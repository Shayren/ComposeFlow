"""ComposeFlow node model. Pure logic; no tkinter imports."""

from dataclasses import dataclass, field
from itertools import count

from . import connections, theme


@dataclass
class Node:
    id: int
    type: str
    label: str
    x: float               # world coordinates, top-left corner
    y: float
    w: float = theme.CANVAS_NODE_W
    h: float = theme.CANVAS_NODE_H
    file_path: str = ""    # input node: imported file
    purpose: str = ""      # input node: purpose text
    permission: bool = False  # input node: allow-permission flag
    header: str = ""       # numbered or user-edited content card title
    description: str = ""
    response_format: str = "Markdown"
    response_styles: list = field(default_factory=list)
    result_summary: str | None = None
    contract: dict = field(default_factory=lambda: {"format": "markdown"})
    system_generated: bool = False
    execution_content: dict = field(default_factory=dict)
    execution_task_id: int | None = None
    migration_legacy: dict = field(default_factory=dict)
    auto_header: bool = False
    extra_props: dict = field(default_factory=dict)  # unknown-type raw props
    read_only: bool = False
    file_paths: list[str] = field(default_factory=list)
    folder_path: str = ""


@dataclass(frozen=True)
class Connection:
    source_node: int
    source_port: str
    target_node: int
    target_port: str
    type: str = "DATA"
    ownership: str = "USER"


class NodeStore:
    """Ordered node collection with multi-select state.

    The full selection is a set of node ids; `selected()` returns a single
    primary node (the most recently added to the selection) for the calls
    that only understand one node, and the set is authoritative.
    """

    def __init__(self):
        self._nodes = {}
        self._connections = {}
        self._ids = count(1)
        self._selected = None
        self._selected_ids = set()
        self.execution_traces = {}

    def _card_header(self, node_type):
        index = sum(node.type == node_type for node in self._nodes.values()) + 1
        label = theme.NODE_TYPES.get(node_type, {}).get("label", node_type)
        return f"{label} {index}"

    def _reindex_headers(self, node_type):
        index = 0
        label = theme.NODE_TYPES.get(node_type, {}).get("label", node_type)
        for node in self._nodes.values():
            if node.type != node_type:
                continue
            index += 1
            if node.auto_header:
                node.header = f"{label} {index}"

    def add(self, node_type, x, y, w=None, h=None):
        """Add a node. When w/h are None, the node takes the type's
        NODE_DIMS (the task node-> card is larger); types without an entry
        fall back to the classic compact 200x160 box."""
        if node_type in theme.AI_NODE_TYPES:
            raise ValueError("AI execution nodes are generated from execution traces")
        if node_type not in theme.USER_NODE_TYPES:
            raise ValueError(f"unknown node type: {node_type!r}")
        if w is None or h is None:
            w, h = theme.NODE_DIMS.get(
                node_type, (theme.CANVAS_NODE_W, theme.CANVAS_NODE_H))
        node = Node(next(self._ids), node_type,
                    theme.NODE_TYPES[node_type]["label"], x, y, w, h)
        node.header = self._card_header(node_type)
        node.auto_header = True
        self._nodes[node.id] = node
        self._reindex_headers(node_type)
        return node

    def get(self, node_id):
        return self._nodes.get(node_id)

    def all(self):
        return list(self._nodes.values())

    def connections(self):
        return list(self._connections.values())

    def delete_connection(self, connection):
        if connection.ownership == "SYSTEM":
            return False
        key = (connection.source_node, connection.source_port,
               connection.target_node, connection.target_port)
        return self._connections.pop(key, None) is not None

    def replace_graph(self, node_specs, edge_specs, positions):
        """Replace semantic graph data while keeping supplied UI positions."""
        old_selected = set(self._selected_ids)
        if self._selected is not None:
            old_selected.add(self._selected.id)
        nodes = {}
        for spec in node_specs:
            node_type = spec["type"]
            if node_type in theme.AI_NODE_TYPES:
                raise ValueError(
                    "AI execution nodes cannot be stored in workflow.nodes")
            node_id = spec["id"]
            x, y = positions[node_id]
            w, h = theme.NODE_DIMS.get(node_type, theme.UNKNOWN_DIMS)
            label = theme.NODE_TYPES.get(node_type, {}).get("label", node_type)
            node = Node(node_id, node_type, label, x, y, w, h)
            node.header = spec.get("title", "")
            if node_type in theme.NODE_TYPES:
                prefix = f"{node.label} "
                legacy_header = f"{node.label} Header"
                node.auto_header = (
                    not node.header or node.header == legacy_header
                    or (node.header.startswith(prefix)
                        and node.header[len(prefix):].isdigit()))
                if node.header == legacy_header:
                    node.header = ""
            else:
                node.auto_header = False
            node.description = spec.get("description", "")
            node.file_path = spec.get("file_path", "")
            node.file_paths = list(spec.get("file_paths", ()))
            node.folder_path = spec.get("folder_path", "")
            if node.type == "input":
                if not node.file_paths and node.file_path:
                    node.file_paths = [node.file_path]
                node.file_path = (node.file_paths[0]
                                  if node.file_paths else "")
            node.purpose = spec.get("purpose", "")
            node.permission = spec.get("allow_permission", False)
            node.response_format = spec.get("format", "Markdown")
            node.response_styles = list(spec.get("style", ()))
            node.contract = dict(spec.get("contract", {"format": "markdown"}))
            node.migration_legacy = dict(spec.get("migration_legacy", {}))
            node.extra_props = dict(spec.get("extra_props", ()))
            nodes[node_id] = node

        self._nodes = nodes
        for node_type in theme.NODE_ORDER:
            self._reindex_headers(node_type)
        self._connections = {}
        for spec in edge_specs:
            source, target = spec["source"], spec["target"]
            key = (source["node"], source["port"],
                   target["node"], target["port"])
            properties = connections.connection_properties(
                nodes[source["node"]].type, source["port"],
                nodes[target["node"]].type, target["port"])
            if properties is None or properties[1] != "USER":
                raise ValueError("Workflow edges must be valid USER connections")
            self._connections[key] = Connection(*key, *properties)
        self._ids = count(max(nodes, default=0) + 1)
        self._selected_ids = old_selected & set(nodes)
        self._selected = (self._nodes.get(min(self._selected_ids))
                          if self._selected_ids else None)

    def connect(self, source_node, source_port, target_node, target_port):
        """Add a typed USER edge, independent of endpoint selection order."""
        candidate = self._connection_candidate(
            source_node, source_port, target_node, target_port)
        if candidate is None:
            return None
        source_node, source_port, target_node, target_port, source, target = candidate
        key = (source_node, source_port, target_node, target_port)
        connection = Connection(*key, *connections.connection_properties(
            source.type, source_port, target.type, target_port))
        self._connections[key] = connection
        if (source.type, source_port, target.type, target_port) == (
                "task", "contract", "response", "contract"):
            source.contract.setdefault("format", "markdown")
        return connection

    def can_connect(self, first_node, first_port, second_node, second_port):
        """Return whether a USER edge can be added without changing state."""
        return self._connection_candidate(
            first_node, first_port, second_node, second_port) is not None

    def _connection_candidate(self, first_node, first_port,
                              second_node, second_port):
        """Normalize endpoint order and apply all graph constraints."""
        source_node, target_node = first_node, second_node
        source_port, target_port = first_port, second_port
        source = self.get(source_node)
        target = self.get(target_node)
        if (source is None or target is None or source.system_generated
                or target.system_generated):
            return None
        canonical = connections.canonical_user_edge(
            source.type, source_port, target.type, target_port)
        if canonical is None:
            return None
        reverse_gesture = (canonical != (source.type, source_port,
                                          target.type, target_port))
        _source_type, source_port, _target_type, target_port = canonical
        if reverse_gesture:
            source_node, target_node = target_node, source_node
            source, target = target, source
        if source_node == target_node:
            return None
        if (target.type, target_port) == ("response", "contract") and any(
                edge.target_node == target_node and edge.target_port == target_port
                for edge in self._connections.values()):
            return None
        if (source.type, source_port, target.type, target_port) == (
                "task", "next", "task", "after") and self._would_cycle(
                    source_node, target_node):
            return None
        key = (source_node, source_port, target_node, target_port)
        if key in self._connections:
            return None
        return (*key, source, target)

    def connect_reason(self, source_node, source_port, target_node,
                       target_port):
        """Why a connect() call would be rejected, or None if it is legal
        (already connected or a valid edge)."""
        source = self.get(source_node)
        target = self.get(target_node)
        if source is not None and target is not None:
            if connections.canonical_user_edge(
                    source.type, source_port, target.type, target_port):
                return None
        return connections.reason(
            source.type if source else None, source_port,
            target.type if target else None, target_port)

    @staticmethod
    def _valid_connection(source, source_port, target, target_port):
        if source is None or target is None:
            return False
        return connections.is_legal(
            source.type, source_port, target.type, target_port)

    def _would_cycle(self, source_id, target_id):
        pending, visited = [target_id], set()
        while pending:
            node_id = pending.pop()
            if node_id == source_id:
                return True
            if node_id in visited:
                continue
            visited.add(node_id)
            pending.extend(
                edge.target_node for edge in self._connections.values()
                if edge.ownership == "USER" and edge.type == "CONTROL"
                and edge.source_node == node_id and edge.source_port == "next"
                and edge.target_port == "after")
        return False

    def add_system_connection(self, source_node, source_port,
                              target_node, target_port):
        """Add a known report relationship; user connect() cannot add it."""
        source, target = self.get(source_node), self.get(target_node)
        if source is None or target is None:
            return None
        properties = connections.SYSTEM_CONNECTIONS.get(
            (source.type, source_port, target.type, target_port))
        if properties is None:
            return None
        key = (source_node, source_port, target_node, target_port)
        if key in self._connections:
            return None
        connection = Connection(*key, *properties)
        self._connections[key] = connection
        return connection

    def set_execution(self, traces):
        """Build the read-only execution graph from runtime traces."""
        self.execution_traces = dict(traces or {})
        self._nodes = {nid: node for nid, node in self._nodes.items()
                       if not node.system_generated}
        self._connections = {
            key: edge for key, edge in self._connections.items()
            if edge.ownership == "USER"}
        for node in self._nodes.values():
            if node.type == "response":
                node.result_summary = None
                node.h = theme.RESPONSE_CARD_H
        next_id = max(self._nodes, default=0) + 1
        generated = {}

        def make_node(task, kind, content, x, y, title, read_only=False):
            nonlocal next_id
            node_id = next_id
            next_id += 1
            label = theme.NODE_TYPES[kind]["label"]
            node = Node(node_id, kind, label, x, y,
                        *theme.NODE_DIMS[kind], system_generated=True,
                        execution_content=content,
                        execution_task_id=task.id, read_only=read_only)
            node.header = title
            node.description = _execution_summary(kind, content)
            self._nodes[node_id] = node
            generated[node_id] = node
            return node

        def attempt_title(title):
            suffix = f" · A{attempt_number}"
            title = title.removesuffix(suffix).removesuffix(
                f" · Attempt {attempt_number}")
            if len(title) + len(suffix) > 44:
                title = title[:41 - len(suffix)].rstrip() + "..."
            return title + suffix

        def header_for(content, fallback):
            value = content.get("header") if isinstance(content, dict) else None
            title = value.strip() if isinstance(value, str) and value.strip() else fallback
            return attempt_title(title)

        task_edges = list(self._connections.values())
        for task_id, trace in traces.items():
            try:
                task_id = int(task_id)
            except (TypeError, ValueError):
                continue
            task = self.get(task_id)
            if task is None or task.type != "task" or not isinstance(trace, dict):
                continue
            read_only = trace.get("read_only", False) is True
            attempts = trace.get("attempts", [])
            if not isinstance(attempts, list):
                attempts = []
            accepted = trace.get("acceptedAttempt")
            result_summary = accepted_result_summary(trace)
            task_responses = [self.get(edge.target_node) for edge in task_edges
                              if edge.source_node == task.id
                              and edge.source_port == "contract"]
            task_responses = [node for node in task_responses
                              if node is not None and node.type == "response"]
            valid_attempts = [item for item in attempts
                              if isinstance(item, dict)]
            row_gap = theme.AI_CARD_H + theme.AI_CARD_GAP
            stage_gap = theme.AI_CARD_W + theme.AI_CARD_GAP
            lane_gap = 80
            execution_height = (len(valid_attempts) * theme.AI_CARD_H
                                + max(0, len(valid_attempts) - 1)
                                * theme.AI_CARD_GAP)
            top_y = task.y - lane_gap - execution_height
            for row, attempt in enumerate(valid_attempts):
                attempt_number = attempt.get("attempt", row + 1)
                row_y = top_y + row * row_gap
                task_title = task.header.strip() or f"Task {task.id}"
                plan_data = attempt.get("plan", {})
                plan_main = _main_content(plan_data) or task_title
                plan_header = (plan_main if plan_main.casefold().startswith("plan -")
                               else f"Plan - {plan_main}")
                plan_header = attempt_title(plan_header)
                plan = make_node(task, "plan", {
                    "plan": plan_data,
                    "criteria": attempt.get("criteria", []),
                }, task.x + task.w + theme.AI_CARD_GAP, row_y,
                    plan_header, read_only)
                actions_data = attempt.get("actions", [])
                if not isinstance(actions_data, list):
                    actions_data = []
                actions = [make_node(task, "action", item,
                                     task.x + task.w + theme.AI_CARD_GAP
                                     + (index + 1) * stage_gap, row_y,
                                     header_for(
                                         item,
                                         f"Action {index + 1} · {task_title}"),
                                     read_only)
                           for index, item in enumerate(actions_data)
                           if isinstance(item, dict)]
                evaluation_x = (task.x + task.w + theme.AI_CARD_GAP
                                + (len(actions) + 1) * stage_gap)
                evaluation_data = attempt.get("evaluation", {})
                evaluation = make_node(
                    task, "evaluation",
                    evaluation_data if isinstance(evaluation_data, dict) else {},
                    evaluation_x, row_y,
                    header_for(evaluation_data,
                               f"Evaluation · {task_title}"),
                    read_only)
                self.add_system_connection(task.id, "task", plan.id, "task")
                for edge in task_edges:
                    if edge.target_node != task.id:
                        continue
                    source = self.get(edge.source_node)
                    if source is None:
                        continue
                    if edge.target_port == "context" and source.type == "context":
                        self.add_system_connection(source.id, "context", plan.id, "context")
                    if edge.target_port == "data" and source.type == "input":
                        for action in actions:
                            self.add_system_connection(source.id, "data", action.id, "data")
                for action in actions:
                    self.add_system_connection(plan.id, "plan", action.id, "plan")
                    self.add_system_connection(action.id, "output", evaluation.id, "output")
                    self.add_system_connection(action.id, "observation", evaluation.id,
                                               "observation")
                self.add_system_connection(plan.id, "criteria", evaluation.id, "criteria")
                if attempt_number == accepted and result_summary is not None:
                    for response in task_responses:
                        self.add_system_connection(evaluation.id, "result",
                                                   response.id, "result")
                        response.result_summary = result_summary
                        response.h = theme.RESPONSE_RESULT_CARD_H
        self._ids = count(max(self._nodes, default=0) + 1)


    def selected(self):
        return self._selected

    def selected_ids(self):
        """The full multi selection as a set of node ids (possibly empty)."""
        return set(self._selected_ids)

    def is_selected(self, node_id):
        return node_id in self._selected_ids

    def select(self, node_id):
        node = None if node_id is None else self._nodes.get(node_id)
        self._selected = node
        self._selected_ids = set() if node is None else {node.id}

    def toggle_select(self, node_id):
        """Flip one node's membership in the selection, keeping the rest."""
        node = self._nodes.get(node_id)
        if node is None:
            return
        if node.id in self._selected_ids:
            self._selected_ids.discard(node.id)
            self._selected = (self._nodes.get(min(self._selected_ids))
                              if self._selected_ids else None)
        else:
            self._selected_ids.add(node.id)
            self._selected = node

    def select_many(self, node_ids, add=False):
        """Replace (add=False) or extend (add=True) the selection with the
        given ids. Unknown ids are ignored."""
        valid = {node_id for node_id in node_ids
                 if node_id in self._nodes}
        self._selected_ids = self._selected_ids | valid if add else valid
        if self._selected_ids:
            if (self._selected is None
                    or self._selected.id not in self._selected_ids):
                self._selected = self._nodes.get(min(self._selected_ids))
        else:
            self._selected = None

    def move_delta(self, node_id, dx, dy):
        node = self._nodes.get(node_id)
        if node is None or node.system_generated:
            return
        node.x += dx
        node.y += dy

    def delete(self, node_id):
        if node_id in self._nodes and self._nodes[node_id].system_generated:
            return
        removed = self._nodes.pop(node_id, None)
        if removed is not None:
            self._reindex_headers(removed.type)
        self._connections = {
            key: connection for key, connection in self._connections.items()
            if connection.source_node != node_id
            and connection.target_node != node_id
        }
        if self._selected is not None and self._selected.id == node_id:
            self._selected = None
        self._selected_ids.discard(node_id)
        if self._selected is None and self._selected_ids:
            self._selected = self._nodes.get(min(self._selected_ids))

    def reorder_by_type(self):
        """Rewind node insertion order grouped by type following
        theme.NODE_ORDER, stable within each type (existing relative order
        is preserved). Header numbering is re-computed for each type."""
        ordered = {}
        for node_type in theme.NODE_ORDER:
            for node in self._nodes.values():
                if node.type == node_type:
                    ordered[node.id] = node
        # Unknown types have no NODE_ORDER slot: keep them, grouped after the
        # known types in their existing relative order.
        for node in self._nodes.values():
            if node.id not in ordered:
                ordered[node.id] = node
        self._nodes = ordered
        for node_type in theme.NODE_ORDER:
            self._reindex_headers(node_type)
        return ordered

    def change_type(self, node_id, node_type):
        """Switch a node's type/label/dims. ID, x, and y stay stable; w/h
        reset to the TARGET type's NODE_DIMS (task becomes the large card,
        any other type the compact box)."""
        if node_type not in theme.USER_NODE_TYPES:
            raise ValueError(f"unknown node type: {node_type!r}")
        node = self._nodes.get(node_id)
        if node is None:
            return None
        if node.system_generated or node.read_only:
            return None
        old_type = node.type
        node.type = node_type
        node.label = theme.NODE_TYPES[node_type]["label"]
        if node_type != old_type:
            if node_type in ("task", "input"):
                node.header = self._card_header(node_type)
                node.auto_header = True
            elif node_type in ("context", "response"):
                node.header = self._card_header(node_type)
                node.auto_header = True
        node.w, node.h = theme.NODE_DIMS.get(
            node_type, (theme.CANVAS_NODE_W, theme.CANVAS_NODE_H))
        self._connections = {
            key: connection for key, connection in self._connections.items()
            if self._valid_connection(
                self.get(connection.source_node), connection.source_port,
                self.get(connection.target_node), connection.target_port)
        }
        if node_type != old_type:
            self._reindex_headers(old_type)
            self._reindex_headers(node_type)
        return node


def accepted_result_summary(trace):
    if (not isinstance(trace, dict) or trace.get("acceptedAttempt") is None
            or trace.get("result") is None):
        return None
    attempts = trace.get("attempts", [])
    if not isinstance(attempts, list):
        return None
    for attempt in attempts:
        if (isinstance(attempt, dict)
                and attempt.get("attempt") == trace["acceptedAttempt"]
                and isinstance(attempt.get("evaluation"), dict)
                and attempt["evaluation"].get("decision") == "pass"):
            return _summary_text(trace["result"]) or "(Empty result)"
    return None


def _execution_summary(kind, content):
    if not isinstance(content, dict):
        return _summary_text(content)
    if kind == "plan":
        plan = content.get("plan", {})
        sections = [_summary_text(plan)]
        if isinstance(plan, dict) and plan.get("steps"):
            sections.append("Steps:\n" + _summary_text(plan["steps"]))
        if content.get("criteria"):
            sections.append("Criteria:\n" + _summary_text(content["criteria"]))
        return "\n\n".join(section for section in sections if section)
    if kind == "evaluation":
        sections = []
        decision = content.get("decision")
        if isinstance(decision, str) and decision.strip():
            sections.append(f"Decision: {decision.strip().upper()}")
        report = _summary_text(content.get("report", ""))
        if report:
            sections.append(report)
        else:
            for key in ("output", "observation"):
                summary = _summary_text(content.get(key, ""))
                if summary:
                    sections.append(summary)
        return "\n\n".join(sections)
    if kind == "action":
        sections = [_summary_text(content)]
        subagents = _subagent_summary(content.get("subagents"))
        if subagents:
            sections.append("Subagent workflow:\n" + subagents)
        return "\n\n".join(section for section in sections if section)
    return _summary_text(content)


def _subagent_summary(subagents, indent=0):
    if not isinstance(subagents, list):
        return ""
    lines = []
    pad = "  " * indent
    for item in subagents:
        if not isinstance(item, dict):
            continue
        agent = str(item.get("agent", "subagent")).strip() or "subagent"
        status = str(item.get("status", "unknown")).strip().upper()
        parallel_group = item.get("parallelGroup")
        parallel_label = (f" · parallel {parallel_group}"
                          if parallel_group is not None else "")
        task = _summary_text(item.get("task"))
        lines.append(f"{pad}• {agent} · {status}{parallel_label}")
        if task:
            lines.append(f"{pad}  Task: {task}")
        workflow = item.get("workflow", [])
        if isinstance(workflow, list):
            for index, step in enumerate(workflow, 1):
                if not isinstance(step, dict):
                    continue
                number = step.get("step", index)
                action = _summary_text(step.get("action")) or "Workflow step"
                result = _summary_text(step.get("result"))
                lines.append(f"{pad}  {number}. {action}")
                if result:
                    lines.append(f"{pad}     Result: {result}")
                children = _subagent_summary(
                    step.get("subagents"), indent=indent + 2)
                if children:
                    lines.append(children)
        result = _summary_text(item.get("result"))
        error = _summary_text(item.get("error"))
        if result:
            lines.append(f"{pad}  Returned: {result}")
        elif error:
            lines.append(f"{pad}  Error: {error}")
    return "\n".join(lines)


def _main_content(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return next((text for item in value
                     if (text := _main_content(item))), "")
    if isinstance(value, dict):
        for key in ("summary", "objective", "goal", "content", "description",
                    "text", "header", "title", "name", "prompt", "plan",
                    "steps"):
            if key in value and (text := _main_content(value[key])):
                return text
    return ""


def _summary_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(
            f"• {text}" for item in value
            if (text := _summary_text(item)))
    if isinstance(value, dict):
        for key in ("summary", "objective", "goal", "content", "description",
                    "text", "header", "title", "name", "prompt", "plan",
                    "steps", "action", "output", "observation", "report",
                    "decision"):
            if key in value and (text := _summary_text(value[key])):
                return text
        return "\n".join(
            f"{key.replace('_', ' ').capitalize()}: {text}"
            for key, item in value.items()
            if (text := _summary_text(item)))
    return ""
