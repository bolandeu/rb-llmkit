"""Исключения llmkit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .core import Answer, Attempt


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
    """Вся цепочка моделей исчерпана, а `default` у задачи не задан.

    `error_type` заполнен, когда все попытки упали по одной причине (все
    без ключа, все по таймауту) — потребителю не нужно разбирать attempts.
    `answer` — уже посчитанный Answer(source="default"), им пользуется
    `ask_many`, чтобы не собирать его заново.
    """

    def __init__(self, attempts: list[Attempt], answer: Answer | None = None) -> None:
        self.attempts = attempts
        self.answer = answer
        types = {attempt.error_type for attempt in attempts}
        self.error_type: str | None = types.pop() if len(types) == 1 else None
        details = "; ".join(f"{a.model}: {a.error_type} {a.error}" for a in attempts) or "попыток не было"
        super().__init__(f"все модели цепочки упали ({details})")
