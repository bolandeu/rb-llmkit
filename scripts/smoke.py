"""Фаза 0: три реальных вызова через LiteLLM — проверка, что связка работает.

Ключи берутся из связки ключей macOS проекта intentree (llmkit свои ключи
ещё не хранит). Промпты короткие, ответ ограничен 20 токенами, чтобы прогон
стоил копейки. Ключи никуда не печатаются.

Запуск: uv run python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import json
import logging

import keyring
import litellm
from pydantic import BaseModel

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

PROMPT = "Reply with exactly one word: pong"


def secret(service: str, user: str) -> str:
    raw = keyring.get_password(service, user)
    if not raw:
        raise SystemExit(f"нет ключа в связке: {service}")
    return json.loads(raw)["api_key"]


class Ping(BaseModel):
    word: str
    length: int


def report(title: str, response: object) -> None:
    usage = getattr(response, "usage", None)
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception as exc:  # цена может быть неизвестна LiteLLM
        cost = None
        print(f"[{title}] цена неизвестна: {type(exc).__name__}: {exc}")
    print(f"[{title}] model={getattr(response, 'model', '?')}")
    print(f"[{title}] usage={usage}")
    print(f"[{title}] cost_usd={cost}")


async def openrouter_text(api_key: str) -> None:
    response = await litellm.acompletion(
        model="openrouter/openai/gpt-4o-mini",
        messages=[{"role": "user", "content": PROMPT}],
        api_key=api_key,
        temperature=0.0,
        max_tokens=20,
    )
    print(f"[openrouter-text] answer={response.choices[0].message.content!r}")
    report("openrouter-text", response)


async def openrouter_json(api_key: str) -> None:
    import instructor

    client = instructor.from_litellm(litellm.acompletion, mode=instructor.Mode.TOOLS)
    obj, response = await client.chat.completions.create_with_completion(
        model="openrouter/openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "The word is 'pong'. Fill the schema."}],
        response_model=Ping,
        api_key=api_key,
        temperature=0.0,
        max_tokens=20,
    )
    print(f"[openrouter-json] answer={obj!r}")
    report("openrouter-json", response)


async def ollama_text(api_key: str) -> str:
    """Пробуем ollama_chat/ на ollama.com, при неудаче — openai/ + /v1.

    gpt-oss:120b — reasoning-модель: при max_tokens=20 весь бюджет уходит
    в рассуждение и content приходит пустым, поэтому лимит здесь выше.
    """
    try:
        response = await litellm.acompletion(
            model="ollama_chat/gpt-oss:120b",
            messages=[{"role": "user", "content": PROMPT}],
            api_base="https://ollama.com",
            api_key=api_key,
            temperature=0.0,
            max_tokens=200,
        )
    except Exception as exc:
        print(f"[ollama] ollama_chat/ не сработал: {type(exc).__name__}: {str(exc)[:300]}")
        response = await litellm.acompletion(
            model="openai/gpt-oss:120b",
            messages=[{"role": "user", "content": PROMPT}],
            api_base="https://ollama.com/v1",
            api_key=api_key,
            temperature=0.0,
            max_tokens=200,
        )
        path = "openai/ + https://ollama.com/v1"
    else:
        path = "ollama_chat/ + https://ollama.com"
    print(f"[ollama] рабочий путь: {path}")
    print(f"[ollama] answer={response.choices[0].message.content!r}")
    report("ollama", response)
    return path


async def main() -> None:
    openrouter_key = secret("intentree:openrouter", "openrouter")
    ollama_key = secret("intentree:ollama", "ollama")
    await openrouter_text(openrouter_key)
    await openrouter_json(openrouter_key)
    path = await ollama_text(ollama_key)
    print(f"\nИТОГ: рабочий путь Ollama Cloud — {path}")


if __name__ == "__main__":
    asyncio.run(main())
