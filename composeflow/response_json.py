import hashlib
import json
from pathlib import Path


class ResponseJsonError(ValueError):
    pass


def requires_response_json(workflow: dict) -> bool:
    return any(node.get("type") == "response" and node.get("format") == "JSON"
               for node in workflow["nodes"])


def report_document(workflow_path: Path, response_path: Path) -> dict:
    try:
        workflow_bytes = workflow_path.read_bytes()
        workflow_document = json.loads(workflow_bytes)
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResponseJsonError(f"Cannot read workflow or response JSON: {exc}") from exc
    if not isinstance(workflow_document, dict) or not isinstance(response, dict):
        raise ResponseJsonError("Workflow and response.json must be JSON objects")
    if set(response) != {"responseSchemaVersion", "runId", "workflowSha256",
                         "execution", "responses"}:
        raise ResponseJsonError("response.json has missing or unsupported fields")
    if response["responseSchemaVersion"] != "1.0":
        raise ResponseJsonError("response.json needs responseSchemaVersion 1.0")
    if response["runId"] != workflow_path.parent.name:
        raise ResponseJsonError("response.json run ID does not match the launched workflow")
    if response_path.parent.resolve() != workflow_path.parent.resolve():
        raise ResponseJsonError("response.json must be beside its launched workflow")
    digest = hashlib.sha256(workflow_bytes).hexdigest()
    if response["workflowSha256"] != digest:
        raise ResponseJsonError("response.json workflow hash is stale or mismatched")
    workflow = workflow_document.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise ResponseJsonError("Launched workflow has no node list")
    if not requires_response_json(workflow):
        raise ResponseJsonError("This workflow has no JSON Response; return Markdown or tables directly")
    execution = response["execution"]
    entries = response["responses"]
    if (not isinstance(execution, dict) or set(execution) != {"traces"}
            or not isinstance(execution["traces"], dict)
            or not isinstance(entries, list)):
        raise ResponseJsonError("response.json needs execution.traces and a responses array")
    expected = {}
    for node in workflow["nodes"]:
        if node["type"] != "response":
            continue
        sources = [edge["source"]["node"] for edge in workflow["edges"]
                   if edge["target"] == {"node": node["id"], "port": "contract"}]
        if len(sources) != 1:
            raise ResponseJsonError(f"Response {node['id']} needs one source Task")
        expected[node["id"]] = (sources[0], node["format"])
    actual = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {
                "responseId", "sourceTaskId", "format", "result"}:
            raise ResponseJsonError("Each response needs responseId, sourceTaskId, format, result")
        response_id = item["responseId"]
        if type(response_id) is not int:
            raise ResponseJsonError("Each responseId must be an integer node ID")
        if response_id not in expected or response_id in actual:
            raise ResponseJsonError(f"Unknown or duplicate Response ID: {response_id}")
        actual.add(response_id)
        source_id, fmt = expected[response_id]
        if type(item["sourceTaskId"]) is not int or item["sourceTaskId"] != source_id:
            raise ResponseJsonError(f"Response {response_id} source Task does not match Contract edge")
        if item["format"] != fmt:
            raise ResponseJsonError(f"Response {response_id} format does not match workflow")
        trace = execution["traces"].get(str(source_id))
        if (not isinstance(trace, dict)
                or json.dumps(trace.get("result"), sort_keys=True)
                != json.dumps(item["result"], sort_keys=True)):
            raise ResponseJsonError(f"Response {response_id} result differs from Task {source_id} trace")
    if actual != set(expected):
        raise ResponseJsonError(f"response.json is missing Response IDs {sorted(set(expected) - actual)}")
    return {"schemaVersion": workflow_document["schemaVersion"],
            "workflow": workflow, "execution": execution}
