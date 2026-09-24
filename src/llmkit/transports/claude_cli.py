"""Модели подписки Claude через установленный Claude Code CLI.

Порт `agent/lib/claude-cli.ts` из iva-agent в минимальном виде: один вызов
`claude -p` на один ответ, без инструментов, сессий и чужих настроек.
Токен подписки держит CLI (`claude auth login` или `CLAUDE_CODE_OAUTH_TOKEN`),
llmkit его не читает. Температуру CLI не принимает — она игнорируется.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Any

from ._common import (
    SubscriptionAuthError,
    SubscriptionEmpty,
    SubscriptionTimeout,
    error_from_text,
    model_response,
    strip_fences,
    text_of,
)

DEFAULT_SYSTEM = "You are a helpful assistant."
JSON_OBJECT_HINT = "Answer with a single JSON object only, without any prose or code fences."

# С этими переменными CLI ушёл бы мимо подписки: на платный ключ или чужой адрес.
AUTH_CONFLICTS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_BASE_URL")
BACKEND_PREFIX = "CLAUDE_CODE_USE_"
# Лишний трафик выключен; повторы делает цепочка llmkit, не CLI.
CLAUDE_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_MAX_RETRIES": "0",
    "DISABLE_AUTO_COMPACT": "1",
}


def command(env: dict[str, str] | None = None) -> list[str] | None:
    """Команда CLI: `CLAUDE_COMMAND` (можно с аргументами) или `claude` из PATH."""
    env = os.environ if env is None else env
    raw = env.get("CLAUDE_COMMAND", "").strip()
    if raw:
        parts = shlex.split(raw)
        found = shutil.which(parts[0], path=env.get("PATH"))
        return [found, *parts[1:]] if found else None
    found = shutil.which("claude", path=env.get("PATH"))
    return [found] if found else None


def child_env(source: dict[str, str], max_tokens: int | None = None) -> dict[str, str]:
    """Окружение CLI: без ключей API и сторонних бэкендов, с нашими флагами."""
    env = {
        key: value
        for key, value in source.items()
        if key not in AUTH_CONFLICTS and not key.startswith(BACKEND_PREFIX) and key != "CLAUDE_CODE_EXTRA_BODY"
    }
    env.update(CLAUDE_ENV)
    if max_tokens:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_tokens)
    return env


def render_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Сообщения → (системный промпт, текст для stdin).

    CLI в режиме `-p` принимает одну реплику; история превращается в
    размеченную стенограмму перед последним сообщением пользователя.
    """
    system = [text_of(m.get("content")) for m in messages if m.get("role") in ("system", "developer")]
    turns = [m for m in messages if m.get("role") not in ("system", "developer")]
    if not turns:
        return "\n\n".join(system), ""
    last = text_of(turns[-1].get("content"))
    history = turns[:-1]
    if not history:
        return "\n\n".join(system), last
    lines = ["<conversation_history>"]
    for message in history:
        role = "Assistant" if message.get("role") == "assistant" else "User"
        lines.append(f"{role}: {text_of(message.get('content'))}")
    lines.append("</conversation_history>")
    return "\n\n".join(system), "\n".join(lines) + "\n\n" + last


def build_argv(cmd: list[str], model: str, system_file: Path, schema: dict[str, Any] | None) -> list[str]:
    argv = [
        *cmd,
        "-p",
        "--model", model,
        "--output-format", "json",
        # Свои инструменты CLI выключены: нужен ответ модели, а не агент.
        "--tools", "",
        "--system-prompt-file", str(system_file),
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        # Ответ по --json-schema CLI отдаёт через внутренний инструмент — это ещё ход.
        "--max-turns", "1" if schema is None else "3",
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
    ]  # fmt: skip
    if schema is not None:
        argv += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    return argv


def parse_result(stdout: str) -> dict[str, Any] | None:
    """Итоговый объект `type: result` из вывода `--output-format json`."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, list):
        results = [item for item in data if isinstance(item, dict) and item.get("type") == "result"]
        return results[-1] if results else None
    return data if isinstance(data, dict) else None


def _kill(process: asyncio.subprocess.Process) -> None:
    """CLI живёт в своей группе процессов: убиваем её целиком, с детьми."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


async def acompletion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
    **_ignored: Any,
) -> Any:
    """Вызов модели через `claude -p`; сигнатура как у `litellm.acompletion`."""
    cmd = command()
    if cmd is None:
        raise SubscriptionAuthError("Claude Code CLI не найден: установите его и выполните `claude auth login`")
    system, prompt = render_prompt(messages)
    schema = None
    if response_format and response_format.get("type") == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema") or {}
    elif response_format and response_format.get("type") == "json_object":
        system = f"{system}\n\n{JSON_OBJECT_HINT}".strip()

    # Пустой каталог как cwd: CLI не подхватит CLAUDE.md и настройки проекта.
    with tempfile.TemporaryDirectory(prefix="llmkit-claude-") as workdir:
        system_file = Path(workdir) / "system.md"
        system_file.write_text(system or DEFAULT_SYSTEM, "utf-8")
        process = await asyncio.create_subprocess_exec(
            *build_argv(cmd, model, system_file, schema),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env=child_env(dict(os.environ), max_tokens),
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode("utf-8")), timeout)
        except TimeoutError:
            _kill(process)
            await process.wait()
            raise SubscriptionTimeout(f"Claude CLI не ответил за {timeout} с") from None
        except asyncio.CancelledError:
            _kill(process)  # отмена задачи не оставляет висящий CLI
            raise

    result = parse_result(stdout.decode("utf-8", "replace"))
    if result is None:
        text = stderr.decode("utf-8", "replace").strip() or stdout.decode("utf-8", "replace").strip()
        raise error_from_text(f"Claude CLI (код {process.returncode}): {text[:500]}")
    if result.get("is_error") or result.get("subtype") not in (None, "success"):
        status = result.get("api_error_status")
        detail = str(result.get("result") or result.get("subtype") or "ошибка без текста")
        raise error_from_text(f"{status} {detail}" if status else detail)

    if schema is not None and result.get("structured_output") is not None:
        content = json.dumps(result["structured_output"], ensure_ascii=False)
    else:
        content = str(result.get("result") or "")
        if response_format:
            content = strip_fences(content)
    if not content.strip():
        raise SubscriptionEmpty("Claude CLI вернул пустой ответ")
    usage = result.get("usage") or {}
    prompt_tokens = sum(
        int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    finish = "length" if result.get("stop_reason") == "max_tokens" else "stop"
    return model_response(model, content, prompt_tokens, int(usage.get("output_tokens") or 0), finish)


async def auth_status() -> dict[str, Any]:
    """`claude auth status` → словарь; CLI без входа или без бинаря — пометка в ответе."""
    cmd = command()
    if cmd is None:
        return {"installed": False, "loggedIn": False}
    process = await asyncio.create_subprocess_exec(
        *cmd, "auth", "status",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env(dict(os.environ)),
    )  # fmt: skip
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 20)
    except TimeoutError:
        process.kill()
        return {"installed": True, "loggedIn": False, "error": "claude auth status не ответил за 20 с"}
    try:
        data = json.loads(stdout.decode("utf-8", "replace"))
    except ValueError:
        data = {}
    return {"installed": True, **(data if isinstance(data, dict) else {}), "loggedIn": bool(data.get("loggedIn"))}
