"""Стоимость платных вызовов (T175) — общая схема инструментов (serp, wordstat, context).

cost_source: provider (цена из ответа провайдера) → price_table (цена × токены: routing.prices,
затем справочник LiteLLM) → null (неизвестно, предупреждение); cache и subscription — cost 0.
Конверт ask/json/decide: cost, cost_currency, cost_source, billable_requests, cost_total;
cost_usd оставлен для совместимости (Windmill).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from types import SimpleNamespace

import conftest as fakes
import pytest
from conftest import ROUTING, FakeCompletion, response
from test_decide import QUESTIONS, FakeDecisions, body
from typer.testing import CliRunner

from llmkit import LlmKit, Task
from llmkit import keys as keys_mod
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()
PRICE_A = (10 * 1.0 + 5 * 2.0) / 1_000_000  # ROUTING.prices["a/m1"] × токены response()
ONLY_A = {**ROUTING, "chain": ["a/m1"]}
ONLY_B = {**ROUTING, "chain": ["b/m2"]}


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture
def fake_kit(monkeypatch):
    def install(script):
        completion = FakeCompletion(script)
        monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
        return completion

    return install


class _FakeLitellm:
    """Справочник LiteLLM знает цену только модели `known`."""

    @staticmethod
    def completion_cost(completion_response):
        if getattr(completion_response, "model", None) == "known":
            return 0.5
        raise ValueError("модель не найдена")


@pytest.fixture
def litellm_prices(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", _FakeLitellm)


def with_cost(cost: float, text: str = "ответ"):
    """Ответ OpenRouter через LiteLLM: usage.cost — списано провайдером."""
    reply = response(text)
    reply.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=cost)
    return reply


def with_hidden_cost(cost: float):
    """Так LiteLLM прячет usage.cost OpenRouter: _hidden_params.additional_headers."""
    reply = response()
    reply._hidden_params = {"additional_headers": {"llm_provider-x-litellm-response-cost": cost}}
    return reply


def named(text: str, model: str):
    reply = response(text)
    reply.model = model
    return reply


def run(*args):
    return runner.invoke(app, list(args))


def ask(routing: dict, *extra: str):
    result = run("ask", "вопрос", "--routing", json.dumps(routing), *extra, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def json_cmd(tmp_path, routing: dict, *extra: str):
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    return run("json", "вопрос", "--schema", str(schema), "--routing", json.dumps(routing), *extra, "--json")


def rows(tmp_path) -> list[dict]:
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM llmkit_calls ORDER BY id")]


# --- источник цены ---------------------------------------------------------------------------


def test_provider_cost_beats_routing_price(fake_kit):
    fake_kit([with_cost(0.0123)])
    body_ = ask(ONLY_A)  # у a/m1 есть цена в routing — но провайдер назвал списанное
    assert body_["cost"] == 0.0123 and body_["cost_source"] == "provider"
    assert body_["cost_currency"] == "USD"
    assert body_["cost_usd"] == 0.0123  # старое поле — то же значение
    assert body_["billable_requests"] == 1 and body_["cost_total"] == 0.0123


def test_provider_cost_from_litellm_hidden_params(fake_kit):
    fake_kit([with_hidden_cost(0.007)])
    body_ = ask(ONLY_B)
    assert body_["cost"] == 0.007 and body_["cost_source"] == "provider"


def test_routing_price_is_price_table(fake_kit):
    fake_kit([response()])
    body_ = ask(ONLY_A)
    assert body_["cost_source"] == "price_table"
    assert body_["cost"] == pytest.approx(PRICE_A) and body_["cost_total"] == pytest.approx(PRICE_A)


def test_litellm_reference_price_is_price_table(fake_kit, litellm_prices):
    fake_kit([named("ответ", "known")])
    body_ = ask(ONLY_B)
    assert body_["cost_source"] == "price_table" and body_["cost"] == 0.5


def test_unknown_price_is_null_with_warning(fake_kit, litellm_prices):
    fake_kit([named("ответ", "никто-не-знает")])
    body_ = ask(ONLY_B)
    assert body_["cost"] is None and body_["cost_source"] is None and body_["cost_usd"] is None
    assert body_["cost_total"] is None and body_["billable_requests"] == 1
    assert "price unknown for b/m2" in body_["warnings"]


def test_cache_hit_is_free(fake_kit):
    fake_kit([response()])
    ask(ONLY_A)
    body_ = ask(ONLY_A)
    assert body_["cache_hit"] is True
    assert (body_["cost"], body_["cost_source"], body_["billable_requests"], body_["cost_total"]) == (
        0,
        "cache",
        0,
        0,
    )


# --- billable_requests и cost_total -----------------------------------------------------------


def test_rejected_attempts_are_not_billable(fake_kit, slept):
    # rate limit и 5xx провайдер не списывает (OpenRouter: платят только за успешный ответ).
    fake_kit({"openai/m1": [fakes.RateLimitError("429"), fakes.ServiceUnavailableError("503"), response()]})
    body_ = ask(ONLY_A)
    assert body_["billable_requests"] == 1
    assert body_["cost_total"] == pytest.approx(PRICE_A)


def test_fallen_model_without_answer_is_not_billable(fake_kit):
    fake_kit({"openai/m1": [fakes.BadRequestError("400")], "openai/m2": [with_cost(0.01)]})
    body_ = ask(ROUTING)
    assert body_["model"] == "b/m2"
    assert body_["billable_requests"] == 1 and body_["cost_total"] == 0.01


def test_unparsable_json_is_billable(fake_kit, tmp_path):
    # Ответ получен и списан, но не разобрался — повтор на той же модели платный.
    fake_kit({"openai/m1": [response("не json"), response('{"x": 1}')]})
    result = json_cmd(tmp_path, ONLY_A)
    assert result.exit_code == 0, result.output
    body_ = json.loads(result.stdout)
    assert body_["billable_requests"] == 2
    assert body_["cost"] == pytest.approx(PRICE_A)
    assert body_["cost_total"] == pytest.approx(2 * PRICE_A)


def test_unparsable_json_uses_provider_cost(fake_kit, tmp_path):
    fake_kit({"openai/m1": [with_cost(0.02, "не json"), with_cost(0.03, '{"x": 1}')]})
    body_ = json.loads(json_cmd(tmp_path, ONLY_A).stdout)
    assert body_["billable_requests"] == 2 and body_["cost_total"] == pytest.approx(0.05)
    assert body_["cost"] == 0.03


def test_empty_answer_is_not_billable(fake_kit):
    # Пустой ответ без токенов ответа — zero completion insurance OpenRouter: не списывается.
    fake_kit({"openai/m1": [response(" ", completion_tokens=0)], "openai/m2": [with_cost(0.01)]})
    body_ = ask(ROUTING)
    assert body_["billable_requests"] == 1 and body_["cost_total"] == 0.01


def test_unknown_price_of_billable_attempt_makes_total_unknown(fake_kit, tmp_path):
    fake_kit({"openai/m2": [response("не json"), with_cost(0.03, '{"x": 1}')]})
    body_ = json.loads(json_cmd(tmp_path, ONLY_B).stdout)
    assert body_["billable_requests"] == 2
    assert body_["cost"] == 0.03 and body_["cost_total"] is None


def test_whole_chain_failed_reports_spent(fake_kit, tmp_path):
    fake_kit({"openai/m1": [response("не json")]})
    result = json_cmd(tmp_path, ONLY_A, "--no-retry")
    assert result.exit_code == 5
    error = json.loads(result.stdout)["error"]
    assert error["billable_requests"] == 1 and error["cost_total"] == pytest.approx(PRICE_A)
    assert error["cost_currency"] == "USD"


# --- decide --------------------------------------------------------------------------------


def test_decide_envelope_has_cost_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(decisions=FakeDecisions(body()), **kwargs))
    routing = {
        "providers": {"openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"}},
        "chain": ["openrouter/~typesafe/jev-latest"],
    }
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    result = run("decide", "s", "--questions", str(questions), "--routing", json.dumps(routing), "--json")
    assert result.exit_code == 0, result.output
    body_ = json.loads(result.stdout)
    assert body_["cost_source"] == "provider" and body_["cost"] == pytest.approx(1.7934e-05)
    assert body_["cost_currency"] == "USD" and body_["billable_requests"] == 1
    assert body_["cost_total"] == pytest.approx(1.7934e-05)


# --- библиотека ----------------------------------------------------------------------------


async def test_library_answer_has_billable_and_total(make_kit):
    instance = make_kit(FakeCompletion({"openai/m1": [fakes.BadRequestError("400")], "openai/m2": [with_cost(0.01)]}))
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.cost_source == "provider" and answer.cost_usd == 0.01
    assert answer.billable_requests == 1 and answer.cost_total == 0.01
    assert answer.cost_known


async def test_library_unknown_price_source_is_none(make_kit):
    instance = make_kit(FakeCompletion([response()]))
    answer = await instance.ask(Task(user="вопрос", chain=["b/m2"]))
    assert answer.cost_usd is None and answer.cost_source is None and answer.cost_known is False


# --- учёт ------------------------------------------------------------------------------------


def test_usage_rows_have_cost_source_and_billable(fake_kit, tmp_path):
    fake_kit({"openai/m1": [fakes.BadRequestError("400")], "openai/m2": [with_cost(0.01)]})
    ask(ROUTING)
    ask(ROUTING)  # из кэша
    failed, ok, cached = rows(tmp_path)
    assert (failed["status"], failed["billable"], failed["cost_source"]) == ("failed", 0, None)
    assert (ok["status"], ok["billable"], ok["cost_source"], ok["cost_usd"]) == ("ok", 1, "provider", 0.01)
    assert (cached["status"], cached["billable"], cached["cost_source"]) == ("cache", 0, "cache")


def test_usage_row_of_billable_failed_attempt(fake_kit, tmp_path):
    fake_kit({"openai/m1": [response("не json"), response('{"x": 1}')]})
    json_cmd(tmp_path, ONLY_A)
    failed, ok = rows(tmp_path)
    assert (failed["status"], failed["error_type"], failed["billable"]) == ("failed", "invalid_output", 1)
    assert failed["cost_source"] == "price_table" and failed["cost_usd"] == pytest.approx(PRICE_A)
    assert ok["billable"] == 1


def test_usage_row_unknown_price(fake_kit, tmp_path, litellm_prices):
    fake_kit([named("ответ", "никто-не-знает")])
    ask(ONLY_B)
    (row,) = rows(tmp_path)
    assert row["cost_source"] is None and row["cost_known"] == 0 and row["billable"] == 1


def test_v1_view_has_cost_source_and_billable(fake_kit, tmp_path):
    fake_kit([with_cost(0.01)])
    ask(ONLY_A)
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        row = connection.execute("SELECT cost_source, billable, cost_usd FROM llmkit_v1_calls").fetchone()
    assert row == ("provider", 1, 0.01)
