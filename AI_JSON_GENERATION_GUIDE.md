# ComposeFlow JSON Guide

Use this guide whenever generating a ComposeFlow workflow. For `/compose`
execution and response handoff, also follow `COMPOSE_PROTOCOL.md`. When asked
to generate a workflow JSON document, return one complete raw JSON document only. No Markdown fences, comments,
preamble, or trailing explanation.

## Required shape

```json
{
  "schemaVersion": "2.0",
  "workflow": { "nodes": [], "edges": [] },
  "execution": { "traces": {} }
}
```

Use valid JSON syntax: double-quoted keys and strings, lowercase `true`,
`false`, and `null`, no trailing commas. Keep arrays as arrays, even for one
item. `workflow.nodes` and `workflow.edges` must always be arrays.

## Nodes and edges

- Every node has a unique positive integer `id`, a lowercase `type`, and may
  have a text `title`.
- `input`: optional `file_path`, `file_paths` (array), `folder_path`, `purpose`,
  and boolean `allow_permission`. A folder uses `folder_path` alone.
- `context`: optional `description`, `file_paths` (array of `.md` paths), or
  `folder_path`. Do not mix folder and file paths.
- `task`: optional `description` and `contract`; contract may contain text
  `format`, string-array `style`, and string-array `acceptance`.
- `response`: always include `format`: `Markdown`, `Table`, or `JSON`. It must
  agree with the connected Task contract format. Optional `style` is an array
  of `Concise`, `Structure`, and/or `Technical`.
- Use only fields documented for that node type. Preserve supplied file paths;
  never invent paths or substitute paths from the AI host.
- `workflow.edges` is an array of edge objects with `source` and `target`, each
  containing `node` and `port`. Allowed pairs are `input.data → task.data`,
  `context.context → task.context`, `task.next → task.after`, and
  `task.contract → response.contract`. Response Contract accepts one edge;
  Task Contract may fan out. CONTROL edges must be acyclic.
- Do not put Plan, Action, or Evaluation nodes or system execution edges in
  `workflow`; ComposeFlow derives them from execution traces.

## Execution traces

Key `execution.traces` by Task ID as a string. Each trace may contain
`taskId`, `inputs_from`, `read_only`, `attempts`, `acceptedAttempt`, and
`result`.

- `inputs_from` is an array of predecessor Task IDs (integers), not file paths.
  Use `[]` when there are no predecessor Tasks.
- Set `read_only` to a JSON boolean. Use `true` for AI-generated execution
  reports.
- Each attempt contains `attempt`, `variantOf`, `plan`, `criteria`, `actions`,
  and `evaluation`. Use arrays for `plan.steps`, `criteria`, and `actions`.
- When an Action invokes a subagent, include that call in the Action's `subagents`
  array. Record every call in the parent Task attempt, including calls made by
  nested subagents. Each subagent entry has `id`, `agent`, `task`, `status`,
  `workflow`, and either `result` (completed) or `error` (failed/cancelled).
  `agent` is the exact OpenCode agent ID; `task` is a concise description of
  the dispatched assignment; `status` is `completed`, `failed`, or `cancelled`.
  `workflow` is an ordered array of `{step, action, result, subagents}` objects.
  Put child calls under the workflow step that invoked them, using the same
  subagent entry shape recursively. Add `parallelGroup` to sibling entries
  that ran concurrently; omit it for sequential calls. Preserve observed call
  order and outcomes. Summarize work and results; do not include hidden
  reasoning or invent steps that are not available from the run.
- Keep Plan titles short: `Plan - <main content>`. Evaluation `decision` and
  `report` are content, not pins. Use `pass`, `revise`, or `stop` for decision.
- Summarize each attempt's findings and decision in `evaluation.report`,
  including why a failed attempt needs revision. Link a later attempt with
  `variantOf` and summarize what changed.
- Add `acceptedAttempt` and `result` only when an attempt passed. The accepted
  result must satisfy the Task contract. For JSON output, keep the result
  content valid JSON. Do not create `Task.Result` or Result-to-Data edges.
- Include a concise final summary and answer in the accepted `result`, with key
  findings and evidence. Summarize findings and decisions; do not include
  hidden chain-of-thought. Do not invent execution details. Use empty `traces`
  when no execution report exists.

Example Action with a subagent call:

```json
{
  "header": "Delegate source review",
  "description": "Ask Explore to inspect the source",
  "subagents": [{
    "id": "explore-1",
    "agent": "explore",
    "task": "Inspect the source and report relevant findings",
    "status": "completed",
    "workflow": [{
      "step": 1,
      "action": "Read the source file",
      "result": "Located the relevant implementation.",
      "subagents": []
    }],
    "result": "The source implements the requested behavior."
  }]
}
```

## Check before returning

1. Parse the complete response as JSON; fix any syntax error.
2. Confirm the top-level keys and node/edge array shapes match the required
   structure.
3. Check unique node IDs, existing endpoints, allowed connections, and matching
   Response/Task formats.
4. Confirm trace IDs, `inputs_from`, decisions, accepted attempt, and result
   agree. Return only the JSON document.

## `/compose` response handoff

The launched `workflow.json` is immutable for a run. If at least one Response
node's **format field** is `JSON`, write a separate `response.json` beside it
using the versioned envelope in `COMPOSE_PROTOCOL.md`. Include all Response
nodes, including Markdown and Table formats, and all Task execution traces.
Each response entry identifies its `responseId`, Contract edge
`sourceTaskId`, exact `format`, and accepted `result`. Use the launched run ID
and SHA-256 of the exact workflow file bytes. Validate and reopen Report mode
with `python3 -m composeflow.compose_cli report WORKFLOW_PATH --response
RESPONSE_PATH`. If no Response format is JSON, deliver Markdown or Table in
the CLI session instead. Never infer the output format from free text.
