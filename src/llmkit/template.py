"""Рендер шаблона промпта (mustache, движок combustache).

Экранирование HTML выключено: промпт не HTML, `{{x}}` == `{{{x}}}`. Строгий
режим по умолчанию: промах по контексту (переменная, секция, partial) —
ошибка с именем, а не пустая строка; `strict=False` — как в спецификации.
"""

from __future__ import annotations

from typing import Any

from .errors import TemplateError, TemplateVariableMissing


def render(template: str, data: dict[str, Any], *, strict: bool = True, partials: dict[str, str] | None = None) -> str:
    """Отрендерить `template` с переменными `data`."""
    import combustache
    from combustache import main as engine
    from combustache.ctx import MISSING, Ctx
    from combustache.util import to_str

    # Строгость — в поиске: движок зовёт missing_data() без имени, а инвертированную
    # секцию над промахом рендерит, не зовя его вовсе.
    class _Ctx(Ctx):
        def get(self, key: str) -> Any:
            found = super().get(key)
            if found is MISSING and strict:
                raise TemplateVariableMissing(key)
            return found

    class _Partials(dict):
        def get(self, key, default=None):
            if key not in self and strict:
                raise TemplateError(f"в шаблоне нет partial {key!r}")
            return super().get(key, default)

    opts = {"stringify": to_str, "escape": lambda text: text, "missing_data": lambda: ""}
    try:
        return engine._render(template, _Ctx([data]), _Partials(partials or {}), opts)  # ty: ignore[invalid-argument-type]
    except combustache.CombustacheError as exc:
        raise TemplateError(f"шаблон не разбирается: {exc}") from exc
