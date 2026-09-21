"""Резолв ключей: аргумент конфига → env → связка ключей."""

from __future__ import annotations

import json
import logging

import pytest

from llmkit import keys
from llmkit.config import ProviderConfig
from llmkit.errors import KeyMissing


class FakeKeyring:
    """Подмена модуля keyring: хранит значения в словаре."""

    class errors:  # имя повторяет модуль keyring.errors
        class KeyringError(Exception): ...

        class PasswordDeleteError(KeyringError): ...

    def __init__(self, values=None, *, broken=False) -> None:
        self.values = values or {}
        self.broken = broken

    def get_password(self, service, user):
        if self.broken:
            raise self.errors.KeyringError("связки нет")
        return self.values.get((service, user))

    def set_password(self, service, user, value):
        self.values[(service, user)] = value

    def delete_password(self, service, user):
        if (service, user) not in self.values:
            raise self.errors.PasswordDeleteError("нет такого")
        del self.values[(service, user)]


@pytest.fixture
def fake_keyring(monkeypatch):
    def install(values=None, *, broken=False):
        fake = FakeKeyring(values, broken=broken)
        monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
        monkeypatch.setitem(__import__("sys").modules, "keyring.errors", fake.errors)
        keys._store_warned = False
        return fake

    return install


def test_env_wins_over_keychain(fake_keyring):
    fake_keyring({("llmkit:openrouter", "openrouter"): json.dumps({"api_key": "из-связки"})})
    cfg = ProviderConfig(kind="openrouter")
    assert keys.resolve("openrouter", cfg, env={"OPENROUTER_API_KEY": "из-env"}) == "из-env"


def test_keychain_used_when_env_empty(fake_keyring):
    fake_keyring({("llmkit:openrouter", "openrouter"): json.dumps({"api_key": "из-связки"})})
    assert keys.resolve("openrouter", ProviderConfig(kind="openrouter"), env={}) == "из-связки"


def test_config_api_key_wins_over_everything(fake_keyring):
    fake_keyring()
    cfg = ProviderConfig(kind="openrouter", api_key="из-конфига")
    assert keys.resolve("openrouter", cfg, env={"OPENROUTER_API_KEY": "из-env"}) == "из-конфига"


def test_api_key_env_overrides_standard_name(fake_keyring):
    fake_keyring()
    cfg = ProviderConfig(kind="openai_compatible", base_url="http://x/v1", api_key_env="DEEPSEEK_API_KEY")
    assert keys.resolve("deepseek", cfg, env={"DEEPSEEK_API_KEY": "ключ"}) == "ключ"


def test_broken_keychain_warns_once_and_falls_back_to_env(fake_keyring, caplog):
    fake_keyring(broken=True)
    cfg = ProviderConfig(kind="openrouter")
    with caplog.at_level(logging.WARNING, logger="llmkit.keys"):
        assert keys.resolve("openrouter", cfg, env={"OPENROUTER_API_KEY": "из-env"}) == "из-env"
        assert keys.from_keychain("openrouter") is None
        assert keys.from_keychain("openrouter") is None
    assert len([r for r in caplog.records if "связка" in r.getMessage()]) == 1


def test_missing_key_raises_with_hint(fake_keyring):
    fake_keyring()
    with pytest.raises(KeyMissing) as info:
        keys.resolve("openrouter", ProviderConfig(kind="openrouter"), env={})
    assert "OPENROUTER_API_KEY" in str(info.value) and "llm keys set openrouter" in str(info.value)


def test_provider_without_key_returns_none(fake_keyring):
    fake_keyring()
    cfg = ProviderConfig(kind="ollama", base_url="http://localhost:11434", requires_key=False)
    assert keys.resolve("ollama", cfg, env={}) is None


def test_store_and_delete_roundtrip(fake_keyring):
    fake = fake_keyring()
    keys.store("openrouter", "секрет")
    assert json.loads(fake.values[("llmkit:openrouter", "openrouter")]) == {"api_key": "секрет"}
    keys.delete("openrouter")
    keys.delete("openrouter")  # повторное удаление — не ошибка
    assert fake.values == {}
