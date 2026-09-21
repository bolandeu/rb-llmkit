# Фаза 3 — перевод antagor на llmkit

Задание для новой сессии (`/senior-fable`, одному implementer-у). Исследование уже
сделано, ниже — факты и план; код antagor заново не изучать целиком.

## Факты (2026-09-21)

- antagor: `/Users/bolandau/Projects/antagor`, не uv-проект — `requirements.txt` + `.venv`
  (Python 3.14). Ключи и провайдеры из `data/.env`: `LLM_PROVIDER` (дефолт `ollama`),
  `LLM_PROVIDER_FALLBACK` (дефолт `openrouter`), `OLLAMA_API_KEY`, `OPENROUTER_API_KEY`.
  Имена env совпадают со стандартными именами llmkit — ключи из `.env` продолжат работать,
  плюс связка `llmkit:*`.
- Клиент: `utils/llm.py` (648 строк, httpx + ollama SDK). Публичный API, на который завязаны
  38 файлов (`commands/*.py`, `utils/*.py`):
  - `LLMConfig(api_key, model, provider, timeout=120, max_tokens, temperature=0.7,
    retry_limit, fallback_provider, use_fallback=True)`;
  - `async with LLMClient(config) as client:`; `client.chat(messages, model, max_tokens,
    temperature) -> str | None`; `client.generate(prompt, system_prompt, model, max_tokens,
    temperature) -> str | None` — ошибки не бросает, возвращает `None`;
  - `generate_json(client, prompt, model, label, retries=2, system_prompt, validate) -> Any | None`
    (strip_code_fence + json.loads + свой `validate`, ретраи на «не по формату»);
  - `generate_with_llm(content, prompt_template, model, api_key, timeout)`;
  - `resolve_model(model, provider)` — алиасы уровней (`MODEL_ALIASES`) → тег модели у
    провайдера; `strip_code_fence`; `DEFAULT_MODEL`, `DEFAULT_PROVIDER` используются как
    дефолты typer-опций;
  - `client.embed(texts, model)` — 4 вызова (`utils/context_ingest.py`, `utils/intent_candidates.py`,
    `commands/raw_embed.py`, `commands/text_analyze_url.py`); `client.generate_image(prompt, model)` —
    1 вызов (`commands/featured_image.py`). **Embeddings и картинки вне llmkit v1** (ROADMAP).

## План

1. **Зависимость**: `llmkit @ git+https://github.com/bolandeu/llmkit` в `requirements.txt`,
   установить в `.venv` (`uv pip install -r requirements.txt` или как принято в antagor).
   Для локальной разработки — `uv pip install -e ../tools/llmkit`.
2. **Шим вместо переписывания 38 файлов**: `utils/llm.py` остаётся фасадом с теми же именами
   и сигнатурами, внутри — `llmkit.LlmKit`:
   - `LLMConfig` сохраняется как есть (dataclass-подобный), но из него строится цепочка
     `[f"{provider}/{resolve_model(model, provider)}", f"{fallback}/{resolve_model(model, fallback)}"]`
     (второй элемент только при `use_fallback` и заданном фолбэке). `retry_limit` → игнорировать
     (политика ретраев теперь в конфиге llmkit), `timeout`/`max_tokens`/`temperature` →
     в `Task`. Температура по умолчанию 0.7, как было (у llmkit дефолт 0.0 — передавать явно).
   - `LLMClient.generate/chat` → `kit.ask(Task(..., chain=..., default=None))`, при
     `AllModelsFailed` — лог и `None` (контракт сохранён). `generate_json` → `Task(schema=None)` +
     прежний strip_code_fence/json.loads/validate (dict-схемы у antagor нет, промпты просят JSON
     текстом; менять промпты не надо).
   - Метки: `tags={"tool": "antagor", "task": <label или имя модуля-вызывающего>,
     "project": <имя проекта, если доступно из config/контекста>}`.
   - `embed` и `generate_image` остаются на старом httpx-коде без изменений (вынести в
     `utils/llm_extra.py` или оставить в `llm.py` — на усмотрение, но без дублирования ключей:
     ключ брать через `llmkit.keys.resolve(provider)`).
   - Один `LlmKit` на процесс (модульный синглтон с ленивым созданием), `LLMClient.__aenter__`
     ничего не открывает.
3. **Конфиг llmkit** на этой машине: `llm config init`, провайдеры `ollama` (https://ollama.com)
   и `openrouter`; уровни antagor не использует (цепочка явная из `LLMConfig`).
4. **Проверка**: `python main.py --help`; один реальный прогон самой дешёвой команды antagor,
   которая зовёт `generate` (например, `query_expand` на 1–2 запросах), ключи из `.env`;
   вызов виден в `llm cost --by tool,task`. Тестов у antagor нет — не заводить сверх
   одного smoke-теста шима на фейковом `completion`.
5. **Удалить**: `_request_openrouter`, `_request_ollama`, `_call_provider`, ретраи/бэкофф
   в `utils/llm.py` (~350 строк); `ollama` из requirements, если после переноса не используется
   (проверить `embed`).
6. Коммит в antagor `refactor: LLM через llmkit (фаза 3)`; push делает пользователь.

Definition of done: все 38 файлов-потребителей не изменены (кроме импортов, если что-то
переименовано); `grep -rn httpx utils/llm.py` показывает только embed/image; реальный вызов
прошёл и учтён в `llm cost`; отчёт ≤ 15 строк.
