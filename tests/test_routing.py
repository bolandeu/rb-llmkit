"""Routing v1 (T86): провайдеры и цепочка приходят данными; сценарии R1–R14."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import conftest as fakes
import jsonschema
import pytest
from conftest import ROUTING, FakeCompletion, response
from test_decide import QUESTIONS, FakeDecisions
from typer.testing import CliRunner

from llmkit import LlmKit, RoutingInvalid, RoutingMissing, Task
from llmkit import keys as keys_mod
from llmkit import routing as routing_mod
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()
DATA = Path(__file__).parent / "data"
SECRET_KEY = "sk-секретный-ключ-0001"

OPENROUTER = {
    "providers": {"openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"}},
    "chain": ["openrouter/a", "openrouter/b"],
}


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture
def fake_kit(monkeypatch):
    """Подменяет вызов модели в CLI; routing приходит из аргументов команды."""

    def install(script=None):
        completion = FakeCompletion(script if script is not None else [anonymous("ответ модели")])
        monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
        return completion

    return install


def anonymous(text: str = "ответ"):
    """Ответ, в котором провайдер не назвал версию модели."""
    reply = response(text)
    reply.model = None
    return reply


def named(text: str, model: str):
    reply = response(text)
    reply.model = model
    return reply


def run(*args, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def payload(result) -> dict:
    return json.loads(result.stdout)


def usage_rows(tmp_path) -> list[dict]:
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM llmkit_calls ORDER BY id")]


# --- R1: вызов по routing из аргумента ------------------------------------------------


def test_r1_ask_goes_to_first_model_of_chain(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", SECRET_KEY)
    fake = fake_kit()
    routing = {**OPENROUTER, "prices": {"openrouter/a": {"input": 1.0, "output": 2.0}}}
    result = run("ask", "вопрос", "--routing", json.dumps(routing), "--json")
    assert result.exit_code == 0, result.output
    body = payload(result)
    assert body["ok"] is True and body["text"] == "ответ модели"
    assert body["model"] == "openrouter/a"
    assert body["served_model"] == "openrouter/a"  # провайдер версию не назвал — элемент цепочки
    assert body["provider"] == "openrouter"
    assert (body["tokens_in"], body["tokens_out"]) == (10, 5)
    assert body["cost_usd"] == pytest.approx((10 * 1.0 + 5 * 2.0) / 1_000_000)
    assert body["cost_source"] == "routing"
    assert body["cache_hit"] is False
    assert body["chain_position"] == 0 and body["attempts"] == [] and body["warnings"] == []
    assert fake.calls[0]["model"] == "openrouter/a"
    assert fake.calls[0]["api_key"] == SECRET_KEY
    assert SECRET_KEY not in result.output


def test_r1_served_model_is_what_provider_returned(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake_kit([named("ответ", "a-2026-09-01")])
    body = payload(run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json"))
    assert body["model"] == "openrouter/a" and body["served_model"] == "a-2026-09-01"


def test_r1_second_call_is_cache_hit(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake = fake_kit()
    run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json")
    body = payload(run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json"))
    assert body["cache_hit"] is True and body["text"] == "ответ модели"
    assert len(fake.calls) == 1


# --- R2: фолбэк по цепочке --------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (fakes.Timeout("долго"), "timeout"),
        (fakes.ServiceUnavailableError("503"), "server"),
        (fakes.RateLimitError("429"), "rate_limit"),
    ],
)
def test_r2_failed_model_yields_to_next(fake_kit, monkeypatch, tmp_path, slept, failure, code):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake_kit({"openrouter/a": [failure], "openrouter/b": [anonymous("от b")]})
    result = run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--no-retry", "--json")
    assert result.exit_code == 0, result.output
    body = payload(result)
    assert body["text"] == "от b"
    assert body["model"] == "openrouter/b" and body["served_model"] == "openrouter/b"
    assert body["chain_position"] == 1
    assert body["attempts"] == [{"model": "openrouter/a", "error_code": code}]
    rows = usage_rows(tmp_path)
    assert [(row["model"], row["status"]) for row in rows] == [("openrouter/a", "failed"), ("openrouter/b", "ok")]
    assert rows[1]["served_model"] == "openrouter/b"


def test_r2_whole_chain_failed_is_exit_5_with_attempts(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake_kit([fakes.BadRequestError("нет")])
    result = run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json")
    assert result.exit_code == 5
    error = payload(result)["error"]
    assert error["code"] == "PROVIDER_ERROR"
    assert error["attempts"] == [
        {"model": "openrouter/a", "error_code": "bad_request"},
        {"model": "openrouter/b", "error_code": "bad_request"},
    ]


# --- R3: routing из файла и из LLMKIT_ROUTING_FILE --------------------------------------


def test_r3_routing_from_file(fake_kit, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake = fake_kit()
    path = tmp_path / "rb-run" / "r.json"
    path.parent.mkdir()
    path.write_text(json.dumps(OPENROUTER), encoding="utf-8")
    result = run("ask", "вопрос", "--routing", str(path), "--json")
    assert result.exit_code == 0, result.output
    assert payload(result)["model"] == "openrouter/a" and fake.models() == ["openrouter/a"]


def test_r3_routing_from_env_file(fake_kit, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake_kit()
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(OPENROUTER), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert payload(result)["model"] == "openrouter/a"


def test_r3_argument_wins_over_env_file(fake_kit, monkeypatch, tmp_path):
    fake = fake_kit()
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(OPENROUTER), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    result = run("ask", "вопрос", "--routing", json.dumps(ROUTING), "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["openai/m1"]


def test_r3_missing_routing_file_is_routing_invalid(fake_kit, tmp_path):
    fake_kit()
    result = run("ask", "вопрос", "--routing", str(tmp_path / "нет.json"), "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "ROUTING_INVALID"


# --- R4: цена ------------------------------------------------------------------------------


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


def test_r4_price_from_routing(fake_kit, litellm_prices):
    fake_kit([named("ответ", "known")])
    routing = {**ROUTING, "chain": ["a/m1"]}
    body = payload(run("ask", "вопрос", "--routing", json.dumps(routing), "--json"))
    assert body["cost_source"] == "routing"  # routing главнее справочника LiteLLM


def test_r4_price_from_litellm(fake_kit, litellm_prices):
    fake_kit([named("ответ", "known")])
    routing = {**ROUTING, "chain": ["b/m2"]}
    body = payload(run("ask", "вопрос", "--routing", json.dumps(routing), "--json"))
    assert body["cost_source"] == "litellm" and body["cost_usd"] == 0.5


def test_r4_unknown_price_is_null_with_warning(fake_kit, litellm_prices, tmp_path):
    fake_kit([named("ответ", "никто-не-знает")])
    routing = {**ROUTING, "chain": ["b/m2"]}
    result = run("ask", "вопрос", "--routing", json.dumps(routing), "--json")
    assert result.exit_code == 0
    body = payload(result)
    assert body["cost_usd"] is None and body["cost_source"] == "unknown"
    assert "price unknown for b/m2" in body["warnings"]
    assert usage_rows(tmp_path)[0]["cost_known"] == 0


async def test_r4_library_answer_has_cost_source(make_kit, litellm_prices):
    instance = make_kit(FakeCompletion([named("ответ", "никто-не-знает")]))
    answer = await instance.ask(Task(user="вопрос", chain=["b/m2"]))
    assert answer.cost_usd is None and answer.cost_source == "unknown"
    assert "price unknown for b/m2" in answer.warnings


# --- R5: routing нет ------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["ask", "json", "decide"])
def test_r5_no_routing_is_exit_2(fake_kit, tmp_path, command):
    fake = fake_kit()
    extra = {
        "ask": [],
        "json": ["--schema", str(_schema(tmp_path))],
        "decide": ["--questions", str(_questions(tmp_path))],
    }[command]
    result = run(command, "вопрос", *extra, "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "ROUTING_MISSING"
    assert "--routing" in error["action"] and "LLMKIT_ROUTING_FILE" in error["action"]
    assert fake.calls == []


def _schema(tmp_path) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    return path


def _questions(tmp_path) -> Path:
    path = tmp_path / "q.json"
    path.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    return path


def test_r5_old_config_file_is_not_read(fake_kit, monkeypatch, tmp_path):
    fake_kit()
    old = tmp_path / "config.toml"
    old.write_text('[levels]\ncheap = ["a/m1"]\n', encoding="utf-8")
    monkeypatch.setenv("LLMKIT_CONFIG", str(old))
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "ROUTING_MISSING"


# --- R6: routing не по схеме ------------------------------------------------------------------

INVALID = [
    ({"providers": ROUTING["providers"]}, "/chain"),
    ({**ROUTING, "chain": []}, "/chain"),
    ({**ROUTING, "chain": ["a/m1", "без-слэша"]}, "/chain/1"),
    ({**ROUTING, "chain": ["нет/m1"]}, "/chain/0"),
    ({**ROUTING, "providers": {**ROUTING["providers"], "a": {"protocol": "telepathy"}}}, "/providers/a/protocol"),
]


@pytest.mark.parametrize(("routing", "path"), INVALID)
def test_r6_invalid_routing_is_exit_2_with_path(fake_kit, routing, path):
    fake = fake_kit()
    result = run("ask", "вопрос", "--routing", json.dumps(routing), "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "ROUTING_INVALID" and error["path"] == path
    assert fake.calls == []


def test_r6_broken_json_is_routing_invalid(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--routing", "{не json", "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "ROUTING_INVALID"


@pytest.mark.parametrize(("routing", "path"), INVALID)
def test_r6_library_raises_routing_invalid(routing, path):
    with pytest.raises(RoutingInvalid) as caught:
        routing_mod.parse(routing)
    assert caught.value.path == path


# --- R7: ключи ----------------------------------------------------------------------------------


def test_r7_new_env_name(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "новый")
    monkeypatch.setenv("OPENROUTER_API_KEY", "старый")
    fake = fake_kit()
    body = payload(run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json"))
    assert fake.calls[0]["api_key"] == "новый"
    assert not any("rename" in warning for warning in body["warnings"])


def test_r7_key_env_defaults_to_llm_provider_api_key(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_MY_GATE_API_KEY", "ключ")
    fake = fake_kit()
    routing = {
        "providers": {"my-gate": {"protocol": "openai_compatible", "base_url": "http://gate/v1"}},
        "chain": ["my-gate/m"],
    }
    assert run("ask", "вопрос", "--routing", json.dumps(routing), "--json").exit_code == 0
    assert fake.calls[0]["api_key"] == "ключ"


@pytest.mark.parametrize(
    ("provider", "protocol", "legacy"),
    [
        ("openrouter", "openrouter", "OPENROUTER_API_KEY"),
        ("ccode", "openai_compatible", "CCODE_API_KEY"),
        ("anymodel", "openai_compatible", "ANYMODEL_API_KEY"),
        ("ollama", "ollama", "OLLAMA_API_KEY"),
    ],
)
def test_r7_legacy_env_name_with_warning(fake_kit, monkeypatch, provider, protocol, legacy):
    monkeypatch.setenv(legacy, "старый")
    fake = fake_kit()
    spec = {"protocol": protocol}
    if protocol in ("openai_compatible", "ollama"):
        spec["base_url"] = "http://gate/v1"
    routing = {"providers": {provider: spec}, "chain": [f"{provider}/m"]}
    result = run("ask", "вопрос", "--routing", json.dumps(routing), "--json")
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["api_key"] == "старый"
    new_name = f"LLM_{provider.upper()}_API_KEY"
    assert any(legacy in w and f"rename to {new_name}" in w for w in payload(result)["warnings"])


def test_r7_keychain_fallback(fake_kit, monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: "из-связки" if provider == "openrouter" else None)
    fake = fake_kit()
    assert run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json").exit_code == 0
    assert fake.calls[0]["api_key"] == "из-связки"


def test_r7_no_key_anywhere_is_exit_3(fake_kit, tmp_path):
    fake = fake_kit()
    result = run("ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json")
    assert result.exit_code == 3
    error = payload(result)["error"]
    assert error["code"] == "AUTH_MISSING" and error["variable"] == "LLM_OPENROUTER_API_KEY"
    assert fake.calls == []


def test_r7_key_never_printed_or_journaled(fake_kit, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", SECRET_KEY)
    fake_kit([fakes.AuthenticationError(f"bad key {SECRET_KEY}")])
    result = run("--verbose", "ask", "вопрос", "--routing", json.dumps(OPENROUTER), "--json")
    assert result.exit_code == 3
    assert SECRET_KEY not in result.output
    assert SECRET_KEY not in json.dumps(usage_rows(tmp_path), ensure_ascii=False)


# --- R8: подписочные протоколы ------------------------------------------------------------------


def test_r8_subscription_protocols_need_no_key_env():
    parsed = routing_mod.parse(
        {
            "providers": {"gpt": {"protocol": "chatgpt"}, "cl": {"protocol": "claude_cli"}},
            "chain": ["gpt/gpt-5", "cl/sonnet"],
        }
    )
    assert parsed.providers["gpt"].key_env is None


def test_r8_subscription_call_goes_through_transport(monkeypatch, tmp_path):
    from llmkit.transports import chatgpt, chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "read_auth", lambda path: SimpleNamespace(plan_type="plus"))
    calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return response("из подписки")

    monkeypatch.setattr(chatgpt, "acompletion", fake_acompletion)
    instance = LlmKit(routing={"providers": {"gpt": {"protocol": "chatgpt"}}, "chain": ["gpt/gpt-5"]})
    answer = instance.ask_sync(Task(user="вопрос"))
    assert answer.data == "из подписки" and calls[0]["model"] == "gpt-5"
    assert answer.cost_usd == 0.0


# --- R9: уровней нет ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["ask", "json", "decide"])
def test_r9_level_option_is_removed_with_hint(fake_kit, tmp_path, command):
    fake_kit()
    extra = {
        "ask": [],
        "json": ["--schema", str(_schema(tmp_path))],
        "decide": ["--questions", str(_questions(tmp_path))],
    }[command]
    result = run(command, "вопрос", *extra, "--level", "cheap", "--routing", json.dumps(ROUTING), "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "INVALID_ARGUMENTS"
    assert "-m" in error["action"] and "routing.chain" in error["action"]


def test_r9_library_has_no_levels():
    with pytest.raises(TypeError):
        LlmKit(routing=ROUTING, level="cheap")  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError):
        Task(user="x", level="cheap")  # ty: ignore[unknown-argument]


def test_r9_levels_key_in_routing_is_invalid():
    with pytest.raises(RoutingInvalid) as caught:
        routing_mod.parse({**ROUTING, "levels": {"cheap": ["a/m1"]}})
    assert caught.value.path == "/levels"


# --- R10: импорт старого config.toml ------------------------------------------------------------


def test_r10_import_legacy_config():
    result = run("routing", "import", str(DATA / "legacy_config.toml"), "--json")
    assert result.exit_code == 0, result.output
    body = payload(result)
    routing = body["routing"]
    prices = routing["prices"]
    by_provider: dict[str, int] = {}
    for ref in prices:
        by_provider[ref.partition("/")[0]] = by_provider.get(ref.partition("/")[0], 0) + 1
    assert by_provider == {"ccode": 5, "anymodel": 21, "openrouter": 1}
    assert prices["ccode/gpt-5.6-terra"] == {"input": 0.09, "output": 0.54}
    assert prices["anymodel/cx/gpt-6-luna"] == {"input": 0.075, "output": 0.075}
    assert prices["openrouter/google/gemini-2.5-flash-lite"] == {"input": 0.10, "output": 0.40}
    providers = routing["providers"]
    # Провайдеры, которые раньше были встроенными, переносятся со своими адресами.
    assert providers["ccode"] == {
        "protocol": "openai_compatible",
        "base_url": "https://all-api.ccode.dev/v1",
        "key_env": "LLM_CCODE_API_KEY",
        "mode": "TOOLS",
    }
    assert providers["openrouter"] == {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"}
    assert providers["chatgpt"] == {"protocol": "chatgpt"}
    assert "chain" not in routing
    assert body["levels"]["cheap"][0] == "ccode/gpt-5.6-terra"
    assert set(body["levels"]) >= {"cheap", "judge", "strong", "decide"}
    # Результат сам проходит validate (как файл провайдеров под -m).
    assert routing_mod.parse(routing, require_chain=False).providers


def test_r10_import_drops_keys_and_reports_it(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[providers.x]\nkind = "openai_compatible"\nbase_url = "http://x/v1"\napi_key = "sk-не-переносить"\n',
        encoding="utf-8",
    )
    result = run("routing", "import", str(path), "--json")
    assert result.exit_code == 0, result.output
    assert "sk-не-переносить" not in result.stdout
    body = payload(result)
    assert body["routing"]["providers"]["x"]["key_env"] == "LLM_X_API_KEY"
    assert any("api_key" in warning for warning in body["warnings"])


def test_r10_import_human_output_is_routing_json():
    result = run("routing", "import", str(DATA / "legacy_config.toml"))
    assert result.exit_code == 0
    assert json.loads(result.stdout)["routing"]["providers"]["anymodel"]["protocol"] == "openai_compatible"


def test_r10_import_missing_file_is_exit_2(tmp_path):
    result = run("routing", "import", str(tmp_path / "нет.toml"), "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


# --- R11: validate ------------------------------------------------------------------------------


def test_r11_validate_ok_from_string_and_file(tmp_path):
    result = run("routing", "validate", json.dumps(ROUTING), "--json")
    assert result.exit_code == 0, result.output
    body = payload(result)
    assert body["ok"] is True and body["chain"] == ["a/m1", "b/m2"] and body["providers"] == ["a", "b"]
    path = tmp_path / "r.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    assert run("routing", "validate", str(path)).exit_code == 0


@pytest.mark.parametrize(("routing", "path"), INVALID)
def test_r11_validate_reports_path(routing, path):
    result = run("routing", "validate", json.dumps(routing), "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "ROUTING_INVALID" and error["path"] == path


def test_r11_validate_without_chain_flag():
    providers_only = {"providers": ROUTING["providers"]}
    assert run("routing", "validate", json.dumps(providers_only), "--json").exit_code == 2
    assert run("routing", "validate", json.dumps(providers_only), "--providers-only", "--json").exit_code == 0


# --- контракт routing-v1: схема и векторы -------------------------------------------------------


def _contract(name: str):
    from importlib import resources

    return json.loads(resources.files("llmkit").joinpath("contracts", name).read_text(encoding="utf-8"))


def test_contract_schema_and_vectors_ship_in_package():
    schema = _contract("routing-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    vectors = _contract("routing-v1.vectors.json")
    assert {v["name"] for v in vectors["valid"]} and {v["name"] for v in vectors["invalid"]}


def test_contract_vectors_match_llmkit():
    vectors = _contract("routing-v1.vectors.json")
    for vector in vectors["valid"]:
        routing_mod.parse(vector["routing"], require_chain=vector.get("require_chain", True))
    for vector in vectors["invalid"]:
        with pytest.raises(RoutingInvalid) as caught:
            routing_mod.parse(vector["routing"])
        assert caught.value.path == vector["error_path"], vector["name"]


def test_contract_vectors_match_json_schema():
    """Схема проверяет форму; ссылки цепочки на провайдеров — только llmkit (`schema: false` у вектора)."""
    validator = jsonschema.Draft202012Validator(_contract("routing-v1.schema.json"))
    vectors = _contract("routing-v1.vectors.json")
    for vector in vectors["valid"]:
        assert not list(validator.iter_errors(vector["routing"])), vector["name"]
    for vector in vectors["invalid"]:
        if vector.get("schema", True):
            assert list(validator.iter_errors(vector["routing"])), vector["name"]


# --- R12: шаблоны и routing вместе -----------------------------------------------------------


def test_r12_template_from_stdin_with_routing_argument(fake_kit, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake = fake_kit()
    result = run(
        "ask",
        "--template",
        "-",
        "--vars",
        '{"city": "Москва"}',
        "--routing",
        json.dumps(OPENROUTER),
        "--json",
        input="Погода в {{city}}?",
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["messages"][-1]["content"] == "Погода в Москва?"


def test_r12_routing_is_not_read_from_stdin(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--routing", "-", "--json", input=json.dumps(ROUTING))
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "ROUTING_INVALID"


# --- R13: библиотека -----------------------------------------------------------------------------


def test_r13_library_with_routing_dict():
    fake = FakeCompletion([anonymous("ответ")])
    instance = LlmKit(routing=ROUTING, completion=fake)
    answer = instance.ask_sync(Task(user="вопрос"))
    assert answer.model == "a/m1" and answer.served_model == "a/m1" and answer.cost_source == "routing"
    assert answer.chain_position == 0 and answer.cache_hit is False


def test_r13_library_without_routing_fails_on_first_call_only():
    instance = LlmKit(completion=FakeCompletion())  # создать можно
    with pytest.raises(RoutingMissing):
        instance.ask_sync(Task(user="вопрос"))


def test_r13_library_does_not_read_routing_env(monkeypatch, tmp_path):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    with pytest.raises(RoutingMissing):
        LlmKit(completion=FakeCompletion()).ask_sync(Task(user="вопрос"))


def test_r13_invalid_routing_fails_at_construction():
    with pytest.raises(RoutingInvalid):
        LlmKit(routing={"providers": {}, "chain": ["a/m1"]})


# --- R14: повторяемый -m --------------------------------------------------------------------------


def test_r14_repeated_model_flag_is_chain(fake_kit, slept):
    fake = fake_kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [anonymous("от второй")]})
    providers_only = {"providers": ROUTING["providers"]}
    result = run(
        "ask", "вопрос", "--routing", json.dumps(providers_only), "-m", "a/m1", "-m", "b/m2", "--no-retry", "--json"
    )
    assert result.exit_code == 0, result.output
    assert fake.models() == ["openai/m1", "openai/m2"]
    assert payload(result)["model"] == "b/m2"


def test_r14_model_flag_with_routing_chain_is_invalid(fake_kit):
    fake = fake_kit()
    result = run("ask", "вопрос", "--routing", json.dumps(ROUTING), "-m", "a/m1", "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "ROUTING_INVALID" and error["path"] == "/chain"
    assert "chain задана дважды" in error["message"]
    assert fake.calls == []


def test_r14_model_flag_provider_must_be_described(fake_kit):
    fake_kit()
    providers_only = {"providers": ROUTING["providers"]}
    result = run("ask", "вопрос", "--routing", json.dumps(providers_only), "-m", "zz/m", "--json")
    assert result.exit_code == 2 and payload(result)["error"]["path"] == "/chain/0"


# --- ответ json/decide и учёт ------------------------------------------------------------------


def test_json_command_answer_fields(fake_kit, tmp_path):
    fake_kit([anonymous('{"x": 1}')])
    result = run("json", "вопрос", "--schema", str(_schema(tmp_path)), "--routing", json.dumps(ROUTING), "--json")
    assert result.exit_code == 0, result.output
    body = payload(result)
    assert body["data"] == {"x": 1} and body["model"] == "a/m1" and body["cost_source"] == "routing"
    assert {"tokens_in", "tokens_out", "cache_hit", "chain_position", "attempts", "warnings"} <= set(body)


def test_decide_uses_routing_chain(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake = FakeDecisions()
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(decisions=fake, **kwargs))
    routing = {**OPENROUTER, "chain": ["openrouter/~typesafe/jev-latest"]}
    result = run(
        "decide", "состояние", "--questions", str(_questions(tmp_path)), "--routing", json.dumps(routing), "--json"
    )
    assert result.exit_code == 0, result.output
    body = payload(result)
    assert body["model"] == "openrouter/~typesafe/jev-latest"
    assert body["served_model"] == "typesafe/jev-1.13-20260917"
    assert body["cost_source"] == "provider"
    assert fake.calls[0]["model"] == "~typesafe/jev-latest"


def test_usage_has_tags_but_no_keys_or_template_values(fake_kit, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", SECRET_KEY)
    fake_kit()
    result = run(
        "ask",
        "--template",
        "Привет, {{name}}",
        "--vars",
        '{"name": "значение-переменной"}',
        "--routing",
        json.dumps(OPENROUTER),
        "--tag",
        "level=cheap",
        "--tag",
        "executor=windmill",
        "--json",
    )
    assert result.exit_code == 0, result.output
    rows = usage_rows(tmp_path)
    assert json.loads(rows[0]["tags"])["level"] == "cheap"
    dump = json.dumps(rows, ensure_ascii=False)
    assert SECRET_KEY not in dump and "значение-переменной" not in dump


# --- T138: task_id в конверте — ссылка на строку учёта (llm_call_ref у windmill) -------------------


def _v1_task_ids(tmp_path) -> list[str]:
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        return [row[0] for row in connection.execute("SELECT task_id FROM llmkit_v1_calls ORDER BY id")]


@pytest.mark.parametrize("command", ["ask", "json"])
def test_t138_envelope_task_id_matches_usage(command, fake_kit, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    fake_kit([anonymous('{"x": 1}')])
    extra = ["--schema", str(_schema(tmp_path))] if command == "json" else []
    result = run(command, "вопрос", *extra, "--routing", json.dumps(OPENROUTER), "--json")
    assert result.exit_code == 0, result.output
    task_id = payload(result)["task_id"]
    assert task_id and [row["task_id"] for row in usage_rows(tmp_path)] == [task_id]
    assert _v1_task_ids(tmp_path) == [task_id]
