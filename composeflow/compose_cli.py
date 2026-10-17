import argparse
import json
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .flow_json import parse_flow_json
from .response_json import ResponseJsonError, report_document


@dataclass(frozen=True, slots=True)
class ComposeValidationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def check_environment(project_root: Path | None = None) -> None:
    root = project_root or Path(__file__).resolve().parent.parent
    _check_guides(root)
    try:
        import tkinter as tk
    except ImportError as exc:
        raise ComposeValidationError(
            "Tkinter is missing. Install your Python distribution's Tk package (for example python3-tk).") from exc
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise ComposeValidationError(
            f"No usable graphical display: {exc}. Start a desktop session or configure DISPLAY/XWayland.") from exc
    window.withdraw()
    window.destroy()


def launch_gui() -> int:
    check_environment()
    root = Path(__file__).resolve().parent.parent
    entry = root / "main.py"
    _require(entry.is_file(), f"ComposeFlow entry point is missing: {entry}")
    try:
        process = subprocess.Popen(
            [sys.executable, str(entry)], cwd=root,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        raise ComposeValidationError(f"Could not launch ComposeFlow: {exc}") from exc
    return process.pid


def _check_guides(root: Path) -> None:
    for name in ("COMPOSE_PROTOCOL.md", "AI_JSON_GENERATION_GUIDE.md"):
        path = root / name
        _require(path.is_file(),
                 f"Missing ComposeFlow guide: {path}. Restore the integration files before /compose.")


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ComposeValidationError(detail)


def _check_files(node: dict, base: Path) -> None:
    paths = list(node.get("file_paths", []))
    if node.get("file_path") and node["file_path"] not in paths:
        paths.append(node["file_path"])
    if node.get("folder_path"):
        paths.append(node["folder_path"])
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = base / path
        _require(path.exists(),
                 f"Node {node['id']} source not found: {path}. Select an existing path in ComposeFlow and export again.")
        if raw_path == node.get("folder_path"):
            _require(path.is_dir(), f"Node {node['id']} requires a folder: {path}")
            if node["type"] == "context":
                invalid = [item for item in path.rglob("*")
                           if item.is_file() and item.suffix.casefold() != ".md"]
                _require(not invalid,
                         f"Context node {node['id']} folder contains a non-Markdown file: {invalid[0] if invalid else ''}")
        else:
            _require(path.is_file(), f"Node {node['id']} requires a file: {path}")


def _check_trace(task_id: int, trace: dict, predecessors: set[int]) -> bool:
    _require(trace.get("taskId") == task_id,
             f"Trace {task_id} taskId must be {task_id}")
    sources = trace.get("inputs_from")
    _require(isinstance(sources, list)
             and all(type(source) is int for source in sources)
             and len(sources) == len(set(sources))
             and set(sources) == predecessors,
             f"Trace {task_id} inputs_from must list predecessor Tasks {sorted(predecessors)}")
    attempts = trace.get("attempts")
    _require(isinstance(attempts, list) and bool(attempts),
             f"Trace {task_id} needs at least one attempt")
    seen: set[int] = set()
    passed: set[int] = set()
    for item in attempts:
        _require(isinstance(item, dict), f"Trace {task_id} attempt must be an object")
        number = item.get("attempt")
        _require(type(number) is int and number > 0 and number not in seen,
                 f"Trace {task_id} attempt numbers must be unique positive integers")
        variant = item.get("variantOf")
        _require(variant is None or (type(variant) is int and variant in seen),
                 f"Trace {task_id} attempt {number} variantOf must refer to an earlier attempt")
        _require(isinstance(item.get("plan"), dict),
                 f"Trace {task_id} attempt {number} needs a plan object")
        steps = item["plan"].get("steps")
        _require(steps is None or (isinstance(steps, list)
                 and all(isinstance(step, str) for step in steps)),
                 f"Trace {task_id} attempt {number} plan.steps must be a text array")
        _require(isinstance(item.get("criteria"), list)
                 and all(isinstance(rule, str) for rule in item["criteria"]),
                 f"Trace {task_id} attempt {number} needs a criteria array")
        _require(isinstance(item.get("actions"), list)
                 and all(isinstance(action, dict) for action in item["actions"]),
                 f"Trace {task_id} attempt {number} needs an actions array of objects")
        evaluation = item.get("evaluation")
        _require(isinstance(evaluation, dict),
                 f"Trace {task_id} attempt {number} needs an evaluation object")
        _require(evaluation.get("decision") in ("pass", "revise", "stop"),
                 f"Trace {task_id} attempt {number} decision must be pass, revise, or stop")
        _require(isinstance(evaluation.get("report"), str)
                 and bool(evaluation["report"].strip()),
                 f"Trace {task_id} attempt {number} needs a summary in evaluation.report")
        if evaluation["decision"] == "pass":
            passed.add(number)
        seen.add(number)
    accepted = trace.get("acceptedAttempt")
    has_result = "result" in trace and trace["result"] is not None
    _require((accepted is None) == (not has_result),
             f"Trace {task_id} acceptedAttempt and result must appear together")
    if accepted is not None:
        _require(type(accepted) is int and accepted in passed,
                 f"Trace {task_id} acceptedAttempt must point to a pass evaluation")
    _require(not passed or accepted in passed,
             f"Trace {task_id} passed evaluation needs acceptedAttempt and result")
    return accepted is not None


def validate_export(path: Path, complete: bool = False,
                    against: Path | None = None) -> None:
    _check_guides(Path(__file__).resolve().parent.parent)
    _require(path.is_file(),
             f"Export file not found: {path}. Press Launch in ComposeFlow or export Flow JSON first.")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ComposeValidationError(f"Cannot read export {path}: {exc}") from exc
    try:
        document = json.loads(text)
        parsed = parse_flow_json(text)
    except ValueError as exc:
        raise ComposeValidationError(f"Invalid export {path}: {exc}") from exc
    _require(isinstance(document, dict)
             and isinstance(document.get("schemaVersion"), str)
             and document["schemaVersion"].startswith("2."),
             "Export must use schemaVersion 2.x; export the workflow again from ComposeFlow.")
    if against is not None:
        validate_export(against)
        baseline = json.loads(against.read_text(encoding="utf-8"))
        _require(document["schemaVersion"] == baseline["schemaVersion"],
                 "Report schemaVersion differs from original export.")
        _require(document["workflow"] == baseline["workflow"],
                 "Report workflow differs from original export; preserve authored nodes and edges.")
    nodes = {node["id"]: node for node in parsed["nodes"]}
    for node in nodes.values():
        _require(node["type"] not in ("plan", "action", "evaluation"),
                 f"Node {node['id']}: AI execution nodes belong in traces, not workflow.nodes.")
    tasks = {node_id for node_id, node in nodes.items() if node["type"] == "task"}
    _require(bool(tasks), "Export has no Task node to execute.")
    edges = parsed["edges"]
    for node in nodes.values():
        if node["type"] in ("input", "context"):
            _check_files(node, path.parent)
        if node["type"] == "input" and any(
                edge["source"]["node"] == node["id"]
                and edge["source"]["port"] == "data" for edge in edges):
            _require(node.get("allow_permission") is True,
                     f"Input node {node['id']} needs Allow permission enabled before AI reads it.")
    response_sources: dict[int, int] = {}
    for node in nodes.values():
        if node["type"] != "response":
            continue
        node_id = node["id"]
        sources = [edge["source"]["node"] for edge in edges
                   if edge["target"] == {"node": node_id, "port": "contract"}]
        _require(len(sources) == 1,
                 f"Response {node_id} needs exactly one Task.Contract connection.")
        source = nodes[sources[0]]
        fmt = node.get("format")
        _require(fmt in ("Markdown", "Table", "JSON"),
                 f"Response {node_id} needs a Format: Markdown, Table, or JSON.")
        contract_fmt = source.get("contract", {}).get("format", "markdown")
        _require(fmt.casefold() == contract_fmt.casefold(),
                 f"Response {node_id} format differs from Task {source['id']} Contract format.")
        response_sources[node_id] = source["id"]
    predecessors = {task_id: set() for task_id in tasks}
    for edge in edges:
        if edge["source"]["port"] == "next":
            predecessors[edge["target"]["node"]].add(edge["source"]["node"])
    traces = parsed["execution"]["traces"]
    accepted_tasks: set[int] = set()
    for key, trace in traces.items():
        _require(isinstance(key, str) and key.isdecimal()
                 and str(int(key)) == key and int(key) in tasks,
                 f"Trace key {key!r} must be an existing Task ID string.")
        _require(isinstance(trace, dict), f"Trace {key} must be an object.")
        _require(trace.get("read_only") is True,
                 f"Trace {key} must set read_only to true for AI execution nodes.")
        task_id = int(key)
        if _check_trace(task_id, trace, predecessors[task_id]):
            accepted_tasks.add(task_id)
    if complete:
        missing = sorted(tasks - accepted_tasks)
        _require(not missing,
                 f"Execution incomplete: Tasks {missing} lack accepted results.")
        for response_id, task_id in response_sources.items():
            _require(task_id in accepted_tasks,
                     f"Response {response_id} has no accepted Result from Task {task_id}.")


def validate_response_report(workflow_path: Path, response_path: Path) -> str:
    validate_export(workflow_path)
    try:
        document = report_document(workflow_path, response_path)
    except ResponseJsonError as exc:
        raise ComposeValidationError(str(exc)) from exc
    content = json.dumps(document, indent=2, ensure_ascii=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=workflow_path.parent,
                suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ComposeValidationError(f"Cannot validate response report: {exc}") from exc
    try:
        validate_export(temporary, complete=True, against=workflow_path)
    finally:
        temporary.unlink(missing_ok=True)
    return content


def launch_and_wait() -> int:
    check_environment()
    root = Path(__file__).resolve().parent.parent
    run_id = uuid.uuid4().hex
    output = Path.cwd() / ".composeflow" / "runs" / run_id / "workflow.json"
    try:
        completed = subprocess.run(
            [sys.executable, str(root / "main.py"), "--run-id", run_id,
             "--output-path", str(output)], cwd=Path.cwd(),
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise ComposeValidationError(f"Could not start ComposeFlow: {exc}") from exc
    if completed.returncode == 3:
        print("COMPOSE_CANCELLED " + json.dumps({"runId": run_id}))
        return 3
    if completed.returncode != 0:
        raise ComposeValidationError(
            f"ComposeFlow GUI exited with status {completed.returncode}: {completed.stderr.strip()}")
    validate_export(output)
    print("COMPOSE_LAUNCHED " + json.dumps(
        {"runId": run_id, "workflowPath": str(output)}))
    return 0


def reopen_report(workflow_path: Path, response_path: Path) -> int:
    validate_response_report(workflow_path, response_path)
    check_environment()
    root = Path(__file__).resolve().parent.parent
    try:
        process = subprocess.Popen(
            [sys.executable, str(root / "main.py"),
             "--report-workflow", str(workflow_path.resolve()),
             "--response-json", str(response_path.resolve())], cwd=root,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        raise ComposeValidationError(f"Could not open Report mode: {exc}") from exc
    print(f"ComposeFlow Report mode opened (PID {process.pid}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch ComposeFlow, validate a workflow, or open Report mode")
    parser.add_argument("command", choices=("doctor", "launch", "validate", "report"))
    parser.add_argument("path", nargs="?", type=Path,
                        help="exact workflow JSON path for validate or report")
    parser.add_argument("--complete", action="store_true",
                        help="require accepted results for every Task")
    parser.add_argument("--against", type=Path,
                        help="compare the report with the original GUI export")
    parser.add_argument("--wait", action="store_true",
                        help="wait for Launch or cancellation and print the exact workflow path")
    parser.add_argument("--response", type=Path,
                        help="matching response.json for Report mode")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            check_environment()
            print("ComposeFlow GUI and guides are ready.")
            return 0
        if args.command == "launch":
            if args.wait:
                return launch_and_wait()
            print(f"ComposeFlow GUI launched (PID {launch_gui()}).")
            return 0
        if args.command == "report":
            if args.path is None or args.response is None:
                raise ComposeValidationError(
                    "Use report /path/to/workflow.json --response /path/to/response.json")
            return reopen_report(args.path, args.response)
        if args.path is None:
            raise ComposeValidationError(
                "Give the exported JSON path: python3 -m composeflow.compose_cli validate /path/to/flow.json")
        validate_export(args.path, complete=args.complete, against=args.against)
    except ComposeValidationError as exc:
        print(f"ComposeFlow validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"ComposeFlow export valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
