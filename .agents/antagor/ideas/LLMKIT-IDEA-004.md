---
id: LLMKIT-IDEA-004
title: Move the consumers onto the gateway journal
created: '2026-11-06T15:59:47+00:00'
source_project: llmkit
source_path: /Users/bolandau/Work/tools/llmkit
status: new
---

antagor, intentree and windmill still read the old spend surfaces of llmkit. Each consumer moves to its own gateway API key and reads `usageHistory`/`usageDaily` (or `/api/usage/*` when the gateway opens it by key). Outside this repository; the Human decides the order.
