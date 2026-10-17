# ComposeFlow 2.4.0

ComposeFlow is a Tkinter desktop workflow editor. This folder contains the application and its OpenCode/Codex integration.

## Requirements

- Python 3.10 or newer
- Tkinter and a graphical display (`python3-tk` may need to be installed separately on Debian/Ubuntu)
- No third-party Python packages; `requirements.txt` has no installable dependencies

`xrandr` is optional on Linux. When available, ComposeFlow places the window on the monitor under the pointer. The app still opens if it is unavailable.

## Install

From this folder:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

After an accepted PASS, each bound Response shows a read-only **SUMMARY RESULT**
below **FORMAT** and **STYLE**. Long results scroll inside the card. Generated
attempt labels use **A1**, **A2**, and so on; the JSON schema is unchanged.

```sh
python3 main.py
```

From any other working directory, run `python3 /path/to/ComposeFlow_release/main.py`. Workflow JSON and input/context files are selected by the user; no sample files are required to start the app.

## OpenCode and Codex

OpenCode 1.18.32 loads this folder's `.opencode/commands/compose.md` as
`/compose`. Codex 0.157.0 loads `.agents/skills/compose/SKILL.md` as
`$compose`; the installed Codex CLI does not provide a project-owned
`/compose` slash command. Both adapters read the shared procedure in
[COMPOSE_PROTOCOL.md](COMPOSE_PROTOCOL.md) and the schema in
[AI_JSON_GENERATION_GUIDE.md](AI_JSON_GENERATION_GUIDE.md).

```sh
opencode .       # enter /compose
codex -C .       # enter $compose
```

The command opens ComposeFlow immediately. Edit or import a workflow, then
press **▶** in the JSON panel header (or in its collapsed rail). Collapsed
controls are vertical: Expand, Launch, Export, Import, Copy, and Paste/Update.
Launch validates
and atomically saves the run's
`.composeflow/runs/<runId>/workflow.json` under the active CLI working
directory, closes the GUI, and hands the exact path to the agent. Closing
without Launch cancels the run.

The agent executes Tasks and checks every Response card's Format field. If
any Response requests JSON, it writes one versioned `response.json` for the
whole run and opens ComposeFlow in Report mode. Otherwise it returns the
requested Markdown or Table Responses in the CLI session.

From another working directory, install thin global adapters under
`~/.config/opencode/commands/compose.md` and
`~/.codex/skills/compose/SKILL.md`, pointing `PYTHONPATH` and guide paths
to this copied release folder. For OpenCode, add the absolute paths to the
two guides under `instructions` in `~/.opencode/opencode.json` so they load
at startup. The OpenCode command uses `tcsh -f`, so install `tcsh` if absent.
Restart Codex after installing its skill.

```sh
python3 -m composeflow.compose_cli doctor
python3 -m composeflow.compose_cli validate /exact/path/workflow.json
python3 -m composeflow.compose_cli report /exact/path/workflow.json --response /exact/path/response.json
```

`doctor` reports missing guides, Tkinter, or display access. Launch errors
leave the GUI open for correction. Report import rejects mismatched or stale
run IDs, workflow hashes, and Response bindings before opening Report mode.

Panel controls stay hidden during expand/collapse animation and appear once
the panel reaches its final width. The canvas then fits the workflow.
