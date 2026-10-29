"""Файлы llmkit в каталогах пользователя — для `llm describe --json` (x-rb-data).

Шаблон cli-generator v1.5.6 (`core/data_files.py`); отличие — поле `dir`: файлы
лежат в каталоге данных, кэша или конфигурации пользователя. Кэш ответов — таблица
`llmkit_cache` в базе, не файл. Пути — по умолчанию, настройка
`LlmKit(config=...)` (`usage.path`) может их перенести. Новый файл, который пишет
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
    dir: Literal["data", "cache", "config"] = "data"  # user_data_dir, user_cache_dir или user_config_dir


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
        "routing.json",
        "data",
        "Routing v1 по умолчанию для CLI, когда нет --routing и LLMKIT_ROUTING_FILE; права 600 (шире — предупреждение)",
        dir="config",
    ),
)
