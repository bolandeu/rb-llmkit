---
id: LLMKIT-IDEA-008
title: routing v1 rejects fields it used to ignore
created: '2026-11-06T18:42:57+00:00'
source_project: llmkit
source_path: /Users/bolandau/Work/tools/llmkit
status: new
---

After E-003 llmkit rejects a routing file with unknown fields: a working file with "mode": "TOOLS" and "prices": {} (both accepted before) now fails every command with ROUTING_INVALID, and the status command answers with the error envelope instead of its credentials list. Two such files existed on this machine, one of them the Human's own, and the release gate went red on the standard health step because of it. Decide: unknown field is a warning (keep reading), or a hard error with a migration note in the release and in the routing validate output.
