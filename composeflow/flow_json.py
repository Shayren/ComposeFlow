"""Semantic JSON projection of the current flow model."""

import json
import warnings as log_warnings
from pathlib import Path

from . import connections


_PORT_CONNECTIONS = connections.EDGES
_NODE_FIELDS = {
    "task": {"description", "contract"},
    "input": {"file_path", "file_paths", "folder_path", "purpose", "allow_permission"},
    "context": {"description", "file_paths", "folder_path"},
    "response": {"format", "style"},
    "plan": {"description"},
    "action": {"description"},
    "evaluation": {"description"},
}
_RESPONSE_FORMATS = {"Markdown", "Table", "JSON"}
_RESPONSE_STYLES = {"Concise", "Structure", "Structured", "Technical"}


def flow_to_dict(store):
    """Return the canonical workflow document without canvas/UI state."""
    nodes = [node for node in store.all() if not node.system_generated]
    edges = [edge for edge in store.connections() if edge.ownership == "USER"]
    serialized_nodes = []
    for node in nodes:
        item = {"id": node.id, "type": node.type}
        if node.header:
            item["title"] = node.header
        if node.type == "input":
            paths = node.file_paths or ([node.file_path]
                                        if node.file_path else [])
            if node.folder_path:
                item["folder_path"] = node.folder_path
            elif paths:
                item["file_path"] = paths[0]
                if len(paths) > 1:
                    item["file_paths"] = list(paths)
            if node.purpose:
                item["purpose"] = node.purpose
            item["allow_permission"] = bool(node.permission)
        elif node.type in ("task", "context"):
            if node.description:
                item["description"] = node.description
            if node.type == "context":
                if node.folder_path:
                    item["folder_path"] = node.folder_path
                elif node.file_paths:
                    item["file_paths"] = list(node.file_paths)
            if node.type == "task":
                item["contract"] = dict(node.contract)
        elif node.type == "response":
            item["format"] = node.response_format
            if node.response_styles:
                item["style"] = list(node.response_styles)
            if node.migration_legacy:
                item["migration"] = {"legacy": dict(node.migration_legacy)}
        elif node.type in ("plan", "action", "evaluation"):
            if node.description:
                item["description"] = node.description
        else:
            # Unknown-type node: re-emit id/type/title plus every preserved
            # raw property so the document survives the round trip verbatim.
            item.update(node.extra_props)
        serialized_nodes.append(item)

    serialized_edges = [
        {"source": {"node": edge.source_node, "port": edge.source_port},
         "target": {"node": edge.target_node, "port": edge.target_port}}
        for edge in edges
    ]
    return {"schemaVersion": "2.0",
            "workflow": {"nodes": serialized_nodes,
                         "edges": serialized_edges},
            "execution": {"traces": dict(store.execution_traces)}}


def flow_to_json(store):
    return json.dumps(flow_to_dict(store), indent=2, ensure_ascii=False)


def parse_flow_json(text, current_node_ids=()):
    """Parse and validate canonical flow JSON without mutating live state.

    Returns normalized semantic node and edge lists. Validation is strict so
    malformed or UI-only fields never partially update the canvas. Edges to
    node IDs that existed in the current graph but were removed from this
    document are pruned with the deleted node.
    """
    try:
        document = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON syntax") from exc
    if not isinstance(document, dict):
        raise ValueError("Expected a JSON object")
    legacy = "schemaVersion" not in document and "version" in document
    if legacy:
        if document.get("version") != "1.0" or set(document) != {"version", "workflow"}:
            raise ValueError("Unsupported legacy flow JSON version")
    elif (set(document) != {"schemaVersion", "workflow", "execution"}
          or not isinstance(document["schemaVersion"], str)
          or not document["schemaVersion"].startswith("2.")):
        raise ValueError("Expected schemaVersion 2.x, workflow, and execution")
    if legacy:
        document = _migrate_legacy(document)
    workflow = document["workflow"]
    if not isinstance(workflow, dict) or set(workflow) != {"nodes", "edges"}:
        raise ValueError("Workflow must contain nodes and edges")
    nodes, edges = workflow["nodes"], workflow["edges"]
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Nodes and edges must be arrays")

    normalized_nodes = []
    by_id = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"Node {index + 1} must be an object")
        node_id, node_type = node.get("id"), node.get("type")
        if (not isinstance(node_id, int) or isinstance(node_id, bool)
                or node_id < 1):
            raise ValueError(f"Node {index + 1} needs a positive integer id")
        if node_id in by_id:
            raise ValueError(f"Duplicate node id {node_id}")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError(f"Node {node_id} has an empty or non-text type")
        if node_type in _NODE_FIELDS:
            allowed = {"id", "type", "title"} | _NODE_FIELDS[node_type]
            if node_type == "response":
                allowed.add("migration")
            if set(node) - allowed:
                raise ValueError(f"Node {node_id} contains unsupported fields")
            title = node.get("title", "")
            if not isinstance(title, str):
                raise ValueError(f"Node {node_id} title must be text")
            item = {"id": node_id, "type": node_type, "title": title}
            for key in ("description", "file_path", "purpose"):
                if key in node:
                    if not isinstance(node[key], str):
                        raise ValueError(f"Node {node_id} {key} must be text")
                    item[key] = node[key]
            if "file_paths" in node:
                paths = node["file_paths"]
                if (not isinstance(paths, list)
                        or any(not isinstance(path, str) or not path
                               for path in paths)):
                    raise ValueError(f"Node {node_id} file_paths must be text values")
                item["file_paths"] = list(paths)
                if (node_type == "context"
                        and any(Path(path).suffix.casefold() != ".md"
                                for path in paths)):
                    raise ValueError(f"Node {node_id} Context files must be Markdown (.md)")
            if "folder_path" in node:
                folder = node["folder_path"]
                if not isinstance(folder, str) or not folder:
                    raise ValueError(f"Node {node_id} folder_path must be nonempty text")
                if "file_path" in node or "file_paths" in node:
                    raise ValueError(f"Node {node_id} cannot mix folder and file paths")
                item["folder_path"] = folder
            if "allow_permission" in node:
                if not isinstance(node["allow_permission"], bool):
                    raise ValueError(f"Node {node_id} allow_permission must be boolean")
                item["allow_permission"] = node["allow_permission"]
            if "format" in node:
                if (not isinstance(node["format"], str)
                        or node["format"] not in _RESPONSE_FORMATS):
                    raise ValueError(f"Node {node_id} has an unsupported response format")
                item["format"] = node["format"]
            if "contract" in node:
                contract = node["contract"]
                if not isinstance(contract, dict) or set(contract) - {
                        "format", "style", "acceptance"}:
                    raise ValueError(f"Node {node_id} has an invalid contract")
                if ("format" in contract and not isinstance(contract["format"], str)):
                    raise ValueError(f"Node {node_id} contract format must be text")
                if ("style" in contract and
                        (not isinstance(contract["style"], list) or
                         any(not isinstance(value, str)
                             for value in contract["style"]))):
                    raise ValueError(f"Node {node_id} contract style must be text values")
                if ("acceptance" in contract and
                        (not isinstance(contract["acceptance"], list) or
                         any(not isinstance(value, str)
                             for value in contract["acceptance"]))):
                    raise ValueError(f"Node {node_id} contract acceptance must be text values")
                item["contract"] = dict(contract)
            if "migration" in node:
                migration = node["migration"]
                if (node_type != "response" or not isinstance(migration, dict)
                        or set(migration) != {"legacy"}
                        or not isinstance(migration["legacy"], dict)):
                    raise ValueError(f"Node {node_id} has invalid migration data")
                item["migration_legacy"] = dict(migration["legacy"])
            if "style" in node:
                raw_styles = node["style"]
                if (not isinstance(raw_styles, list)
                        or any(not isinstance(style, str)
                               or style not in _RESPONSE_STYLES
                               for style in raw_styles)):
                    raise ValueError(f"Node {node_id} has invalid response styles")
                styles = ["Structure" if style == "Structured" else style
                          for style in raw_styles]
                if len(set(styles)) != len(styles):
                    raise ValueError(f"Node {node_id} has invalid response styles")
                item["style"] = styles
        else:
            # Unknown type: skip the strict allowed-fields / per-field checks
            # and preserve every available property verbatim. Title is
            # normalized to text ("" when missing or not a string).
            title = node.get("title", "")
            if not isinstance(title, str):
                title = ""
            item = {"id": node_id, "type": node_type, "title": title,
                    "extra_props": {
                        key: value for key, value in node.items()
                        if key not in ("id", "type", "title")}}
        normalized_nodes.append(item)
        by_id[node_id] = node_type

    removed_node_ids = set(current_node_ids) - set(by_id)
    normalized_edges = []
    edge_keys = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or set(edge) != {"source", "target"}:
            raise ValueError(f"Edge {index + 1} must contain source and target")
        source, target = edge["source"], edge["target"]
        if (not isinstance(source, dict) or set(source) != {"node", "port"}
                or not isinstance(target, dict)
                or set(target) != {"node", "port"}):
            raise ValueError(f"Edge {index + 1} has invalid endpoints")
        source_id, target_id = source["node"], target["node"]
        if (not isinstance(source_id, int) or isinstance(source_id, bool)
                or not isinstance(target_id, int) or isinstance(target_id, bool)
                or not isinstance(source["port"], str)
                or not isinstance(target["port"], str)):
            raise ValueError(f"Edge {index + 1} has invalid endpoint values")
        if source_id in removed_node_ids or target_id in removed_node_ids:
            continue
        if source_id not in by_id or target_id not in by_id:
            raise ValueError(f"Edge {index + 1} references a missing node")
        key = (source_id, source["port"], target_id, target["port"])
        if key in edge_keys:
            raise ValueError(f"Edge {index + 1} duplicates an existing edge")
        edge_keys.add(key)
        if source_id == target_id:
            raise ValueError(f"Edge {index + 1} cannot be a self-loop")
        if target["port"] == "contract" and by_id[target_id] == "response":
            if any(existing["target"]["node"] == target_id
                   and existing["target"]["port"] == "contract"
                   for existing in normalized_edges):
                raise ValueError("Response.Contract accepts one connection")
        typed_key = (by_id[source_id], source["port"],
                     by_id[target_id], target["port"])
        if (by_id[source_id] not in _NODE_FIELDS
                or by_id[target_id] not in _NODE_FIELDS):
            # Edge touches an unknown-type node: dropped entirely (not
            # parsed, not rendered, not exported).
            continue
        if typed_key not in _PORT_CONNECTIONS:
            raise ValueError(
                f"Edge {index + 1}: {connections.reason(
                    by_id[source_id], source["port"],
                    by_id[target_id], target["port"])}")
        normalized_edges.append({
            "source": {"node": source_id, "port": source["port"]},
            "target": {"node": target_id, "port": target["port"]},
        })
    control = {}
    for edge in normalized_edges:
        source, target = edge["source"], edge["target"]
        if source["port"] == "next" and target["port"] == "after":
            control.setdefault(source["node"], []).append(target["node"])
    visiting, visited = set(), set()

    def visit(node_id):
        if node_id in visiting:
            raise ValueError("USER CONTROL edges must form a DAG")
        if node_id in visited:
            return
        visiting.add(node_id)
        for target_id in control.get(node_id, ()):
            visit(target_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in control:
        visit(node_id)
    execution = document.get("execution", {"traces": {}})
    if (not isinstance(execution, dict) or set(execution) != {"traces"}
            or not isinstance(execution["traces"], dict)):
        raise ValueError("Execution must contain a traces object")
    for task_id, trace in execution["traces"].items():
        if (isinstance(trace, dict) and "read_only" in trace
                and not isinstance(trace["read_only"], bool)):
            raise ValueError(
                f"Execution trace {task_id} read_only must be boolean")
    return {"nodes": normalized_nodes, "edges": normalized_edges,
            "execution": execution}


def _migrate_legacy(document):
    """Convert v1's mixed workflow graph into the v2 authored graph."""
    workflow = document["workflow"]
    if not isinstance(workflow, dict):
        raise ValueError("Workflow must be an object")
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    ai_ids = {node.get("id") for node in nodes if isinstance(node, dict)
              and node.get("type") in ("plan", "action", "evaluation")}
    nodes = [dict(node) for node in nodes if isinstance(node, dict)
             and node.get("type") not in ("plan", "action", "evaluation")]
    by_id = {node.get("id"): node for node in nodes}
    incoming_task_edges = {}
    migrated_edges = []
    warnings = []
    for edge in edges:
        try:
            source, target = edge["source"], edge["target"]
            sid, tid = source["node"], target["node"]
            sport, tport = source["port"], target["port"]
        except (TypeError, KeyError):
            raise ValueError("Invalid legacy edge")
        if sid in ai_ids or tid in ai_ids:
            warnings.append("Removed a legacy AI execution node and its edges")
            continue
        source_node, target_node = by_id.get(sid), by_id.get(tid)
        if not source_node or not target_node:
            continue
        st, tt = source_node.get("type"), target_node.get("type")
        if st == "task" and tt == "task" and sport == "output" and tport == "input":
            warnings.append("Dropped a legacy Task.Result to Task.Data edge")
            continue
        elif st == "task" and tt == "response" and sport == "output" and tport == "input":
            sport, tport = "contract", "contract"
            incoming_task_edges.setdefault(tid, []).append(sid)
        elif st == "input" and tt == "task" and sport == "output" and tport == "input":
            sport, tport = "data", "data"
        elif st == "context" and tt == "task" and sport == "output" and tport == "context":
            sport, tport = "context", "context"
        elif st == "task" and sport in ("request", "result", "output"):
            warnings.append(f"Dropped legacy Task.{sport} connection")
            continue
        else:
            warnings.append("Dropped an unsupported legacy connection")
            continue
        migrated_edges.append({"source": {"node": sid, "port": sport},
                               "target": {"node": tid, "port": tport}})
    for response_id, response in by_id.items():
        if response.get("type") != "response":
            continue
        task_ids = incoming_task_edges.get(response_id, [])
        if (len(task_ids) == 1
                and ("format" in response or "style" in response)):
            task = by_id[task_ids[0]]
            task["contract"] = {
                "format": response.pop("format", "Markdown").lower(),
                "style": response.pop("style", []),
            }
        elif "format" in response or "style" in response:
            response.setdefault("migration", {})["legacy"] = {
                "format": response.pop("format", "Markdown"),
                "style": response.pop("style", []),
            }
            warnings.append(f"Response {response_id} contract migration was ambiguous")
    for node in nodes:
        node.pop("requires_response_contract", None)
        for key in ("result", "request"):
            if key in node:
                warnings.append(f"Dropped legacy Task.{key} property")
                node.pop(key, None)
    for warning in warnings:
        log_warnings.warn(warning, RuntimeWarning, stacklevel=2)
    return {"schemaVersion": "2.0",
            "workflow": {"nodes": nodes, "edges": migrated_edges},
            "execution": {"traces": {}}, "_warnings": warnings}
