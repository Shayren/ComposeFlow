---
description: Open ComposeFlow and execute the workflow after Launch
---

ComposeFlow handoff:
!`tcsh -f -c 'python3 -m composeflow.compose_cli launch --wait' || true`

Read `COMPOSE_PROTOCOL.md` and `AI_JSON_GENERATION_GUIDE.md` in this project
if they were not loaded as startup instructions. The command opens the GUI
before the model responds and waits for Launch. Use only the
`COMPOSE_LAUNCHED` JSON line's exact `workflowPath`. On `COMPOSE_CANCELLED`
or nonzero exit, stop and report the reason. Validate the launched file,
execute its Tasks, and follow the shared delivery rule. Do not search for
exports or launch a second editor.
