"""Общие фикстуры: конфиг, кэш и журнал — во временных каталогах, сети нет."""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from llmkit import LlmKit
from llmkit import core as core_mod

# Typer читает эти переменные один раз при импорте и после этого форсирует терминальный вывод — как на CI.
CI_ENV = {"GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "PY_COLORS": "1"}

# Routing тестов: провайдеры и цепочка приходят данными (routing v1), встроенных нет.
ROUTING: dict = {
    "providers": {
        "a": {"protocol": "openai_compatible", "base_url": "http://localhost:11111/v1", "key_env": "TEST_A_KEY"},
        "b": {"protocol": "openai_compatible", "base_url": "http://localhost:22222/v1", "key_env": "TEST_B_KEY"},
    },
    "chain": ["a/m1", "b/m2"],
    "prices": {"a/m1": {"input": 1.0, "output": 2.0}},
}


def settings(tmp_path) -> dict:
    """Настройки вызовов тестов вместо дефолтов кода (config.toml больше не читается)."""
    return {
        "defaults": {"temperature": 0.0, "timeout": 5, "max_tokens": 100, "concurrency": 2},
        "cache": {"enabled": True, "ttl_days": 30, "path": str(tmp_path / "cache.sqlite")},
        "usage": {"path": str(tmp_path / "usage.sqlite")},
        "budget": {"daily_usd": 20.0},
        "retry": {"timeout": 1, "rate_limit": 2, "server": 2, "invalid_output": 2},
    }


# Ошибки провайдеров: классификация идёт по имени класса, поэтому эти
# заглушки проходят ровно тот же путь, что настоящие исключения LiteLLM.
class Timeout(Exception): ...


class RateLimitError(Exception): ...


class ServiceUnavailableError(Exception): ...


class InternalServerError(Exception): ...


class APIConnectionError(Exception): ...


class InstructorRetryException(Exception): ...


class ContentPolicyViolationError(Exception): ...


class BadRequestError(Exception): ...


class ContextWindowExceededError(BadRequestError): ...


class AuthenticationError(Exception): ...


def response(text: str = "ответ", *, prompt_tokens: int = 10, completion_tokens: int = 5, finish_reason: str = "stop"):
    """Минимальный объект ответа в форме litellm.ModelResponse."""
    return SimpleNamespace(
        model="fake",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class FakeCompletion:
    """Подменяет `litellm.acompletion`: отдаёт заранее заданный сценарий.

    `script` — либо общий список, либо словарь «модель → список»; элемент
    списка это исключение (будет брошено), готовый ответ или callable.
    Последний элемент повторяется, когда сценарий исчерпан.
    """

    def __init__(self, script=None, *, delay: float = 0.0) -> None:
        self.script = script if script is not None else [response()]
        self.delay = delay
        self.calls: list[dict] = []
        self.running = 0
        self.max_running = 0

    def _next(self, model: str):
        steps = self.script[model] if isinstance(self.script, dict) else self.script
        index = min(sum(1 for call in self.calls[:-1] if call["model"] == model), len(steps) - 1)
        return steps[index]

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            step = self._next(kwargs["model"])
            if callable(step) and not isinstance(step, BaseException):
                step = step(**kwargs)
                if inspect.isawaitable(step):
                    step = await step
            if isinstance(step, BaseException):
                raise step
            return step
        finally:
            self.running -= 1

    def models(self) -> list[str]:
        return [call["model"] for call in self.calls]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Настройки, кэш и журнал — только во временном каталоге; routing — только явно."""
    from llmkit import config as config_mod

    monkeypatch.setattr(config_mod, "DEFAULTS", settings(tmp_path))
    monkeypatch.delenv("LLMKIT_ROUTING_FILE", raising=False)
    # Файл routing по умолчанию — в каталоге конфигурации пользователя; настоящий не должен влиять.
    import platformdirs

    monkeypatch.setattr(
        platformdirs, "user_config_dir", lambda appname=None, *a, **k: str(tmp_path / "user-config" / appname)
    )
    for name in list(os.environ):  # ключи машины не должны влиять на тесты
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TEST_A_KEY", "ключ-a")
    monkeypatch.setenv("TEST_B_KEY", "ключ-b")
    monkeypatch.delenv("LLMKIT_CACHE", raising=False)
    monkeypatch.delenv("LLMKIT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("LLMKIT_DATABASE_URL", raising=False)  # никогда не общая PostgreSQL
    # Подписки: ни настоящего файла токенов ChatGPT, ни настоящего CLI claude.
    from llmkit.transports import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "default_path", lambda: tmp_path / "chatgpt-auth.json")
    chatgpt_auth._stores.clear()
    monkeypatch.setenv("CLAUDE_COMMAND", "llmkit-no-such-claude")
    core_mod._warned_budgets.clear()
    core_mod._warned_prices.clear()
    return tmp_path


@pytest.fixture
def slept(monkeypatch):
    """Паузы между ретраями не ждём, а записываем."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(core_mod, "_sleep", fake_sleep)
    return recorded


@pytest.fixture
def make_kit():
    """Фабрика `LlmKit` с подменённым вызовом модели."""

    def factory(completion, **kwargs):
        kwargs.setdefault("routing", ROUTING)
        return LlmKit(completion=completion, **kwargs)

    return factory


@pytest.fixture
def contract_offline(monkeypatch):
    """Офлайн-провайдер для контрактов потребителей (tests/contracts/fixtures.yaml).

    Routing фикстур описывает провайдера `contract`; вызов модели подменён: модели
    contract/broken* падают с 503 (ретраи без пауз), остальные отвечают — текстом
    или JSON {verdict, remarks}, если запрос по схеме. Ключ — фейковый.
    """
    from llmkit.cli import runtime

    def reply(**kwargs):
        if kwargs["model"].startswith("openai/broken"):
            return ServiceUnavailableError("503: contract fixture")
        if "response_format" in kwargs:
            return response('{"verdict": "ok", "remarks": []}')
        return response("ответ офлайн-провайдера")

    completion = FakeCompletion([reply])
    monkeypatch.setenv("LLM_CONTRACT_API_KEY", "contract-fake-key")
    monkeypatch.setattr(core_mod, "_sleep", lambda seconds: asyncio.sleep(0))
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
    return completion


@pytest.fixture
def same_in_ci(request: pytest.FixtureRequest) -> Callable[[str], None]:
    """Перезапускает тесты этого файла по `-k` под CI_ENV в новом интерпретаторе: значение читается при импорте."""
    if request.config.getoption("--snapshot-update"):
        pytest.skip("снимки пишутся: сравнивать ещё не с чем")

    def run(selection: str) -> None:
        options = ["-k", selection, "-p", "no:cacheprovider", "--no-cov", "-q"]
        command = [sys.executable, "-m", "pytest", str(request.path), *options]
        env = {**os.environ, **CI_ENV}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.returncode == 0, result.stdout[-3000:]

    return run
