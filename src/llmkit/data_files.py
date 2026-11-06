"""Файлы llmkit в каталогах пользователя — для `llm describe --json` (x-rb-data).

Шаблон cli-generator (`core/data_files.py`); отличие — поле `dir`: файлы лежат
в каталоге данных, кэша или конфигурации пользователя. Своего состояния у llmkit
нет: ни базы, ни кэша, ни токенов подписок — в каталогах пользователя один файл
routing. Новый файл, который пишет llmkit, — новая запись здесь.
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
        "routing.json",
        "data",
        "Routing v1 по умолчанию для CLI, когда нет --routing и LLMKIT_ROUTING_FILE; права 600 (шире — предупреждение)",
        dir="config",
    ),
)
