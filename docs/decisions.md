# Кто что решает

Карта: каждое решение llmkit — одной строкой, с тем, кто его принимает, и с единственным местом, где оно задано.
Сама причина решения — ADR ([adr/](adr/README.md)) или абзац в живом документе; поведение — код и тесты;
значения — `pyproject.toml` и `.agents/antagor/antagor.toml`.

Кто: **Код** — детерминированно, без суждения; **Настройка** — Архитектор проекта в `antagor.toml`
(защищённые — Человек, паролем); **Архитектор**, **Человек**, **Исполнитель**, **Ревьюер** — суждение.

## Продукт

| Решение | Кто | Где |
|---|---|---|
| Что llmkit делает и чего не делает; какие инструменты он обслуживает | Человек, Архитектор | `README.md`, `CONTEXT.md`, идеи |
| Взять готовую библиотеку вместо своего кода | Архитектор, Человек | ADR-0004, `pyproject.toml` |
| Отвергнутая альтернатива, которую нельзя отменить молча | Архитектор, Человек | `docs/adr/NNNN-slug.md` |

## Публичный контракт

| Решение | Кто | Где |
|---|---|---|
| Python API (`LlmKit.ask/generate/ask_many`, `Task`, `Answer`) | Архитектор | `src/llmkit/core.py`, `src/llmkit/models.py` |
| Команды CLI, флаги, `--json`, коды выхода | Архитектор | `src/llmkit/cli/`, `src/llmkit/errors.py` (EXIT_CODES), снимки `tests/snapshots/` |
| Форма `llm describe --json` (OpenCLI), `x-rb-data`, `x-rb-env` | Архитектор | `src/llmkit/opencli.py`, `tests/snapshots/describe.json` |
| Контракты потребителей (`--json`, коды выхода) | Потребитель | `tests/contracts/<потребитель>/llmkit.yaml` (копия из репо потребителя) |
| Формат routing v1 — публичная схема в колесе | Архитектор | `src/llmkit/contracts/routing-v1.schema.json` (ADR-0002) |

## Доступ к моделям и состояние

| Решение | Кто | Где |
|---|---|---|
| Шлюз 9router — единственный доступ к модели: провайдеры, подписки, квоты, форматы | Человек | ADR-0001 §«Границы» |
| **Своего состояния нет**: ни своей базы, ни журнала расходов, ни хранения ответов, ни справочника цен, ни `LLMKIT_DATABASE_URL`, ни команд вида `llm db *` | Человек | ADR-0001 §«Своей базы данных нет», `docs/architecture.md` |
| Расход и его группировка — из журнала шлюза (`usageHistory`), read-only; потребитель — по своему API-ключу шлюза | Код | ADR-0001 §«Журнал расходов — у шлюза», `docs/architecture.md` §Журнал |
| Учёт токенов, статус строки и цена запроса | Шлюз 9router | журнал шлюза `usageHistory` |
| Ключ шлюза — переменная окружения, имя берётся из routing (`key_env`) | Код | ADR-0001, `src/llmkit/keys.py` |

## Вызов модели

| Решение | Кто | Где |
|---|---|---|
| Провайдер, цепочка и адрес шлюза — данные, не код | Архитектор | ADR-0002, `src/llmkit/routing.py` |
| Модель называется строкой как в настройке шлюза; имя не разбирается на провайдера и модель | Архитектор | ADR-0001 §«Названия моделей» |
| Классификация ошибки и код выхода | Код | `src/llmkit/errors.py`, `src/llmkit/cli/output.py` |
| Цена — из ответа шлюза (`usage.cost`), `served_model` и `provider` — оттуда же | Код | ADR-0001 §«Цена — из ответа шлюза», `docs/architecture.md` |
| Все эндпоинты шлюза обёрнуты по одному на семейство: чат, картинки, речь, видео, эмбеддинги, поиск, страница, модели | Архитектор | ADR-0001 §«Вся поверхность шлюза, включая медиа», `docs/architecture.md` |
| Своя цепочка ретраев, клиенты подписок, `llm serve` — не пишем, это у шлюза | Архитектор | ADR-0001 §«Отвергнуто» |

## Документы

| Решение | Кто | Где |
|---|---|---|
| Вид каждого `.md`: живой, сгенерированный, датированная запись, данные | Архитектор | `[docs]` в `.agents/antagor/antagor.toml`, `docs/adr/`, `docs/research/` |
| Живые документы — `docs/architecture.md`, `docs/cli-conventions.md`, `docs/testing.md`, `docs/decisions.md`; корневые — `README.md`, `CONTEXT.md`, `AGENTS.md`, `CODING_STANDARDS.md` | Архитектор | `[docs] living` в `.agents/antagor/antagor.toml` |
| Решение, которое трудно отменить, — ADR с датой; проверенное исследование — запись в `docs/research/` | Архитектор | `docs/adr/README.md`, скилл `antagor-method` |
| План, замысел и отложенное — идея или задача, не файл | Архитектор | `antagor idea add`, `.agents/antagor/` |
| Сделанное — `CHANGELOG.md` | Код | `antagor publish` |

## Работа в проекте

| Решение | Кто | Где |
|---|---|---|
| Форма для агентов: у каждой команды и параметра `--help` со строкой `Example:`, `--json` у всех команд, `llm doctor --json` | Архитектор | ADR-0001, `tests/snapshots/help/` |
| Режим проекта, что Архитектору можно без пароля | Человек | `mode` в `.agents/antagor/antagor.toml` |
| Проверки задачи (pytest, ruff, ty, докстринги), протокол red → green, параллельность | Архитектор | `.agents/antagor/antagor.toml`: `checks`, `[protocol]`, `parallel` |
| Гейт выпуска и деплой (`rb-release check`, `git push --follow-tags`) | Архитектор | `.agents/antagor/antagor.toml`: `[publish]`; `.gitea/workflows/ci.yml` |
| Версия и changelog — только из тега и `antagor publish` | Код | `antagor publish`, `CHANGELOG.md` |
| TDD: тест раньше кода; чужой тест меняется только при смене требования | Человек, Исполнитель, Ревьюер | `AGENTS.md`, отчёт гейта `existing tests` |
| Границы задачи, нарезка, приёмка | Архитектор | `.agents/antagor/`, скилл `antagor-slice` |
| Ревью `feature`/`bugfix` другим моделью (`pi-glm`) | Код, Настройка | `[review]` в `.agents/antagor/antagor.toml` |
