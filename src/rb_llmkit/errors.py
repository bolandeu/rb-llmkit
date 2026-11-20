"""Исключения llmkit: общий `LlmKitError` и его наследники — ошибки конфига и routing, отсутствие ключа шлюза
(`KeyMissing`), недоступность шлюза (`GatewayUnavailable`), исчерпанный ответ (`AllModelsFailed`) и шаблоны промптов.
Класс ошибки задаёт код выхода CLI (`EXIT_CODES`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .core import Answer, Attempt

# Коды выхода CLI `llm` и их смысл (conventions.md cli-builder; 4 — «проект не
# инициализирован» — у llmkit не бывает) — `exitCodes` в `llm describe --json`.
# tests/test_describe.py падает, если ошибка здесь или в cli/output.py берёт код не из списка.
EXIT_CODES: dict[int, str] = {
    0: "Успех",
    1: "Непредвиденная ошибка",
    2: "Неверные аргументы или конфиг",
    3: "Нет ключа шлюза",
    5: "Шлюз недоступен, шлюз ответил ошибкой или ответ невалиден; журнал шлюза не читается",
}


class LlmKitError(Exception):
    """Базовая ошибка библиотеки."""


class ConfigError(LlmKitError):
    """Конфиг не читается, не разбирается или ссылается на несуществующее."""


class RoutingMissing(ConfigError):
    """Routing не передан: встроенных провайдеров и цепочек нет."""

    def __init__(self, message: str = "routing не передан: встроенных провайдеров и цепочек нет") -> None:
        super().__init__(message)


class RoutingInvalid(ConfigError):
    """Routing не по схеме v1; `path` — JSON Pointer поля (`/chain/1`, `/providers/x/protocol`)."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"routing{' ' + path if path else ''}: {message}")


class KeyMissing(LlmKitError):
    """Переменной с ключом шлюза нет в окружении; `env_var` — её имя."""

    def __init__(self, provider: str, env_var: str = "") -> None:
        self.provider = provider
        self.env_var = env_var
        super().__init__(f"нет ключа для провайдера {provider}: переменная {env_var}")


class TemplateError(LlmKitError):
    """Шаблон промпта не разбирается или ссылается на несуществующий partial."""


class TemplateVariableMissing(TemplateError):
    """Строгий режим: переменной шаблона нет в данных; `name` — как в теге (`user.city`)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"в переменных шаблона нет {name!r}")


class GatewayUnavailable(LlmKitError):
    """Шлюз не ответил, ответил ошибкой или превысил таймаут.

    `url` — адрес шлюза из routing (`base_url`), `kind` — вид сбоя: `server`
    (нет соединения, HTTP-ошибка) или `timeout`. Оба — код выхода 5.
    """

    def __init__(self, url: str, kind: str = "server", detail: str | None = None) -> None:
        self.url = url
        self.kind = kind
        reason = "истёк таймаут" if kind == "timeout" else "запрос не прошёл"
        super().__init__(f"шлюз {url} недоступен: {reason}" + (f" ({detail})" if detail else ""))


class AllModelsFailed(LlmKitError):
    """Ответ шлюза невалиден после всех повторов, а `default` у задачи не задан.

    `error_type` заполнен, когда все попытки упали по одной причине — потребителю
    не нужно разбирать attempts. `answer` — уже посчитанный Answer(source="default"),
    им пользуется `ask_many`, чтобы не собирать его заново.
    """

    def __init__(self, attempts: list[Attempt], answer: Answer | None = None) -> None:
        self.attempts = attempts
        self.answer = answer
        types = {attempt.error_type for attempt in attempts}
        self.error_type: str | None = types.pop() if len(types) == 1 else None
        details = "; ".join(f"{a.model}: {a.error_type} {a.error}" for a in attempts) or "попыток не было"
        super().__init__(f"все модели цепочки упали ({details})")
