---
id: LLMKIT-IDEA-005
title: Перевод потребителей на поверхность llmkit после E-003
created: '2026-11-06T17:11:31+00:00'
source_project: llmkit
source_path: /Users/bolandau/Work/tools/llmkit
status: new
---

Из плана проекта (Фаза 3). Первым — antagor: заменить самописные LLM-клиенты на generate()/ask(). Затем intentree: адаптер Task(stage, subject_type, subject_id) -> llmkit.Task, LlmRunner поверх ask_many_sync, LlmStats из kit.stats; журнал решений остаётся в intentree. Затем windmill-скрипты и одноразовые клиенты в tasks/*: перейти на llm --json и на журнал шлюза usageHistory вместо таблиц llmkit_*. Условие: выпущенный тег llmkit с командой llm и шлюз 9router на машине потребителя.
