import json
import os
import tempfile
from pathlib import Path

from .compose_cli import ComposeValidationError, validate_export


def save_launch_workflow(text: str, path: Path) -> None:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComposeValidationError(f"Invalid workflow JSON: {exc}") from exc
    if not isinstance(document, dict) or "execution" not in document:
        raise ComposeValidationError("Workflow needs schemaVersion, workflow, and execution")
    workflow = document.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise ComposeValidationError("Workflow needs a nodes array")
    for node in workflow["nodes"]:
        if not isinstance(node, dict):
            continue
        for key in ("file_path", "folder_path"):
            value = node.get(key)
            if isinstance(value, str) and value and not Path(value).is_absolute():
                node[key] = str((Path.cwd() / value).resolve())
        paths = node.get("file_paths")
        if isinstance(paths, list):
            node["file_paths"] = [
                str((Path.cwd() / value).resolve())
                if isinstance(value, str) and value and not Path(value).is_absolute()
                else value for value in paths]
    document["execution"] = {"traces": {}}
    content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ComposeValidationError(f"Run output already exists: {path}")
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".workflow-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_export(temporary)
        os.replace(temporary, path)
    except OSError as exc:
        raise ComposeValidationError(f"Could not save workflow at {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
