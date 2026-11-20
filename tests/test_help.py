"""The --help contract: every command's help is complete, and any change to it shows up in review.

Help text is rendered from command docstrings and `typer.Option`/`Argument`
`help=` strings — it's the documentation agents and humans read, so it's
tested like an API:

- contract tests: every command (walked from the app's registry, so a new
  command is covered automatically) has a docstring with an
  `Example: llm <command> ...` line, every parameter has non-empty help,
  every group has a description;
- snapshots: `<command> --help` is stored in tests/snapshots/help/<command>.txt
  (syrupy). A changed help text fails until the snapshot is refreshed with
  `uv run pytest --snapshot-update`, which puts the new text in the diff.
  A new command fails until its snapshot exists; a removed one leaves an
  orphan file that fails too.
"""

from __future__ import annotations

import inspect
import shlex
import typing
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import typer
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode
from typer.models import ParameterInfo
from typer.testing import CliRunner

from llmkit.cli.main import app

CLI = "llm"
ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "help"
# Fixed width and no colour so the rendering doesn't depend on the terminal running the tests.
HELP_ENV = {"COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}


def _commands(group: typer.Typer, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Callable]]:
    for info in group.registered_commands:
        assert info.callback is not None
        name = info.name or getattr(info.callback, "__name__", "").replace("_", "-")
        yield (*prefix, name), info.callback
    for sub in group.registered_groups:
        assert sub.name is not None and sub.typer_instance is not None
        yield from _commands(sub.typer_instance, (*prefix, sub.name))


def _groups(group: typer.Typer, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], typer.Typer]]:
    for sub in group.registered_groups:
        assert sub.name is not None and sub.typer_instance is not None
        yield (*prefix, sub.name), sub.typer_instance
        yield from _groups(sub.typer_instance, (*prefix, sub.name))


COMMANDS = dict(_commands(app))
GROUPS = dict(_groups(app))
HELP_PAGES = sorted([*COMMANDS, *GROUPS])


def _slug(path: tuple[str, ...]) -> str:
    return "-".join(path)


def _render_help(path: tuple[str, ...]) -> str:
    result = CliRunner().invoke(app, [*path, "--help"], env=HELP_ENV, prog_name=CLI)
    assert result.exit_code == 0, result.output
    # Trailing padding isn't content; keeping it out keeps the diffs readable.
    return "\n".join(line.rstrip() for line in result.output.splitlines()) + "\n"


class HelpSnapshot(SingleFileSnapshotExtension):
    """One plain-text file per help page: tests/snapshots/help/<command>.txt."""

    _write_mode = WriteMode.TEXT
    file_extension = "txt"

    @classmethod
    def dirname(cls, *, test_location) -> str:
        return str(SNAPSHOT_DIR)

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0) -> str:
        return str(index)


@pytest.mark.parametrize("path", HELP_PAGES, ids=_slug)
def test_help_snapshot(path: tuple[str, ...], snapshot) -> None:
    assert _render_help(path) == snapshot(extension_class=HelpSnapshot, name=_slug(path))


def test_no_orphan_help_snapshots() -> None:
    stored = {p.stem for p in SNAPSHOT_DIR.glob("*.txt")}
    expected = {_slug(path) for path in HELP_PAGES}
    assert stored <= expected, f"snapshots for commands that no longer exist: {sorted(stored - expected)}"


def test_db_group_is_gone() -> None:
    """Своего журнала и базы у llmkit нет — и команд для них тоже."""
    assert ("db",) not in GROUPS
    assert [path for path in COMMANDS if path[0] == "db"] == []


@pytest.mark.parametrize("path", [("serve",), ("auth", "login"), ("auth", "logout"), ("config", "path")], ids=_slug)
def test_subscription_and_state_commands_are_gone(path: tuple[str, ...]) -> None:
    """Подписки и свой доступ ушли в шлюз: `serve`, вход в подписку, старая команда про базу."""
    assert path not in COMMANDS


@pytest.mark.parametrize("path", HELP_PAGES, ids=_slug)
def test_no_help_page_names_own_state(path: tuple[str, ...]) -> None:
    """Справка не обещает ни базы, ни кэша, ни меток: их у llmkit больше нет."""
    text = _render_help(path)
    for gone in (
        "LLMKIT_DATABASE_URL",
        "LLMKIT_CACHE",
        "llmkit_calls",
        "llmkit_cache",
        "usage.sqlite",
        "cache.sqlite",
        "--no-cache",
        "cache_hit",
    ):
        assert gone not in text, f"`{_slug(path)}` still mentions {gone}"


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_every_command_takes_json(path: tuple[str, ...]) -> None:
    assert "--json" in _render_help(path)


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_command_docstring_has_summary_and_example(path: tuple[str, ...]) -> None:
    doc = inspect.getdoc(COMMANDS[path]) or ""
    assert doc.strip(), f"`{_slug(path)}` has no docstring — it is the command's --help text"
    invocation = f"{CLI} {' '.join(path)}"
    examples = [line for line in doc.splitlines() if line.startswith("Example:")]
    assert any(invocation in line for line in examples), (
        f"`{_slug(path)}` docstring needs an `Example: {{cli}} {' '.join(path)} ...` line"
    )


@pytest.mark.parametrize("path", sorted(COMMANDS), ids=_slug)
def test_every_parameter_has_help(path: tuple[str, ...]) -> None:
    callback = inspect.unwrap(COMMANDS[path])
    hints = typing.get_type_hints(callback, include_extras=True)
    for name, param in inspect.signature(callback).parameters.items():
        hint = hints.get(name)
        if hint is typer.Context:
            continue
        infos = [m for m in getattr(hint, "__metadata__", ()) if isinstance(m, ParameterInfo)]
        if isinstance(param.default, ParameterInfo):
            infos.append(param.default)
        assert infos, f"`{_slug(path)}` parameter `{name}` must be a typer.Option/Argument with help="
        assert all((info.help or "").strip() for info in infos), f"`{_slug(path)}` parameter `{name}` has no help"


@pytest.mark.parametrize("path", sorted(GROUPS), ids=_slug)
def test_every_group_has_help(path: tuple[str, ...]) -> None:
    assert (GROUPS[path].info.help or "").strip(), f"group `{_slug(path)}` has no description"


def test_help_is_the_same_in_ci(same_in_ci: Callable[[str], None]) -> None:
    same_in_ci("test_help_snapshot")


# --- README: каждая команда и флаг из него существуют -------------------------------

KNOWN = set(COMMANDS) | set(GROUPS) | {()}
GATEWAY_GROUPS = {"image", "audio", "video", "embeddings", "web", "model", "chat"}


def _readme_invocations() -> list[list[str]]:
    """Строки `llm …` из README: команда, аргументы и флаги, как их наберёт читатель."""
    lines = (line.split("  # ", 1)[0].strip() for line in README.read_text(encoding="utf-8").splitlines())
    return [
        shlex.split(line)
        for line in lines
        if line == "llm" or line.startswith("llm ")
        if not any(mark in line for mark in ("<", "…", "...", "$ "))
    ]


def _resolve(tokens: list[str]) -> tuple[tuple[str, ...], set[str]]:
    """Самый длинный путь команды из реестра и флаги после него."""
    path: tuple[str, ...] = ()
    rest = tokens[1:]
    while rest and (*path, rest[0]) in KNOWN:
        path = (*path, rest[0])
        rest = rest[1:]
    return path, {token.split("=", 1)[0] for token in rest if token.startswith("-")}


README_INVOCATIONS = _readme_invocations()


@pytest.mark.parametrize("tokens", README_INVOCATIONS, ids=" ".join)
def test_every_readme_invocation_is_a_real_command(tokens: list[str]) -> None:
    path, _ = _resolve(tokens)
    assert path or len(tokens) == 1, f"README shows `{' '.join(tokens)}`, but no such command exists"


@pytest.mark.parametrize("tokens", README_INVOCATIONS, ids=" ".join)
def test_every_readme_flag_is_in_the_help(tokens: list[str]) -> None:
    path, flags = _resolve(tokens)
    help_text = _render_help(path) if path else _root_help()
    for flag in flags:
        assert flag in help_text, f"README shows `{flag}` for `{' '.join(path)}`, but --help does not have it"


def _root_help() -> str:
    result = CliRunner().invoke(app, ["--help"], env=HELP_ENV, prog_name=CLI)
    assert result.exit_code == 0, result.output
    return result.output


def test_readme_shows_one_example_per_gateway_group() -> None:
    shown = {path[0] for tokens in README_INVOCATIONS for path, _ in [_resolve(tokens)] if path}
    assert shown >= GATEWAY_GROUPS, f"README has no example for: {sorted(GATEWAY_GROUPS - shown)}"


def test_readme_names_the_gateway_and_the_routing_example() -> None:
    text = README.read_text(encoding="utf-8")
    assert "9router" in text
    assert "localhost:20128/v1" in text  # пример routing: один провайдер — шлюз (ADR-0001)
    assert "key_env" in text  # имя переменной с ключом шлюза
    for agent_hint in ("--help", "--json", "describe", "doctor", "коды выхода"):
        assert agent_hint in text.lower()


# --- Статьи словаря и архитектуры: только текущий замысел -------------------------

REMOVED_FROM_GLOSSARY = (
    "cache",
    "journal",
    "tags",
    "budget",
    "price",
    "transport",
    "кэш",
    "метк",
    "бюджет",
    "прайс",
    "транспорт",
    "cost_source",
    "LLMKIT_DATABASE_URL",
    "LLMKIT_CACHE",
    "llmkit_calls",
    "llmkit_cache",
    "llmkit_v1_calls",
    "cache_hit",
    "--no-cache",
)
REMOVED_FROM_ARCHITECTURE = (
    "LLMKIT_DATABASE_URL",
    "LLMKIT_CACHE",
    "llmkit_calls",
    "llmkit_cache",
    "llmkit_v1_calls",
    "cache_hit",
    "--no-cache",
    "cost_source",
    "cache.py",
    "transports/",
    "cli/serve.py",
    "cli/db.py",
    "src/llmkit/db/",
    "миграц",
    "мигрир",
    "кэш",
    "прайс",
    "транспорт",
)
CURRENT_TERMS = (
    "routing",
    "provider",
    "chain",
    "attempt",
    "task",
    "answer",
    "served model",
    "gateway",
    "readiness report",
    "OpenCLI contract",
)


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8").lower()


SORTED_DOCUMENTS = ("docs/prd.md", "docs/backlog.md")


@pytest.mark.parametrize("name", ["AGENTS.md", "README.md"])
def test_no_pointer_to_a_sorted_document(name: str) -> None:
    """Спецификация и план разобраны: указателей на них у живых документов не остаётся."""
    text = (ROOT / name).read_text(encoding="utf-8")
    for gone in SORTED_DOCUMENTS:
        assert gone not in text, f"{name} still points to `{gone}`"
