---
id: LLMKIT-IDEA-002
title: Streaming output in generate and the CLI
created: '2026-11-06T15:59:45+00:00'
source_project: llmkit
source_path: /Users/bolandau/Work/tools/llmkit
status: new
---

llmkit always sends stream=true and assembles the answer itself. A caller that wants the text as it arrives has no way: add a streaming path to `generate` (an async iterator or a callback) and `--stream` to `llm ask`, keeping the same envelope at the end.
