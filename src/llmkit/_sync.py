"""Запуск корутины из синхронного кода.

Если в этом потоке уже крутится event loop (Jupyter, обработчик внутри
асинхронного кода), `asyncio.run` бросает RuntimeError — тогда корутина
выполняется в отдельном потоке со своим loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
