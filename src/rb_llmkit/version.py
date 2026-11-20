"""Версия установленного пакета: по DIST_NAME, иначе по DIST_NAME_LEGACY (переименование в процессе)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution

from ._distribution import DIST_NAME, DIST_NAME_LEGACY


def installed_version() -> str | None:
    """Версия пакета или None, если исходники запущены вообще без установки (даже без `uv sync`)."""
    for name in (DIST_NAME, DIST_NAME_LEGACY):
        if name:
            try:
                return distribution(name).version
            except PackageNotFoundError:
                continue
    return None
