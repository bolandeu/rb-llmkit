"""Зависимости вычищены: LLM-клиент, JSON-слой, база и прокси ушли из пакета и из lock.

Сеть не нужна: `pyproject.toml` и `uv.lock` читаются разбором. Свежесть lock
(`uv lock --check`) проверяет гейт стандарта — `gate check` на этой машине.
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from llmkit._distribution import DIST_NAME

ROOT = Path(__file__).resolve().parents[1]

# Ушли вместе со своим доступом к провайдерам, своей базой, связкой ключей и `llm serve`.
REMOVED = frozenset(
    {
        "litellm",
        "instructor",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "psycopg-binary",
        "keyring",
        "fastapi",
        "uvicorn",
    }
)


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    """Имя из строки зависимости: `psycopg[binary]>=3.2; extra == 'serve'` → `psycopg`."""
    return _normalized(re.split(r"[\s<>=!~\[;]", requirement, maxsplit=1)[0])


def test_pyproject_declares_no_removed_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = {_requirement_name(requirement) for requirement in project["dependencies"]}
    assert declared & REMOVED == set()
    assert "serve" not in project.get("optional-dependencies", {})


def test_lock_holds_no_removed_package() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {_normalized(package["name"]) for package in lock["package"]}
    assert locked & REMOVED == set()


def test_installed_metadata_requires_no_removed_dependency() -> None:
    requires = metadata.requires(DIST_NAME) or []
    assert {_requirement_name(requirement) for requirement in requires} & REMOVED == set()


@pytest.mark.parametrize("package", sorted(REMOVED))
def test_removed_package_is_not_installed(package) -> None:
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.distribution(package)
