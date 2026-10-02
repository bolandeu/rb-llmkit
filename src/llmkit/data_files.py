"""Файлы llmkit в каталогах пользователя — для `llm describe --json` (x-rb-data).

Шаблон cli-generator v1.5.0 (`core/data_files.py`); отличие — поле `dir`: кэш
ответов у llmkit лежит не в каталоге данных, а в каталоге кэша
(`platformdirs.user_cache_dir("llmkit")`). Пути — по умолчанию, конфиг
(`cache.path`, `usage.path`) может их перенести. Новый файл, который пишет
llmkit, — новая запись здесь.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DataFile:
    path: str  # относительно каталога; для семейства файлов — glob ("exports/*.csv")
    kind: str  # "data": при удалении теряется | "cache": получается заново по запросу
    description: str
    dir: Literal["data", "cache"] = "data"  # user_data_dir или user_cache_dir


DATA_FILES: tuple[DataFile, ...] = (
    DataFile(
        "usage.sqlite",
        "data",
        "Локальная SQLite журнала расходов (llmkit_calls), когда LLMKIT_DATABASE_URL не задан; usage.path",
    ),
    DataFile(
        "chatgpt-auth.json",
        "data",
        "Токены входа в подписку ChatGPT (`llm auth login chatgpt`); без него — вход заново",
    ),
    DataFile(
        "cache.sqlite",
        "cache",
        "Кэш ответов моделей: повторный запрос с теми же параметрами не идёт к провайдеру; cache.path",
        dir="cache",
    ),
)
