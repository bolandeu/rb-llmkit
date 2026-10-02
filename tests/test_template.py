"""Рендер шаблона промпта `llmkit.render`: mustache/spec, строгий режим, без экранирования HTML."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmkit import TemplateError, TemplateVariableMissing, render

SPEC_DIR = Path(__file__).parent / "data" / "mustache_spec"
SPEC_FILES = ["interpolation", "sections", "inverted", "comments", "delimiters", "partials"]

# Экранирование HTML выключено (промпт не HTML, `{{x}}` == `{{{x}}}`): кейсы спецификации,
# которые проверяют именно экранирование, ждут символы как есть, без &amp; &quot; &lt; &gt;.
ESCAPING_OFF = {
    ("interpolation", "HTML Escaping"): 'These characters should be HTML escaped: & " < >\n',
    ("interpolation", "Implicit Iterators - HTML Escaping"): 'These characters should be HTML escaped: & " < >\n',
    ("sections", "Implicit Iterator - HTML Escaping"): '"(&)(")(<)(>)"',
}


def _spec_cases():
    for name in SPEC_FILES:
        for case in json.loads((SPEC_DIR / f"{name}.json").read_text(encoding="utf-8"))["tests"]:
            yield pytest.param(name, case, id=f"{name}: {case['name']}")


SPEC_CASES = list(_spec_cases())


def test_spec_is_complete():
    # Набор вендорен целиком: 42 + 34 + 22 + 12 + 14 + 12; поправки — только к существующим кейсам.
    assert len(SPEC_CASES) == 136
    names = {(param.values[0], param.values[1]["name"]) for param in SPEC_CASES}
    assert set(ESCAPING_OFF) <= names


@pytest.mark.parametrize(("spec", "case"), SPEC_CASES)
def test_mustache_spec(spec, case):
    # Спецификация описывает нестрогий режим: промах по контексту — пустая строка.
    expected = ESCAPING_OFF.get((spec, case["name"]), case["expected"])
    assert render(case["template"], case["data"], partials=case.get("partials"), strict=False) == expected


def test_html_is_not_escaped():
    assert render("{{x}} {{{x}}} {{&x}}", {"x": "<a & 'b'>"}) == "<a & 'b'> <a & 'b'> <a & 'b'>"


def test_strict_by_default_names_missing_variable():
    with pytest.raises(TemplateVariableMissing) as caught:
        render("Привет, {{name}}!", {})
    assert caught.value.name == "name"
    assert "name" in str(caught.value)


def test_strict_names_dotted_variable():
    with pytest.raises(TemplateVariableMissing) as caught:
        render("{{user.city}}", {"user": {"name": "Ия"}})
    assert caught.value.name == "user.city"


def test_strict_reports_variable_inside_section():
    with pytest.raises(TemplateVariableMissing) as caught:
        render("{{#items}}{{title}}: {{price}}\n{{/items}}", {"items": [{"title": "a", "price": 1}, {"title": "b"}]})
    assert caught.value.name == "price"


@pytest.mark.parametrize("template", ["{{#flag}}да{{/flag}}", "{{^flag}}нет{{/flag}}"])
def test_strict_section_over_missing_key_is_an_error(template):
    # Опечатка в имени секции молча выкинула бы кусок промпта: ключ передают явно (false, []).
    with pytest.raises(TemplateVariableMissing) as caught:
        render(template, {})
    assert caught.value.name == "flag"


def test_strict_accepts_present_falsy_and_null_values():
    data = {"flag": False, "items": [], "empty": None, "zero": 0}
    assert render("{{#flag}}x{{/flag}}{{#items}}y{{/items}}[{{empty}}][{{zero}}]", data) == "[][0]"


def test_strict_missing_partial_is_an_error():
    with pytest.raises(TemplateError, match="footer"):
        render("{{>footer}}", {})


def test_lenient_renders_missing_as_empty():
    assert render("Привет, {{name}}!{{#flag}}x{{/flag}}", {}, strict=False) == "Привет, !"


def test_broken_template_is_template_error():
    with pytest.raises(TemplateError):
        render("{{#open}} без закрытия", {"open": True})


def test_missing_variable_is_template_error_too():
    # Потребителю достаточно ловить TemplateError (и LlmKitError).
    from llmkit import LlmKitError

    assert issubclass(TemplateVariableMissing, TemplateError)
    assert issubclass(TemplateError, LlmKitError)
