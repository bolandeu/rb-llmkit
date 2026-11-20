"""Клиент шлюза 9router: один вызов — один POST на `/chat/completions`."""

from __future__ import annotations

from rb_llmkit.gateway.client import GatewayClient, probe
from rb_llmkit.gateway.parse import Reply

__all__ = ["GatewayClient", "Reply", "probe"]
