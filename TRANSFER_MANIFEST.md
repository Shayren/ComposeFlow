# ComposeFlow 2.4.0 transfer manifest

Copy this release folder. It contains **34 files**: 26 Python runtime files and 8 guide, command, and release documents. `subagent-workflow.json` is an example workflow for checking the subagent trace visualization.

```text
ComposeFlow_release/
├── README.md
├── TRANSFER_MANIFEST.md
├── COMPOSE_PROTOCOL.md
├── AI_JSON_GENERATION_GUIDE.md
├── subagent-workflow.json
├── main.py
├── requirements.txt
├── .opencode/
│   └── commands/
│       └── compose.md
├── .agents/
│   └── skills/
│       └── compose/
│           └── SKILL.md
└── composeflow/
    ├── __init__.py
    ├── compose_cli.py
    ├── connections.py
    ├── display_placement.py
    ├── flow_json.py
    ├── model.py
    ├── response_json.py
    ├── run_files.py
    ├── theme.py
    └── ui/
        ├── __init__.py
        ├── app.py
        ├── context_card.py
        ├── execution_card.py
        ├── file_import.py
        ├── flow_canvas.py
        ├── font_cache.py
        ├── future_panel.py
        ├── header.py
        ├── input_card.py
        ├── node_list.py
        ├── response_card.py
        ├── rounded_button.py
        ├── task_card.py
        ├── title_marquee.py
        └── unknown_card.py
```

## Requirements and commands

- Python: **3.10 or newer** with Tkinter and a graphical display.
- External Python packages: **none**. `requirements.txt` intentionally declares no installable packages.
- Optional system command: `xrandr` for laptop-display window placement. If absent, the window manager places the app.
- External workflow files: any JSON, Input, or Context files the user chooses to open are supplied separately; none are needed at launch.
- OpenCode or Codex, a configured AI provider, and the source files are required only for agent execution.

Install from this folder:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Run from this folder:

```sh
python3 main.py
```

Run from elsewhere with `python3 /path/to/ComposeFlow_release/main.py`.

## Runtime file roles

| Files | Purpose |
|---|---|
| `main.py`, `composeflow/display_placement.py` | Launch Tkinter and choose the initial display when possible. |
| `composeflow/__init__.py`, `composeflow/ui/__init__.py` | Preserve the Python package structure. |
| `composeflow/connections.py`, `composeflow/model.py`, `composeflow/flow_json.py`, `composeflow/theme.py` | Graph rules and data, JSON import/export, and visual definitions. |
| `composeflow/compose_cli.py`, `run_files.py`, `response_json.py` | Launch and atomically save workflows, validate versioned response reports, and open matching Report mode files. |
| `composeflow/ui/app.py`, `header.py`, `node_list.py`, `future_panel.py`, `flow_canvas.py` | Main window, panels, canvas, and interactions. |
| `composeflow/ui/input_card.py`, `context_card.py`, `task_card.py`, `response_card.py`, `execution_card.py`, `unknown_card.py` | All supported card renderers, including the fallback for unknown node types. |
| `composeflow/ui/file_import.py`, `font_cache.py`, `rounded_button.py`, `title_marquee.py` | File/folder selection, shared UI drawing helpers, and long-title hover scrolling. |
| `COMPOSE_PROTOCOL.md`, `AI_JSON_GENERATION_GUIDE.md` | Shared Launch/response handoff and JSON output rules. |
| `subagent-workflow.json` | Example flow with nested subagent traces for testing the workflow visualization. |
| `.opencode/commands/compose.md`, `.agents/skills/compose/SKILL.md` | OpenCode `/compose` and Codex `$compose` entry files. |
| `README.md`, `requirements.txt`, `TRANSFER_MANIFEST.md` | Setup instructions, dependency declaration, and this inventory. |

## Excluded from this runtime package

- `test_bench.py` and the entire `tests/` directory, including test JSON fixtures.
- `SortLayoutTest.json`, `response.json`, and other local sample/demo JSON files. Runtime code does not load them. `subagent-workflow.json` is the release's explicit trace-visualization example.
- Test-only fixtures and any local AI execution reports; these are supplied or generated separately.
- `__pycache__/`, `.pyc`, logs, screenshots, temporary/debug files, and unused development scripts.
