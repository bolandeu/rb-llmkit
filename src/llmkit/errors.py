"""Исключения llmkit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .core import Answer, Attempt

# Коды выхода CLI `llm` и их смысл (conventions.md cli-builder; 4 — «проект не
# инициализирован» — у llmkit не бывает) — `exitCodes` в `llm describe --json`.
# tests/test_describe.py падает, если ошибка здесь или в cli/output.py берёт код не из списка.
EXIT_CODES: dict[int, str] = {
    0: "Успех",
    1: "Непредвиденная ошибка; база расходов не смигрирована",
    2: "Неверные аргументы или конфиг",
    3: "Нет ключа провайдера или входа в подписку",
    5: "Все модели цепочки упали (сбой провайдера) или база расходов недоступна",
    6: "Базу расходов смигрировал более новый релиз llmkit",
}


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


class LoginMissing(KeyMissing):
    """Провайдер по подписке: нет входа или не установлен CLI."""

    def __init__(self, provider: str, action: str) -> None:
        self.provider = provider
        self.env_var = ""
        self.action = action
        LlmKitError.__init__(self, f"нет входа в подписку для провайдера {provider}: {action}")


class TemplateError(LlmKitError):
    """Шаблон промпта не разбирается или ссылается на несуществующий partial."""


class TemplateVariableMissing(TemplateError):
    """Строгий режим: переменной шаблона нет в данных; `name` — как в теге (`user.city`)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"в переменных шаблона нет {name!r}")


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


class DatabaseError(LlmKitError):
    """Ошибка слоя БД (llmkit.db): код и код выхода — для конверта CLI."""

    def __init__(self, code: str, message: str, *, action: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code


class InvalidArguments(DatabaseError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, exit_code=2)


class DatabaseUnavailable(DatabaseError):
    """`LLMKIT_DATABASE_URL` задан, но базой не воспользоваться: недоступна, чужой пароль, не PostgreSQL.

    Никогда не подменяется локальной SQLite: записи туда молча пропали бы из общей базы.
    """

    def __init__(self, message: str, *, action: str | None = None) -> None:
        super().__init__(
            "DATABASE_UNAVAILABLE",
            message,
            action=action or "проверьте строку подключения и доступность сервера, затем повторите",
            exit_code=5,
        )


class DatabaseNotMigrated(DatabaseError):
    """Схема общей базы отстала от миграций этой версии llmkit."""

    def __init__(self, current: str | None, head: str) -> None:
        super().__init__(
            "DATABASE_NOT_MIGRATED",
            f"схема базы на ревизии {current or 'none'}, этой версии llmkit нужна {head}",
            action="выполните `llm db upgrade` выпущенной версией (меняет общую базу)",
            exit_code=1,
        )


class DatabaseTooNew(DatabaseError):
    """Базу смигрировал более новый релиз: обновлять нужно llmkit."""

    def __init__(self, current: str) -> None:
        super().__init__(
            "CLI_TOO_OLD",
            f"схема базы на ревизии {current}, которой эта версия llmkit не знает: её смигрировал более новый релиз",
            action="обновите llmkit (`uv tool upgrade rb-llmkit` или пин в проекте), затем повторите",
            exit_code=6,
        )
