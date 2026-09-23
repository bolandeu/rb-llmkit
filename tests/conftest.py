"""Общие фикстуры: конфиг, кэш и журнал — во временных каталогах, сети нет."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from llmkit import LlmKit
from llmkit import core as core_mod

CONFIG_TEMPLATE = """
[providers.a]
kind = "openai_compatible"
base_url = "http://localhost:11111/v1"
api_key_env = "TEST_A_KEY"

[providers.b]
kind = "openai_compatible"
base_url = "http://localhost:22222/v1"
api_key_env = "TEST_B_KEY"

[providers.a.prices]
"m1" = {{ input = 1.0, output = 2.0 }}

[levels]
cheap = ["a/m1", "b/m2"]
solo = ["a/m1"]

[defaults]
level = "cheap"
temperature = 0.0
timeout = 5
max_tokens = 100
concurrency = 2

[cache]
enabled = true
ttl_days = 30
path = "{cache}"

[usage]
path = "{usage}"

[retry]
timeout = 1
rate_limit = 2
server = 2
invalid_output = 2
"""


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
    """Конфиг, кэш и журнал — только во временном каталоге."""
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG_TEMPLATE.format(cache=tmp_path / "cache.sqlite", usage=tmp_path / "usage.sqlite"), encoding="utf-8"
    )
    monkeypatch.setenv("LLMKIT_CONFIG", str(path))
    monkeypatch.setenv("TEST_A_KEY", "ключ-a")
    monkeypatch.setenv("TEST_B_KEY", "ключ-b")
    monkeypatch.delenv("LLMKIT_CACHE", raising=False)
    monkeypatch.delenv("LLMKIT_LOG_LEVEL", raising=False)
    # Подписки: ни настоящего файла токенов ChatGPT, ни настоящего CLI claude.
    from llmkit.transports import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "default_path", lambda: tmp_path / "chatgpt-auth.json")
    chatgpt_auth._stores.clear()
    monkeypatch.setenv("CLAUDE_COMMAND", "llmkit-no-such-claude")
    core_mod._warned_budgets.clear()
    core_mod._warned_prices.clear()
    return path


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
        return LlmKit(completion=completion, **kwargs)

    return factory
