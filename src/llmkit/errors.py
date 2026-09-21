"""Исключения llmkit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .core import Attempt


class LlmKitError(Exception):
    """Базовая ошибка библиотеки."""


class ConfigError(LlmKitError):
    """Конфиг не читается, не разбирается или ссылается на несуществующее."""


class KeyMissing(LlmKitError):
    """Ключа провайдера нет ни в аргументах, ни в env, ни в связке ключей."""

    def __init__(self, provider: str, env_var: str = "") -> None:
        self.provider = provider
        self.env_var = env_var
        hint = f"`llm keys set {provider}`" + (f" или `export {env_var}=...`" if env_var else "")
        super().__init__(f"нет ключа для провайдера {provider}: {hint}")


class AllModelsFailed(LlmKitError):
    """Вся цепочка моделей исчерпана, а `default` у задачи не задан."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        details = "; ".join(f"{a.model}: {a.error_type} {a.error}" for a in attempts) or "попыток не было"
        super().__init__(f"все модели цепочки упали ({details})")
