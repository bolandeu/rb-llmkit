# llmkit — надстройка над 9router, а не свой клиент провайдеров

Статус: accepted (пользователь, 2026-11-06)

Свой доступ к провайдерам llmkit дублирует [9router](https://github.com/decolua/9router)
(`http://localhost:20128/v1`) — OAuth-подписки, ротацию аккаунтов, квоты,
трансляцию форматов, фолбэк — и дублирует беднее. Решено: все вызовы моделей
идут через шлюз, а llmkit делает то, чего у шлюза нет: типизированный API
(`ask`/`generate`/`ask_many`, JSON по схеме), кэш ответов, журнал расходов с
метками и бюджетами, контракты CLI (`--json`, `describe`, `doctor`).

## Границы

| Слой | Кто |
|---|---|
| доступ к провайдерам, OAuth-подписки, ротация аккаунтов, квоты, форматы | 9router |
| выбор модели, цепочка/комбо, ретраи при сбое провайдера | 9router |
| API и схемы, кэш, учёт и цены, метки, бюджеты, CLI | llmkit |

- В routing — один провайдер `openai_compatible` с `base_url` шлюза; ключи
  провайдеров живут в 9router, не в keychain llmkit.
- Уходят свои `transports/chatgpt*`, `transports/claude_cli.py`, `llm auth login`
  для подписок, `llm serve` (фаза 4), таблица `protocol` на каждого провайдера.
- Цепочка llmkit — список ссылок на модели или комбо; порядок и фолбэк
  исполняет шлюз, поэтому `attempts` и `chain_position` в `--json` сокращаются
  до одной попытки (ломающее — minor).
- Учёт: модель, назвавшая ответ, — из поля `model` ответа шлюза
  (`served_model`); ключ кэша — запрошенная ссылка (модель или комбо), чтобы
  один вопрос от цепочки кэшировался один раз.
- `llm doctor` проверяет доступность шлюза: без него llmkit не работает.
  Процесс обязателен, сеть — нет (шлюз локальный).

## Названия моделей

Ссылка на модель — строка ровно как она записана в настройке 9router: комбо
`Deep Sec` вызывается как `Deep Sec`, а имя с префиксом — с префиксом. llmkit
не разбирает `провайдер/модель`, не добавляет и не срезает префиксы и передаёт
строку в поле `model` как есть; `-m` в CLI, `chain` и ключи `prices` берут ту
же строку. Отсюда: `provider` в журнале — `9router`, `model` — эта строка,
`served_model` — что назвал шлюз в ответе. Следствие — имена с `/` больше не
значат провайдера, поэтому разбор ссылки (`routing.py`, `providers.py`,
`core.py`) уходит.

## Вся поверхность шлюза, включая медиа

llmkit оборачивает не только чат, а все эндпоинты 9router, чтобы были доступны
все его провайдеры и все виды сервисов (`serviceKinds`: llm, embedding,
image, imageToText, video, music, tts, stt, search, fetch):

- текст: `/v1/chat/completions`, `/v1/responses`, `/v1/responses/compact`,
  `/v1/messages`, `/v1/messages/count_tokens`, `/v1/api/chat`, `/v1/systemone`,
  `/v1beta/models` (форма Gemini);
- эмбеддинги и поиск: `/v1/embeddings`, `/v1/search`, `/v1/web/fetch`;
- модели: `/v1/models`, `/v1/models/info`, `/v1/models/{model}`;
- картинки: `/v1/images/generations`;
- речь: `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/voices`;
- видео: `/v1/videos/generations`, `/v1/videos/edits`, `/v1/videos/extensions`,
  `/v1/videos/{id}`.

Медиа-провайдеры (картинки, речь, видео, музыка) — чужие: llmkit передаёт
запрос и возвращает ответ типизированно (файл или URL, а не разбор форматов),
свой список провайдеров и ключей не ведёт.

## Журнал расходов — у шлюза

Свой журнал llmkit не пишет: шлюз уже пишет его сам — `usageHistory` (строка на
запрос: timestamp, provider, model, connectionId, apiKey, endpoint,
promptTokens, completionTokens, cost, status, tokens), `usageDaily` (агрегат дня
с `byProvider`, `byModel`, `byAccount`, `byApiKey`, `byEndpoint`), цена считается
самой 9router.

- Чтение — только SQLite шлюза в режиме read-only:
  `~/.9router/db/data.sqlite` (`mode=ro`); схема — его внутреннее дело, llmkit
  читает только `usageHistory` и `usageDaily` и не пишет туда ничего.
- HTTP `/api/usage/*` (stats, history, logs, chart, providers) существует, но
  требует сессии дашборда: API-ключ даёт 401. Пока шлюз не даст ключевой доступ,
  llmkit его не использует.
- Атрибуция по потребителям — ключом: у каждого потребителя свой API-ключ
  9router, в журнале он в колонке `apiKey`, в дне — в `byApiKey`.
- Уходят: таблицы `llmkit_calls` и `llmkit_cache`, миграции, слой БД
  (PostgreSQL/SQLite), `LLMKIT_DATABASE_URL`, `llm db *`, `llm cost` в текущем
  виде, метки и бюджеты, представление `llmkit_v1_calls`.

## Цена — из ответа шлюза

Своего прайса нет. Ответ `/v1/chat/completions` уже содержит всё, что нужно
(проверено живьём, `deepseek-4.1-flash`): `model` — фактическая модель
(`deepseek/deepseek-v4.1-flash-1017`), `provider` — имя провайдера,
`usage.cost` — цена в USD (`usage.cost_details` — её разбивка). Отсюда
`Answer.cost` — `usage.cost`, `served_model` — `model`, `provider` —
`provider`; таблица `prices` в routing уходит.

Особенность шлюза: на непоточный запрос он всё равно отвечает с
`content-type: text/event-stream` — тело это один JSON и строка `data: [DONE]`;
клиент разбирает оба вида.

## Кэша ответов нет

Кэширование ответов — не задача llmkit (пользователь, 2026-11-06): убираются
`cache.py`, таблица `llmkit_cache` (миграция, которая её удаляет), флаг
`--no-cache`, поле `cache_hit` в `--json` и статус строки `cache`. Ответ всегда
приходит от шлюза: повтор того же вопроса — снова вызов, а не попадание.

## Отвергнуто

- Оставить свои транспорты и `llm serve`: два доступа к тем же подпискам, наш
  беднее.
- Взять комбо шлюза, но сохранить свою цепочку ретраев: двойной фолбэк и
  двойной счёт попыток.
- Разбирать имя на `провайдер/модель`, как сейчас: имена комбо и провайдеров в
  шлюзе уже полные, разбор их ломает.

## Последствия

- Раздел 1 `docs/prd.md` (транспорты подписок, `llm serve`) и раздел
  `docs/backlog.md` «Внешний шлюз доступа (9router)» этой записью заменяются.
- Потребителям (antagor, intentree, windmill) нужен запущенный 9router; до
  выпуска они работают на прежних тегах llmkit.
- Кэш ответов убран — `--no-cache`, `cache_hit` и статус `cache` исчезают из
  контракта CLI (ломающее — minor).
- `llmkit_v1_calls` больше нет: `marketer/windmill` и `wordpress-bulk-editor`
  переходят на `usageHistory`/`usageDaily` шлюза (или на его `/api/usage/*`,
  когда тот откроется по ключу). Метки `tool`/`stage`/`niche` не сохраняются:
  группировка — по API-ключу потребителя.
