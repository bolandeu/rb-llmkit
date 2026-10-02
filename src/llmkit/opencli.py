"""`llm describe --json`: CLI как документ OpenCLI (https://opencli.org, спецификация 0.1).

Перенесено вручную из шаблона cli-generator v1.5.5 (`core/opencli.py`; отличия —
в AGENTS.md). Машиночитаемый контракт инструмента для архитектора, Windmill и
каталога tools. Команды, опции и аргументы берутся из дерева Click, которое
строит Typer, — ничего не пишется дважды. Читается по утиной типизации
(`param_type_name`, `commands`): свежий Typer несёт свою копию Click, и
`isinstance` против пакета `click` ничего бы не нашёл. Типа и значения по
умолчанию у параметра, как и метаданных документа, в OpenCLI нет — наше идёт
в `metadata` с именами `x-rb-*`: у опций и аргументов `x-rb-type`,
`x-rb-default`, `x-rb-multiple`; у корневой команды — env, данные, внешние
программы и версия шаблона.

Вывод — контракт между инструментами, как `auth status`: tests/test_describe.py
сверяет его со схемой OpenCLI и снимком. Изменить или убрать в нём что-либо —
ломающее изменение.
"""

from __future__ import annotations

import enum
import inspect
import json
import tomllib
from dataclasses import asdict
from importlib import resources
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PurePath
from typing import Any

from ._distribution import DIST_NAME, TEMPLATE_VERSION, TOOL
from .errors import EXIT_CODES
from .version import installed_version

OPENCLI_VERSION = "0.1"
CLI_NAME = "llm"
_PACKAGE_NAME = __name__.split(".")[0]


def document(root: Any) -> dict:
    """Документ OpenCLI для CLI с корневой командой `root`."""
    command = _command(CLI_NAME, root)
    command["exitCodes"] = [{"code": code, "description": meaning} for code, meaning in EXIT_CODES.items()]
    command["metadata"] = _meta(
        {
            # Пространство имён в общей базе, имя для `uv tool install`, импорт-пакет.
            "x-rb-tool": {"tool": TOOL, "dist": DIST_NAME, "package": _PACKAGE_NAME},
            "x-rb-template-version": TEMPLATE_VERSION,
            "x-rb-env": env_vars(),
            "x-rb-data": data(),
            "x-rb-external": external(),
        }
    )
    info = {"title": CLI_NAME, "version": installed_version() or "0.0.0+source"}
    if summary := _summary():
        info["summary"] = summary
    return {"opencli": OPENCLI_VERSION, "info": info, "command": command}


def _command(name: str, cmd: Any) -> dict:
    out: dict[str, Any] = {"name": name}
    if description := _text(cmd.help):
        out["description"] = description
    if cmd.hidden:
        out["hidden"] = True
    options = [_option(p) for p in cmd.params if p.param_type_name == "option"]
    arguments = [_argument(p) for p in cmd.params if p.param_type_name == "argument"]
    if options:
        out["options"] = options
    if arguments:
        out["arguments"] = arguments
    if (subcommands := getattr(cmd, "commands", None)) is not None:  # группа
        # Порядок регистрации (Typer его хранит) — тот, что показывает `--help`.
        out["commands"] = [_command(sub_name, sub) for sub_name, sub in subcommands.items()]
    return out


def _option(param: Any) -> dict:
    names = sorted(param.opts, key=len, reverse=True)  # имя — длинная форма
    out: dict[str, Any] = {"name": names[0]}
    if aliases := [*names[1:], *param.secondary_opts]:
        out["aliases"] = aliases
    if param.required:
        out["required"] = True
    if not param.is_flag and not param.count:
        value = {"name": param.metavar or (param.name or "value").upper(), "required": True}
        if choices := _choices(param.type):
            value["acceptedValues"] = choices
        out["arguments"] = [value]
    if description := _text(param.help):
        out["description"] = description
    if param.hidden:
        out["hidden"] = True
    out["metadata"] = _param_meta(param, multiple=param.multiple)
    return out


def _argument(param: Any) -> dict:
    out: dict[str, Any] = {"name": param.name or "argument"}
    out["required"] = param.required
    maximum = None if param.nargs == -1 else param.nargs
    out["arity"] = {"minimum": param.nargs if param.required and param.nargs > 0 else int(param.required)}
    if maximum is not None:
        out["arity"]["maximum"] = maximum
    if choices := _choices(param.type):
        out["acceptedValues"] = choices
    if description := _text(getattr(param, "help", None)):  # у аргументов Typer есть help
        out["description"] = description
    if getattr(param, "hidden", False):
        out["hidden"] = True
    out["metadata"] = _param_meta(param, multiple=param.nargs == -1)
    return out


def _param_meta(param: Any, *, multiple: bool) -> list[dict]:
    meta: dict[str, Any] = {"x-rb-type": param.type.name}
    default = param.default
    if default is not None and not callable(default) and default != ():
        meta["x-rb-default"] = _jsonable(default)
    if multiple:
        meta["x-rb-multiple"] = True
    return _meta(meta)


def _choices(param_type: Any) -> list[str] | None:
    choices = getattr(param_type, "choices", None)  # Choice (или Enum, который Typer в него превратил)
    return [str(_jsonable(choice)) for choice in choices] if choices else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _text(text: str | None) -> str:
    # Typer-разметка экранирует `[`; документу нужен сам докстринг.
    return inspect.cleandoc(text or "").replace("\\[", "[").strip()


def _meta(values: dict[str, Any]) -> list[dict]:
    return [{"name": name, "value": value} for name, value in values.items() if value is not None]


def _summary() -> str:
    try:
        return distribution(DIST_NAME).metadata["Summary"] or ""
    except PackageNotFoundError:
        return ""


def env_vars() -> list[dict]:
    """Все env, которые читает llmkit: ключи встроенных провайдеров, конфиг, база, внешний CLI."""
    from . import config, db, keys
    from .providers import SUBSCRIPTION_KINDS

    found: list[dict] = []
    # Встроенные провайдеры (config.DEFAULTS), не конфиг пользователя: документ не зависит от машины.
    # Провайдер из своего конфига читает `api_key_env` или <ПРОВАЙДЕР>_API_KEY.
    defaults = config.Config.model_validate(config.DEFAULTS)
    for name, cfg in defaults.providers.items():
        if cfg.kind in SUBSCRIPTION_KINDS or not cfg.requires_key:
            continue
        found.append(
            {
                "name": keys.env_var(name, cfg),
                "purpose": "credential",
                "provider": name,
                "field": "api_key",
                "required": False,  # нужен, только если цепочка идёт через этого провайдера
            }
        )
    found += [
        {
            "name": "LLMKIT_CONFIG",
            "purpose": "config",
            "description": "Файл конфига вместо поиска ~/.config/llmkit и .llmkit/ проекта",
            "required": False,
        },
        {
            "name": "LLMKIT_CACHE",
            "purpose": "config",
            "description": "0/false/no — выключить кэш ответов",
            "required": False,
        },
        {"name": "LLMKIT_LOG_LEVEL", "purpose": "config", "description": "Уровень логов библиотеки", "required": False},
    ]
    found += [
        {"name": name, "purpose": "database", "description": description, "required": False}
        for name, description in db.ENV_VARS.items()
    ]
    found.append(
        {
            "name": "CLAUDE_COMMAND",
            "purpose": "external",
            "description": "Команда CLI Claude (можно с аргументами) вместо `claude` из PATH",
            "required": False,
        }
    )
    return found


def data() -> dict:
    """Таблицы, представления `llmkit_v1_*` и файлы в каталогах пользователя."""
    from .data_files import DATA_FILES
    from .db import tables

    def files(where: str) -> list[dict]:
        return [
            {key: value for key, value in asdict(entry).items() if key != "dir"}
            for entry in DATA_FILES
            if entry.dir == where
        ]

    return {
        "tables": [
            {
                "name": table.name,
                "kind": table.info.get("kind"),
                **({"description": table.comment} if table.comment else {}),
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": bool(column.nullable),
                        **({"primary_key": True} if column.primary_key else {}),
                    }
                    for column in table.columns
                ],
            }
            for table in tables.metadata.tables.values()
        ],
        "views": [
            {
                "name": view.name,
                **({"description": view.comment} if view.comment else {}),
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        **({"description": column.comment} if column.comment else {}),
                    }
                    for column in view.columns
                ],
            }
            for view in tables.views.tables.values()
        ],
        "user_data_dir": {"appname": TOOL, "files": files("data")},
        # Каталога кэша в шаблоне нет: у llmkit там кэш ответов моделей.
        "user_cache_dir": {"appname": TOOL, "files": files("cache")},
    }


def external() -> list[dict]:
    """Внешние программы из `[[tool.rb.external]]` pyproject.toml (стандарт §12)."""
    text = _pyproject_text()
    entries = tomllib.loads(text).get("tool", {}).get("rb", {}).get("external", []) if text else []
    return [
        {
            "name": entry["name"],
            "required": bool(entry.get("required", True)),
            "why": entry.get("why", ""),
            "min_version": entry.get("min_version"),
            "check": entry.get("check"),
            "detect": bool(entry.get("detect", True)),
            "dist": entry.get("dist"),
            "url": entry.get("url"),
        }
        for entry in entries
    ]


def _pyproject_text() -> str | None:
    # Колесо несёт pyproject.toml как llmkit/_pyproject.toml (hatch force-include);
    # editable-установка читает свой из рабочей копии.
    bundled = resources.files(_PACKAGE_NAME).joinpath("_pyproject.toml")
    if bundled.is_file():
        return bundled.read_text()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            text = candidate.read_text()
            if tomllib.loads(text).get("project", {}).get("name") == DIST_NAME:
                return text
    return None
