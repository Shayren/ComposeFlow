---
name: compose
description: Open ComposeFlow, wait for Launch, execute its Tasks, and deliver Responses.
---

Read `../../../COMPOSE_PROTOCOL.md` and `../../../AI_JSON_GENERATION_GUIDE.md`
relative to this skill folder. Run
`python3 -m composeflow.compose_cli launch --wait` from the current Codex
working directory (set `PYTHONPATH` to the ComposeFlow install directory if
needed). Wait until the GUI closes. Read only the `COMPOSE_LAUNCHED` line's
exact `workflowPath`; on `COMPOSE_CANCELLED`, stop. Follow the shared protocol
for validation, execution, response.json, and Report mode.
