"""Вход в подписку ChatGPT (OAuth Codex CLI): файл токенов, обновление, вход.

Порт `agent/lib/codex-auth.ts` и `scripts/lib/codex-oauth.ts` из iva-agent.
Протокол восстановлен по openai/codex, `client_id` — публичный id Codex CLI.
Файл токенов свой, не `~/.codex/auth.json`: refresh-токен одноразовый, и два
клиента на одном токене выбивали бы друг друга (`refresh_token_reused`).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import secrets
import time
import weakref
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..errors import LoginMissing
from ._common import SubscriptionAuthError

ISSUER = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = f"{ISSUER}/oauth/token"
SCOPE = "openid profile email offline_access"
ORIGINATOR = "codex_cli_rs"
# Бэкенд прячет свежие модели от старых клиентов — держать на актуальном релизе codex.
CLIENT_VERSION = "0.156.0"
REFRESH_SKEW = 300  # обновлять за 5 минут до exp, как Codex CLI
FORCE_REFRESH_COOLDOWN = 60.0
LOGIN_PORTS = (1455, 1457)  # redirect-порты, зарегистрированные за client_id Codex
LOGIN_TIMEOUT = 15 * 60

Echo = Callable[[str], None]


@dataclass
class Auth:
    """Содержимое файла токенов."""

    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    account_id: str | None = None
    plan_type: str | None = None


def default_path() -> Path:
    import platformdirs

    return Path(platformdirs.user_data_dir("llmkit")) / "chatgpt-auth.json"


def read_auth(path: Path) -> Auth | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("access_token"):
        return None
    return Auth(**{key: data.get(key) for key in Auth.__dataclass_fields__})


def write_auth(auth: Auth, path: Path) -> None:
    """Атомарно и сразу с правами 0600: секрет не мелькает с широкими правами."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(asdict(auth), handle, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def delete_auth(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


# --- JWT без проверки подписи: нужны только exp и клеймы аккаунта ---


def parse_jwt(token: str) -> dict[str, Any]:
    parts = str(token).split(".")
    if len(parts) < 2 or not parts[1]:
        raise ValueError("malformed JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))
    if not isinstance(data, dict):
        raise ValueError("JWT payload is not an object")
    return data


def jwt_exp(token: str) -> int:
    try:
        return int(parse_jwt(token).get("exp") or 0)
    except (ValueError, TypeError):
        return 0


def account_from_id_token(id_token: str | None) -> tuple[str | None, str | None]:
    """`(account_id, plan_type)` из клейма `https://api.openai.com/auth`."""
    try:
        claim = parse_jwt(id_token or "").get("https://api.openai.com/auth") or {}
    except (ValueError, TypeError):
        return None, None
    account = claim.get("chatgpt_account_id") if isinstance(claim, dict) else None
    plan = claim.get("chatgpt_plan_type") if isinstance(claim, dict) else None
    return (account or None) if isinstance(account, str) else None, (plan or None) if isinstance(plan, str) else None


def merge_tokens(tokens: dict[str, Any], prev: Auth | None = None) -> Auth:
    """Ответ токен-эндпоинта → запись файла.

    Пустые поля не стирают прежние; id_token без аккаунта не стирает
    `account_id`: без заголовка ChatGPT-Account-Id бэкенд отвечает отказом.
    """
    id_token = tokens.get("id_token") or (prev.id_token if prev else None)
    account, plan = account_from_id_token(id_token)
    return Auth(
        access_token=tokens.get("access_token") or (prev.access_token if prev else ""),
        refresh_token=tokens.get("refresh_token") or (prev.refresh_token if prev else None),
        id_token=id_token,
        account_id=account or (prev.account_id if prev else None),
        plan_type=plan or (prev.plan_type if prev else None),
    )


def is_fresh(access_token: str, now: float | None = None) -> bool:
    return jwt_exp(access_token) - REFRESH_SKEW > (time.time() if now is None else now)


def login_hint(provider: str) -> str:
    return f"выполните `llm auth login {provider}`"


# --- обновление токена ---


async def _refresh(client: Any, refresh_token: str | None) -> dict[str, Any]:
    if not refresh_token:
        raise SubscriptionAuthError("в файле входа нет refresh_token")
    response = await client.post(
        TOKEN_URL,
        json={"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    if response.status_code != 200:
        raise SubscriptionAuthError(f"обновление токена: HTTP {response.status_code} {response.text[:300]}")
    body = response.json()
    access = str(body.get("access_token") or "").strip() if isinstance(body, dict) else ""
    if not access:
        # 200 без токена — отказ, а не новый вход: иначе затрём рабочий файл.
        raise SubscriptionAuthError("обновление токена вернуло пустой access_token; прежний вход сохранён")
    return {**body, "access_token": access}


class TokenStore:
    """Свежий токен для каждого запроса; обновление одно на процесс.

    Модель зовётся конкурентно (`ask_many`), поэтому обновление под замком.
    Гонку между процессами лечит перечитывание файла при неудаче.
    """

    def __init__(self, path: Path, provider: str = "chatgpt") -> None:
        self.path = path
        self.provider = provider
        # Замок на каждый цикл событий: `ask_sync` поднимает новый цикл на вызов.
        self._locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()
        self._last_forced = float("-inf")

    @property
    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = self._locks[loop] = asyncio.Lock()
        return lock

    def _read(self) -> Auth:
        auth = read_auth(self.path)
        if auth is None:
            raise LoginMissing(self.provider, login_hint(self.provider))
        return auth

    async def access(self, client: Any) -> Auth:
        auth = self._read()
        if is_fresh(auth.access_token):
            return auth
        async with self._lock:
            auth = self._read()  # пока ждали замок, мог обновить сосед
            if is_fresh(auth.access_token):
                return auth
            return await self._refresh_locked(client, auth, must_differ=False)

    async def force_refresh(self, client: Any, rejected: str) -> Auth:
        """Бэкенд отверг токен раньше exp: одно обновление в минуту."""
        async with self._lock:
            auth = self._read()
            if auth.access_token != rejected:
                return auth
            now = time.monotonic()
            if now - self._last_forced < FORCE_REFRESH_COOLDOWN:
                raise SubscriptionAuthError(f"токен отвергнут повторно; {login_hint(self.provider)}")
            self._last_forced = now
            return await self._refresh_locked(client, auth, must_differ=True)

    async def _refresh_locked(self, client: Any, auth: Auth, *, must_differ: bool) -> Auth:
        try:
            fresh = merge_tokens(await _refresh(client, auth.refresh_token), auth)
        except SubscriptionAuthError:
            reread = read_auth(self.path)  # мог обновить другой процесс
            if (
                reread is not None
                and is_fresh(reread.access_token)
                and (not must_differ or reread.access_token != auth.access_token)
            ):
                return reread
            raise
        write_auth(fresh, self.path)
        return fresh


_stores: dict[tuple[Path, str], TokenStore] = {}


def store_for(path: Path, provider: str) -> TokenStore:
    key = (path, provider)
    if key not in _stores:
        _stores[key] = TokenStore(path, provider)
    return _stores[key]


# --- вход (синхронный: его зовёт только CLI) ---


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce() -> tuple[str, str]:
    """`(verifier, challenge)`, challenge = base64url(sha256(verifier))."""
    verifier = _b64url(secrets.token_bytes(64))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def exchange_code(client: Any, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    response = client.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        },
    )
    if response.status_code != 200:
        raise SubscriptionAuthError(f"обмен кода на токены: HTTP {response.status_code} {response.text[:300]}")
    tokens = response.json()
    if not tokens.get("access_token"):
        raise SubscriptionAuthError("обмен кода не вернул access_token")
    return tokens


def login_device(
    path: Path, *, echo: Echo, client: Any = None, sleep: Callable[[float], None] = time.sleep
) -> Auth:
    """Вход по коду устройства: ссылка + одноразовый код, работает без браузера на машине."""
    import httpx

    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        api = f"{ISSUER}/api/accounts"
        response = client.post(f"{api}/deviceauth/usercode", json={"client_id": CLIENT_ID})
        if response.status_code != 200:
            raise SubscriptionAuthError(f"запрос кода устройства: HTTP {response.status_code} {response.text[:200]}")
        device = response.json()
        echo(f"1. Откройте в браузере (на любом устройстве): {ISSUER}/codex/device")
        echo(f"2. Введите одноразовый код (живёт 15 минут): {device['user_code']}")
        echo("Жду подтверждения…")
        interval = max(float(device.get("interval") or 5), 1.0)
        deadline = time.monotonic() + LOGIN_TIMEOUT
        while time.monotonic() < deadline:
            sleep(interval)
            poll = client.post(
                f"{api}/deviceauth/token",
                json={"device_auth_id": device["device_auth_id"], "user_code": device["user_code"]},
            )
            if poll.status_code == 200:
                code = poll.json()
                tokens = exchange_code(
                    client, code["authorization_code"], code["code_verifier"], f"{ISSUER}/deviceauth/callback"
                )
                auth = merge_tokens(tokens)
                write_auth(auth, path)
                return auth
            if poll.status_code not in (403, 404):  # 403/404 — пользователь ещё не подтвердил
                raise SubscriptionAuthError(f"ожидание входа: HTTP {poll.status_code}")
        raise SubscriptionAuthError("вход не подтверждён за 15 минут")
    finally:
        if own:
            client.close()


def authorize_url(redirect_uri: str, challenge: str, state: str) -> str:
    from urllib.parse import urlencode

    return f"{ISSUER}/oauth/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": ORIGINATOR,
        }
    )


def login_browser(path: Path, *, echo: Echo, open_browser: bool = True, client: Any = None) -> Auth:
    """Вход через браузер: локальный сервер на 1455/1457 ловит redirect с кодом."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    import httpx

    verifier, challenge = pkce()
    state = _b64url(secrets.token_bytes(32))
    result: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_error(404)
                return
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            if query.get("state") != state:
                result["error"] = "state не совпал"
            elif query.get("error"):
                result["error"] = f"OAuth: {query['error']}"
            elif not query.get("code"):
                result["error"] = "нет кода авторизации"
            else:
                result["code"] = query["code"]
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            text = "Вход выполнен — вкладку можно закрыть." if ok else f"Ошибка входа: {result['error']}"
            self.wfile.write(f"<h3>{text}</h3>".encode())

        def log_message(self, *args: Any) -> None:
            pass

    server = None
    for port in LOGIN_PORTS:
        with contextlib.suppress(OSError):
            server = HTTPServer(("127.0.0.1", port), Handler)
            break
    if server is None:
        raise SubscriptionAuthError(f"порты входа {LOGIN_PORTS} заняты; попробуйте вход по коду устройства")
    redirect_uri = f"http://localhost:{server.server_port}/auth/callback"
    url = authorize_url(redirect_uri, challenge, state)
    echo(f"Откройте в браузере и войдите в OpenAI:\n{url}")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    server.timeout = 1.0
    deadline = time.monotonic() + LOGIN_TIMEOUT
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        raise SubscriptionAuthError(result.get("error") or "вход не выполнен за 15 минут")
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        auth = merge_tokens(exchange_code(client, result["code"], verifier, redirect_uri))
    finally:
        if own:
            client.close()
    write_auth(auth, path)
    return auth
