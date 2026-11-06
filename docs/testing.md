# Тесты llmkit

Тесты сети не касаются: сеть подменяется транспортом `httpx` — `FakeGateway`
в `tests/conftest.py` отдаёт заготовленный ответ шлюза
(`LlmKit(transport=...)`, `runtime.build_kit`).
Каталоги пользователя во время теста — во временных, фикстура `isolated` в
`tests/conftest.py`; журнал расходов тесты строят в своём временном SQLite.
