"""ComposeFlow flow canvas: grid, node placement/selection/movement,
pan/zoom, and the drag-and-drop target side."""

import heapq
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from types import SimpleNamespace

from .. import connections, theme
from ..model import NodeStore, accepted_result_summary
from .rounded_button import RoundedButton
from .task_card import TaskCard
from .input_card import InputCard
from .context_card import ContextCard
from .response_card import ResponseCard
from .execution_card import ExecutionCard
from .unknown_card import UnknownCard

# Node types rendered as embedded card windows (TaskCard / InputCard /
# ContextCard / ResponseCard / ExecutionCard) — the seven known content
# types. Unknown (non-theme) types always render as cards too, so the
# palette stays limited to the known ones.
CARD_TYPES = ("task", "input", "context", "response",
              "plan", "action", "evaluation")


def is_card_type(node_type):
    """Compact-vs-card decision: known non-card types (future compact
    boxes) stay compact; everything known-card and every unknown type
    renders as an embedded card."""
    return node_type in CARD_TYPES or node_type not in theme.NODE_TYPES

# Arrow-key pan step (screen px). Arrow keys move the VIEW in the key
# direction (content slides opposite); MMB drag keeps its own
# content-follows-cursor convention in _pan_motion.
KEY_PAN_STEP = 48
EXECUTION_BAND_GAP = 128.0
EXECUTION_LANE_GAP = 112.0
SORT_NODE_GAP = 96.0

# perf counters (CF_PERF=1)
_PERF = os.environ.get("CF_PERF") == "1"
_P = {"redraws": 0, "redraw_ms": 0.0, "viewport_ms": 0.0,
      "grid_ms": 0.0, "grid_items": 0,
      "node_items": 0, "card_creates": 0, "card_zoom_updates": 0,
      "pan_events": 0, "zoom_events": 0, "resize_events": 0,
      "card_drag_events": 0, "node_drag_events": 0,
      "viewport_frames": 0, "grid_reuses": 0,
      "node_item_updates": 0}


def perf_reset():
    if _PERF:
        for k in _P:
            _P[k] = 0


def perf_snapshot():
    return dict(_P) if _PERF else None


def _execution_region_bounds(nodes):
    """Return the world-space frame bounds for each AI execution group."""
    groups = {}
    for node in nodes:
        if node.type in ("plan", "action", "evaluation"):
            groups.setdefault(node.execution_task_id, []).append(node)
    return [
        (task_id, (
            min(node.x for node in group) - theme.AI_REGION_PADDING,
            min(node.y for node in group) - theme.AI_REGION_PADDING,
            max(node.x + node.w for node in group) + theme.AI_REGION_PADDING,
            max(node.y + node.h for node in group) + theme.AI_REGION_PADDING,
        ))
        for task_id, group in groups.items()
    ]


def snap_to_grid(x, y, min_x=None, min_y=None, max_x=None, max_y=None,
                 grid_x=None, grid_y=None):
    if grid_x is None: grid_x = theme.CREATE_GRID_X
    if grid_y is None: grid_y = theme.CREATE_GRID_Y
    sx = round(x / grid_x) * grid_x
    sy = round(y / grid_y) * grid_y
    if min_x is not None: sx = max(sx, min_x)
    if min_y is not None: sy = max(sy, min_y)
    if max_x is not None: sx = min(sx, max_x)
    if max_y is not None: sy = min(sy, max_y)
    return sx, sy


def grid_step(base, zoom):
    """World grid step: base at zoom >= 1.0; scaled up while zoomed out so
    the on-screen pitch stays constant (base px) below zoom 1.0."""
    return base / zoom if zoom < 1.0 else base


class FlowCanvas(tk.Canvas):
    def __init__(self, master, **kw):
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, **kw)

        self.store = NodeStore()
        self.on_flow_change = None
        self.on_ai_node_interaction = None

        self.pan_x = 0.0
        self.pan_y = 0.0
        self.zoom = 1.0
        self._zoom_min = 0.25
        self._rendered_pan = (self.pan_x, self.pan_y)
        self._rendered_zoom = self.zoom
        self._view_job = None
        self._view_needs_redraw = False
        self._layout_frozen = False
        self.on_fit_request = None
        self._grid_items = {}
        self._node_items = {}
        self._ai_region_items = []
        self._ai_regions_by_task = {}
        self._region_font = None

        self._drag = None        # (node_id, grab_sx, grab_sy, start_x, start_y)
        self._pan_start = None   # (root_x, root_y, pan_x, pan_y) during pan
        self._preview = None     # dnd drop-preview rectangle item id

        self._cards = {}         # node_id -> card widget (task/input nodes)
        self._card_wins = {}     # node_id -> canvas window item id
        self._connection_items = {}
        self._connection_halos = {}
        self._connection_paths = {}
        self._route_scene_signature = None
        self._route_transition_job = None
        self._route_transition_overlays = {}
        self._routing_revision = 0
        self._connection_drag = None
        self._connection_line = None
        self._connection_cursor = None
        self._connection_target = None
        self._connection_compatible_targets = set()
        self._connection_reason_items = []
        self._hovered_connection = None
        self._selected_connection = None
        self._highlighted_wire_ports = set()
        self._wire_style_job = None
        self._wire_style_animation = None
        self._wire_style_target = frozenset()
        self._wire_hovered_card = None
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle = set()
        self._route_drag_positions = {}
        self._grab = None        # (root_x, root_y, start_x, start_y) in card drag
        self._drag_from_card = False  # card drag in progress (not _motion)
        self._drag_motion_job = None
        self._pending_card_motion = None
        self._last_drag_frame = 0.0

        self._zoom_box_start = None
        self._zoom_box = None
        self._sel_box_start = None  # (x0, y0) LMB selection-box anchor
        self._sel_box = None

        # Compact-node label font, scaled with zoom (rebuilt from the
        # theme base size whenever self.zoom changes).
        base = tkfont.Font(font=theme.FONT_NODE)
        self._node_font = tkfont.Font(
            family=base.actual("family"), size=base.actual("size"),
            weight=base.actual("weight"), slant=base.actual("slant"))
        self._node_font_size = base.actual("size")
        self._node_font_zoom = 1.0

        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Motion>", self._wire_hover_motion)
        self.bind("<Leave>", self._wire_hover_leave)
        self.bind("<ButtonPress-2>", self._pan_press)
        self.bind("<ButtonPress-3>", self._zoom_box_press)
        self.bind("<B3-Motion>", self._zoom_box_motion)
        self.bind("<ButtonRelease-3>", self._zoom_box_release)
        self.bind("<B2-Motion>", self._pan_motion)
        self.bind("<ButtonRelease-2>", self._pan_release)
        self.bind("<Delete>", self._delete_key)
        self.bind("<BackSpace>", self._delete_key)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._on_destroy, add="+")
        # f / F = Fit All Nodes. One bind_all binding covers canvas- and
        # app-window focus (canvas bindtags end at 'all', so no double-fire).
        self.bind_all("<KeyPress-f>", self._fit_key)
        self.bind_all("<KeyPress-F>", self._fit_key)
        # s / S = place the graph by its connection dependencies.
        self.bind_all("<KeyPress-s>", self._sort_key)
        self.bind_all("<KeyPress-S>", self._sort_key)
        self.bind_all("<KeyPress-Escape>", self._escape_connection_selection)
        # Arrow keys pan the VIEW in the key direction (Up/Left move the
        # view up/left; content slides opposite). Same bind_all pattern as
        # f/s; the Text/Entry guard (JSON editor / card fields) lives in
        # _pan_key.
        self.bind_all("<KeyPress-Up>",
                      lambda e: self._pan_key(e, 0, KEY_PAN_STEP))
        self.bind_all("<KeyPress-Down>",
                      lambda e: self._pan_key(e, 0, -KEY_PAN_STEP))
        self.bind_all("<KeyPress-Left>",
                      lambda e: self._pan_key(e, KEY_PAN_STEP, 0))
        self.bind_all("<KeyPress-Right>",
                      lambda e: self._pan_key(e, -KEY_PAN_STEP, 0))
        # Scroll zooms anywhere over the canvas tree, without requiring Ctrl.
        self.bind_all("<Button-4>", lambda e: self._plain_zoom(e, 1))
        self.bind_all("<Button-5>", lambda e: self._plain_zoom(e, -1))
        self.bind_all("<MouseWheel>",
                      lambda e: self._plain_zoom(e, -1 if e.delta < 0 else 1))

        self._zoom_controls = tk.Frame(self, bg=theme.CANVAS_BG)
        self._zoom_label = tk.Label(
            self._zoom_controls, text="100%", font=theme.FONT_SMALL,
            bg=theme.CANVAS_BG, fg=theme.TEXT_MUTED)
        self._zoom_label.pack(side="left", padx=(0, 6))
        RoundedButton(self._zoom_controls, text="\u229e",
                      command=self._sort_flow,
                      width=34, height=34, radius=8,
                      fill=theme.PANEL_BG_ALT, fg=theme.TEXT,
                      outline=theme.BORDER, outlinewidth=1,
                      font=("Helvetica", 14), page_bg=theme.CANVAS_BG,
                      ).pack(side="left", padx=(0, 6))
        RoundedButton(self._zoom_controls, text="\u26f6",
                      command=self._fit_button,
                      width=34, height=34, radius=8,
                      fill=theme.PANEL_BG_ALT, fg=theme.TEXT,
                      outline=theme.BORDER, outlinewidth=1,
                      font=("Helvetica", 14), page_bg=theme.CANVAS_BG,
                      ).pack(side="left")
        self._zoom_controls.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)
        self._zoom_controls.tkraise()

    # ------------------------------------------------------------ transforms
    def destroy(self):
        """Remove application-wide bindings before this canvas goes away."""
        if not self.winfo_exists():
            return
        for sequence in (
                "<Motion>", "<ButtonRelease-1>",
                "<KeyPress-f>", "<KeyPress-F>",
                "<KeyPress-s>", "<KeyPress-S>", "<KeyPress-Escape>",
                "<KeyPress-Up>", "<KeyPress-Down>",
                "<KeyPress-Left>", "<KeyPress-Right>",
                "<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.unbind_all(sequence)
        super().destroy()

    def world_to_screen(self, wx, wy):
        return wx * self.zoom + self.pan_x, wy * self.zoom + self.pan_y

    def screen_to_world(self, sx, sy):
        return (sx - self.pan_x) / self.zoom, (sy - self.pan_y) / self.zoom

    # --------------------------------------------------------------- queries
    def node_count(self):
        return len(self.store.all())

    def _notify_flow_change(self):
        if self.on_flow_change is not None:
            self.on_flow_change()

    def _notify_ai_node_interaction(self):
        if self.on_ai_node_interaction is not None:
            self.on_ai_node_interaction()

    def apply_workflow(self, workflow, auto_layout=False,
                       execution_traces=None):
        """Apply a previously validated semantic graph to the canvas."""
        if self._connection_drag is not None:
            self._cancel_connection()
        old_positions = {node.id: (node.x, node.y)
                         for node in self.store.all()}
        cw, ch = self.winfo_width(), self.winfo_height()
        center = self.screen_to_world(cw / 2, ch / 2)
        positions = {}
        if auto_layout:
            positions = self._workflow_layout(workflow, center,
                                              execution_traces)
        else:
            new_ids = set()
            for spec in workflow["nodes"]:
                node_id = spec["id"]
                if node_id in old_positions:
                    positions[node_id] = old_positions[node_id]
                else:
                    w, h = theme.NODE_DIMS.get(
                        spec["type"], theme.UNKNOWN_DIMS)
                    positions[node_id] = snap_to_grid(
                        center[0] - w / 2, center[1] - h / 2,
                        grid_x=grid_step(theme.CREATE_GRID_X, self.zoom),
                        grid_y=grid_step(theme.CREATE_GRID_Y, self.zoom))
                    new_ids.add(node_id)
        self.store.replace_graph(workflow["nodes"], workflow["edges"],
                                 positions)
        if execution_traces is not None:
            self.store.set_execution(execution_traces)
            if auto_layout:
                self._stack_execution_turns()
        self._routing_revision += 1
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle.clear()
        self._route_drag_positions.clear()
        if auto_layout:
            self.fit_all()
        else:
            self._redraw()
            for node_id in new_ids:
                self._resolve_card_overlap(node_id)
        self._notify_flow_change()

    def apply_execution(self, traces):
        """Render read-only report nodes and system-owned execution edges."""
        self.store.set_execution(traces or {})
        self._routing_revision += 1
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle.clear()
        self._route_drag_positions.clear()
        self._redraw()
        self._sync_port_colors()
        self._settle_wire_routes()

    @staticmethod
    def _workflow_layout(workflow, center, execution_traces=None):
        """Place the authored workflow and alternating execution regions.

        Task control edges order the main lane. Successive execution regions
        alternate above and below it, and linked Responses follow their
        Evaluation horizontally.
        """
        specs = workflow["nodes"]
        if not specs:
            return {}
        by_id = {spec["id"]: spec for spec in specs}

        def stable_key(node_id):
            spec = by_id[node_id]
            return (str(spec.get("title", "")).casefold(),
                    str(spec["type"]).casefold(), str(node_id))

        execution_groups = {}
        stage_gap = theme.AI_CARD_W + theme.AI_CARD_GAP
        for task_key, trace in (execution_traces or {}).items():
            try:
                task_id = int(task_key)
            except (TypeError, ValueError):
                continue
            if (task_id not in by_id or by_id[task_id]["type"] != "task"
                    or not isinstance(trace, dict)):
                continue
            raw_attempts = trace.get("attempts", [])
            attempts = ([item for item in raw_attempts if isinstance(item, dict)]
                        if isinstance(raw_attempts, list) else [])
            if not attempts:
                continue
            action_counts = [
                sum(isinstance(action, dict) for action in attempt.get("actions", []))
                if isinstance(attempt.get("actions", []), list) else 0
                for attempt in attempts
            ]
            max_actions = max(action_counts, default=0)
            execution_groups[task_id] = {
                "attempts": attempts,
                "width": (theme.TASK_CARD_W + theme.AI_CARD_GAP
                          + (max_actions + 1) * stage_gap + theme.AI_CARD_W),
                "height": (len(attempts) * theme.AI_CARD_H
                           + max(0, len(attempts) - 1)
                           * theme.AI_CARD_GAP),
            }

        # Task.Next -> Task.After is the workflow's dependency ordering.
        tasks = {node_id for node_id, spec in by_id.items()
                 if spec["type"] == "task"}
        children = {node_id: set() for node_id in tasks}
        parents = {node_id: set() for node_id in tasks}
        response_tasks = {}
        for edge in workflow["edges"]:
            source, target = edge["source"], edge["target"]
            source_id, target_id = source["node"], target["node"]
            if (source.get("port") == "next"
                    and target.get("port") == "after"
                    and source_id in tasks and target_id in tasks):
                children[source_id].add(target_id)
                parents[target_id].add(source_id)
            if (source.get("port") == "contract"
                    and target.get("port") == "contract"
                    and source_id in tasks
                    and by_id.get(target_id, {}).get("type") == "response"):
                response_tasks.setdefault(target_id, source_id)

        indegree = {node_id: len(parents[node_id]) for node_id in tasks}
        ready = sorted((node_id for node_id, degree in indegree.items()
                        if degree == 0), key=stable_key)
        task_order = []
        while ready:
            previous = task_order[-1] if task_order else None
            adjacent = [node_id for node_id in ready
                        if previous in parents[node_id]]
            source_id = min(adjacent, key=stable_key) if adjacent else ready[0]
            ready.remove(source_id)
            task_order.append(source_id)
            for target_id in sorted(children[source_id], key=stable_key):
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    ready.append(target_id)
                    ready.sort(key=stable_key)
        # Imported malformed workflows can contain cycles. Keep those cards
        # stable and visible after the valid dependency order.
        task_order.extend(sorted(tasks - set(task_order), key=stable_key))

        gap_x = SORT_NODE_GAP
        sources = sorted(
            (node_id for node_id, spec in by_id.items()
             if spec["type"] in ("input", "context")),
            key=lambda node_id: (0 if by_id[node_id]["type"] == "input" else 1,
                                 stable_key(node_id)))
        positions = {}
        source_x = 0.0
        for node_id in sources:
            positions[node_id] = (source_x, 0.0)
            source_x += (theme.NODE_DIMS[by_id[node_id]["type"]][0] + gap_x)

        task_x = source_x if sources else 0.0
        task_y = 0.0
        task_xs = {}
        for task_id in task_order:
            task_xs[task_id] = task_x
            positions[task_id] = (task_x, task_y)
            task_x += theme.TASK_CARD_W + gap_x

        response_x = task_x
        for task_id in task_order:
            branch_right = task_xs[task_id] + theme.TASK_CARD_W
            group = execution_groups.get(task_id)
            if group is not None:
                branch_right = max(branch_right,
                                   task_xs[task_id] + group["width"])
            linked_responses = sorted(
                (response_id for response_id, owner in response_tasks.items()
                 if owner == task_id), key=stable_key)
            for response_id in linked_responses:
                response_x = max(response_x, branch_right + gap_x)
                positions[response_id] = (response_x, task_y)
                response_x += theme.NODE_DIMS["response"][0] + gap_x

        # Keep unconnected Responses and future user node types visible after
        # the connected task branches.
        for node_id in sorted(
                (node_id for node_id, spec in by_id.items()
                 if spec["type"] == "response" and node_id not in positions),
                key=stable_key):
            positions[node_id] = (response_x, task_y)
            response_x += theme.NODE_DIMS["response"][0] + gap_x
        for node_id in sorted(set(by_id) - set(positions), key=stable_key):
            positions[node_id] = (response_x, task_y)
            response_x += theme.NODE_DIMS.get(by_id[node_id]["type"],
                                              theme.UNKNOWN_DIMS)[0] + gap_x

        # Center against both lanes, including virtual AI cards that
        # NodeStore.set_execution() will create from the same trace geometry.
        boxes = []
        result_tasks = {int(task_id) for task_id, trace in
                        (execution_traces or {}).items()
                        if str(task_id).isdigit()
                        and accepted_result_summary(trace) is not None}
        for node_id, (x, y) in positions.items():
            width, height = theme.NODE_DIMS.get(by_id[node_id]["type"],
                                                theme.UNKNOWN_DIMS)
            if response_tasks.get(node_id) in result_tasks:
                height = theme.RESPONSE_RESULT_CARD_H
            boxes.append((x, y, x + width, y + height))
        band_tops = FlowCanvas._execution_band_tops(
            task_order,
            {task_id: group["height"]
             for task_id, group in execution_groups.items()},
            min(box[1] for box in boxes), max(box[3] for box in boxes))
        for task_id in task_order:
            group = execution_groups.get(task_id)
            if group is None:
                continue
            plan_x = (task_xs[task_id] + theme.TASK_CARD_W
                      + theme.AI_CARD_GAP)
            top_y = band_tops[task_id]
            for row, attempt in enumerate(group["attempts"]):
                row_y = top_y + row * (theme.AI_CARD_H
                                       + theme.AI_CARD_GAP)
                action_count = (sum(isinstance(action, dict)
                                    for action in attempt.get("actions", []))
                                if isinstance(attempt.get("actions", []), list)
                                else 0)
                for column in range(action_count + 2):
                    x = plan_x + column * stage_gap
                    boxes.append((x, row_y, x + theme.AI_CARD_W,
                                  row_y + theme.AI_CARD_H))
        if boxes:
            min_x = min(box[0] for box in boxes)
            min_y = min(box[1] for box in boxes)
            max_x = max(box[2] for box in boxes)
            max_y = max(box[3] for box in boxes)
            dx = center[0] - (min_x + max_x) / 2
            dy = center[1] - (min_y + max_y) / 2
            positions = {node_id: (x + dx, y + dy)
                         for node_id, (x, y) in positions.items()}
        return positions

    @staticmethod
    def _execution_band_tops(task_order, heights, user_top, user_bottom):
        """Alternate Task execution regions above and below the main lane."""
        upper_bottom = user_top - EXECUTION_LANE_GAP
        lower_top = user_bottom + EXECUTION_LANE_GAP
        positions = {}
        for task_id in task_order:
            height = heights.get(task_id)
            if height is None:
                continue
            if len(positions) % 2 == 0:
                top = upper_bottom - height
                upper_bottom = top - EXECUTION_BAND_GAP
            else:
                top = lower_top
                lower_top = top + height + EXECUTION_BAND_GAP
            positions[task_id] = top
        return positions

    def _stack_execution_turns(self):
        """Place each Task's generated cards in its alternating region."""
        user_nodes = [node for node in self.store.all()
                      if not node.system_generated]
        tasks = sorted((node for node in user_nodes if node.type == "task"),
                       key=lambda node: (node.x, node.header.casefold(),
                                         str(node.id)))
        if not user_nodes:
            return
        groups = {}
        for node in self.store.all():
            if node.system_generated:
                groups.setdefault(node.execution_task_id, []).append(node)
        heights = {
            task_id: max(node.y + node.h for node in group)
                     - min(node.y for node in group)
            for task_id, group in groups.items()
        }
        band_tops = FlowCanvas._execution_band_tops(
            (task.id for task in tasks), heights,
            min(node.y for node in user_nodes),
            max(node.y + node.h for node in user_nodes))
        for task in tasks:
            group = groups.get(task.id)
            if not group:
                continue
            top = min(node.y for node in group)
            new_top = band_tops[task.id]
            for node in group:
                node.y += new_top - top

    def node_at(self, wx, wy):
        for node in reversed(self.store.all()):  # topmost (last drawn) first
            if node.x <= wx < node.x + node.w and node.y <= wy < node.y + node.h:
                return node
        return None

    # --------------------------------------------------------------- redraw
    def set_layout_frozen(self, frozen):
        self._layout_frozen = frozen
        if frozen:
            if self._view_job is not None:
                self.after_cancel(self._view_job)
                self._view_job = None
            self._view_needs_redraw = False

    def _on_configure(self, event=None):
        if _PERF:
            _P["resize_events"] += 1
        self._schedule_view_render(full=True)

    def _on_destroy(self, event):
        if event.widget is self and self._wire_style_job is not None:
            try:
                self.after_cancel(self._wire_style_job)
            except tk.TclError:
                pass
            self._wire_style_job = None
        if event.widget is self and self._view_job is not None:
            try:
                self.after_cancel(self._view_job)
            except tk.TclError:
                pass
            self._view_job = None
        if event.widget is self and self._drag_motion_job is not None:
            self.after_cancel(self._drag_motion_job)
            self._drag_motion_job = None
        if event.widget is self:
            self._clear_route_transitions()

    def _schedule_view_render(self, full=False):
        if self._layout_frozen:
            return
        self._view_needs_redraw |= full
        if self._view_job is None:
            self._view_job = self.after(16, self._flush_view_render)

    def _flush_view_render(self):
        self._view_job = None
        if self._view_needs_redraw or self.zoom != self._rendered_zoom:
            self._view_needs_redraw = False
            self._redraw()
        else:
            self._render_pan_frame()

    def _render_pan_frame(self):
        if _PERF:
            _P["viewport_frames"] += 1
            started = time.perf_counter()
        old_x, old_y = self._rendered_pan
        dx, dy = self.pan_x - old_x, self.pan_y - old_y
        if dx or dy:
            self.move("world", dx, dy)
        self._draw_grid(reposition=False)
        self._refresh_connection_drag()
        self.tag_lower("grid")
        self._rendered_pan = (self.pan_x, self.pan_y)
        if _PERF:
            _P["viewport_ms"] += (time.perf_counter() - started) * 1000.0

    def _redraw(self):
        self._clear_route_transitions()
        if self._view_job is not None:
            self.after_cancel(self._view_job)
            self._view_job = None
        self._view_needs_redraw = False
        if _PERF:
            _P["redraws"] += 1
            _t0 = time.perf_counter()
        camera_changed = ((self.pan_x, self.pan_y) != self._rendered_pan
                          or self.zoom != self._rendered_zoom)
        # Cards live as canvas windows and are only torn down when their
        # node leaves the store or changes type away from a card type
        # (type change / delete); existing grid, compact-node and card items
        # are repositioned or reused during ordinary viewport renders.
        self.delete("preview")
        self._draw_grid(reposition=camera_changed)
        self._draw_ai_region()
        nodes = self.store.all()
        live_compact = {node.id for node in nodes
                        if not is_card_type(node.type)}
        for nid, items in list(self._node_items.items()):
            if nid not in live_compact:
                for item in items:
                    self.delete(item)
                del self._node_items[nid]
        for node in nodes:
            if not is_card_type(node.type):
                self._draw_node(node)
        for node in nodes:
            if is_card_type(node.type):
                self._ensure_card(node)
        self._prune_cards()
        self._sync_connections()
        self._zoom_controls.tkraise()
        self.tag_lower("grid")
        self._update_zoom_label()
        self._rendered_pan = (self.pan_x, self.pan_y)
        self._rendered_zoom = self.zoom
        if _PERF:
            _P["redraw_ms"] += (time.perf_counter() - _t0) * 1000.0

    def _ensure_card(self, node):
        """Create the card window for a card-type node (TaskCard for task,
        InputCard for input) on first sight, then reposition it to the
        node's screen coords and refresh selection."""
        nid = node.id
        card_classes = {"task": TaskCard, "input": InputCard,
                        "context": ContextCard, "response": ResponseCard,
                        "plan": ExecutionCard, "action": ExecutionCard,
                        "evaluation": ExecutionCard}
        card_class = card_classes.get(node.type, UnknownCard)
        card = self._cards.get(nid)
        if card is None or not isinstance(card, card_class):
            if card is not None:
                self._teardown_card(nid)
            if _PERF:
                _P["card_creates"] += 1
            if node.type == "input":
                card = InputCard(
                    self, get_node=lambda nid=nid: self.store.get(nid),
                    header=node.header)
            elif node.type == "task":
                card = TaskCard(self, header=node.header,
                                get_node=lambda nid=nid: self.store.get(nid))
            elif node.type == "context":
                card = ContextCard(self, header=node.header,
                                   get_node=lambda nid=nid: self.store.get(nid))
            elif node.type == "response":
                for edge in self.store.connections():
                    if edge.target_node == nid and edge.target_port == "contract":
                        source = self.store.get(edge.source_node)
                        if source is not None and source.type == "task":
                            contract_format = str(
                                source.contract.get("format", "markdown")
                            ).casefold()
                            node.response_format = next(
                                (option for option in ResponseCard.FORMATS
                                 if option.casefold() == contract_format),
                                node.response_format)
                            node.response_styles = [
                                str(style).title()
                                for style in source.contract.get("style", [])]
                card = ResponseCard(self, header=node.header,
                                    get_node=lambda nid=nid: self.store.get(nid))
            elif node.type in ("plan", "action", "evaluation"):
                card = ExecutionCard(
                    self, get_node=lambda nid=nid: self.store.get(nid),
                    node_type=node.type, header=node.header)
            else:
                card = UnknownCard(
                    self, header=node.header,
                    get_node=lambda nid=nid: self.store.get(nid),
                    node_type=node.type, extra_props=node.extra_props)
            card.on_delete = lambda nid=nid: self._delete_node(nid)
            card.on_press = lambda xr, yr, state=0, nid=nid: (
                self._card_press(nid, xr, yr, state))
            card.on_motion = lambda xr, yr: self._card_motion(
                SimpleNamespace(x_root=xr, y_root=yr))
            card.on_release = lambda xr, yr: self._card_release(None)
            if node.type == "response":
                card.on_data_change = (
                    lambda nid=nid: self._response_contract_changed(nid))
            else:
                card.on_data_change = self._notify_flow_change
            # on_connect_press on every card whose layout has output
            # (right-docked) pins; all other pins are connection targets.
            if any(side == "r"
                   for _port, side, _y in theme.NODE_PINS.get(node.type, ())):
                card.on_connect_press = (
                    lambda port, xr, yr, nid=nid:
                    self._connection_press(nid, port, xr, yr))
            self._cards[nid] = card
            card_w, card_h = theme.NODE_DIMS.get(node.type, theme.UNKNOWN_DIMS)
            self._card_wins[nid] = self.create_window(
                0, 0, anchor="nw", width=card_w, height=card_h,
                window=card, tags=("world", f"card_{nid}"))
        card.set_header(node.header)
        if isinstance(card, ExecutionCard):
            card.set_execution_summary(node.description)
        if isinstance(card, ResponseCard):
            card.set_result_summary(node.result_summary)
        sx, sy = self.world_to_screen(node.x, node.y)
        # Integer pixels: Tk snaps embedded windows to the pixel grid, so
        # fractional placement would misalign the card's stroke vs widget.
        self.coords(self._card_wins[nid], round(sx), round(sy))
        # Uniform zoom: the window item stretches with zoom and the card
        # recomputes content coords in place (no-op when zoom is
        # unchanged). The +1px gives the 1px body outline room for its
        # outer half when the rounded edge lands on the last pixel row/col.
        card_w, card_h = node.w, node.h
        self.itemconfig(self._card_wins[nid],
                        width=round(card_w * self.zoom) + 1,
                        height=round(card_h * self.zoom) + 1)
        if _PERF:
            _zb = card._zoom
        card.apply_zoom(self.zoom)
        if isinstance(card, InputCard):
            card._refresh_path()
        elif isinstance(card, ContextCard):
            card._refresh_files()
        if _PERF and card._zoom != _zb:
            _P["card_zoom_updates"] += 1
        card.set_selected(self.store.is_selected(node.id))

    def _prune_cards(self):
        """Destroy card windows whose node is gone or no longer a card type
        (deleted, or changed type away from task/input during _redraw)."""
        for nid, _card in list(self._cards.items()):
            node = self.store.get(nid)
            if node is None or not is_card_type(node.type):
                self._teardown_card(nid)

    def _teardown_card(self, nid):
        """Remove a card node's window and widget. Safe if already gone."""
        if self._drag_from_card and self._drag == nid:
            self.unbind_all("<Motion>")
            self.unbind_all("<ButtonRelease-1>")
            self._drag = None
            self._drag_from_card = False
        win = self._card_wins.pop(nid, None)
        if win is not None:
            try:
                self.delete(win)
            except tk.TclError:
                pass
        card = self._cards.pop(nid, None)
        if card is not None:
            try:
                card.destroy()
            except tk.TclError:
                pass

    def _rounded_rect(self, x, y, w, h, r):
        """Polygon points for a smooth (rounded) rectangle of size w x h."""
        r = max(0.0, min(r, w / 2, h / 2))
        return [
            x + r, y,
            x + w - r, y,
            x + w, y,
            x + w, y + r,
            x + w, y + h - r,
            x + w, y + h,
            x + w - r, y + h,
            x + r, y + h,
            x, y + h,
            x, y + h - r,
            x, y + r,
            x, y,
        ]

    def _draw_grid(self, reposition=True):
        if _PERF:
            _g0 = time.perf_counter()
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw < 2 or ch < 2:
            return
        world_step = grid_step(theme.GRID_STEP, self.zoom)
        half = theme.GRID_MARK
        imin = math.floor((0 - self.pan_x) / self.zoom / world_step) - 1
        imax = math.ceil((cw - self.pan_x) / self.zoom / world_step) + 1
        jmin = math.floor((0 - self.pan_y) / self.zoom / world_step) - 1
        jmax = math.ceil((ch - self.pan_y) / self.zoom / world_step) + 1
        for i, j in list(self._grid_items):
            if not (imin <= i <= imax and jmin <= j <= jmax):
                self.delete(self._grid_items.pop((i, j)))
        for j in range(jmin, jmax + 1):
            sy = j * world_step * self.zoom + self.pan_y
            for i in range(imin, imax + 1):
                sx = i * world_step * self.zoom + self.pan_x
                item = self._grid_items.get((i, j))
                if item is None:
                    item = self.create_rectangle(
                        sx - half, sy - half, sx + half, sy + half,
                        fill=theme.GRID, outline="", tags=("grid", "world"))
                    self._grid_items[(i, j)] = item
                    if _PERF:
                        _P["grid_items"] += 1
                elif reposition:
                    self.coords(item, sx - half, sy - half,
                                sx + half, sy + half)
                    if _PERF:
                        _P["grid_reuses"] += 1
                elif _PERF:
                    _P["grid_reuses"] += 1
        if _PERF:
            _P["grid_ms"] += (time.perf_counter() - _g0) * 1000.0

    def _region_font_at_zoom(self):
        if self._region_font is None:
            base = tkfont.Font(font=theme.FONT_SMALL)
            self._region_font_size = base.actual("size")
            self._region_font = tkfont.Font(
                family=base.actual("family"), size=self._region_font_size)
            self._region_font_zoom = 1.0
        if self._region_font_zoom != self.zoom:
            self._region_font.configure(
                size=max(1, round(self._region_font_size * self.zoom)))
            self._region_font_zoom = self.zoom
        return self._region_font

    def _draw_ai_region(self):
        """Draw a separate backdrop for each Task's execution trace.

        Generated nodes carry their owning Task ID, so attempts and stages
        stay together without relying on node IDs or their current position.
        Unassociated AI nodes (possible in hand-built debug graphs) share a
        fallback group. Regions are decorative and stay below graph content.
        """
        groups = {}
        for node in self.store.all():
            if node.type not in ("plan", "action", "evaluation"):
                continue
            groups.setdefault(node.execution_task_id, []).append(node)

        for task_id in self._ai_regions_by_task.keys() - groups.keys():
            region, label = self._ai_regions_by_task.pop(task_id)
            self.delete(region)
            self.delete(label)

        pad = theme.AI_REGION_PADDING
        for task_id, ai_nodes in groups.items():
            min_x = min(node.x for node in ai_nodes) - pad
            min_y = min(node.y for node in ai_nodes) - pad
            max_x = max(node.x + node.w for node in ai_nodes) + pad
            max_y = max(node.y + node.h for node in ai_nodes) + pad
            x1, y1 = self.world_to_screen(min_x, min_y)
            x2, y2 = self.world_to_screen(max_x, max_y)
            task = self.store.get(task_id) if task_id is not None else None
            trace = self.store.execution_traces.get(
                str(task_id), self.store.execution_traces.get(task_id, {}))
            trace_header = trace.get("header") if isinstance(trace, dict) else None
            if isinstance(trace_header, str) and trace_header.strip():
                title = trace_header.strip()
            elif task is not None:
                title = task.header.strip()
            else:
                title = ""
            region_title = (f"AI EXECUTION · {title}" if title
                            else "AI EXECUTION")
            region_title += " · READ ONLY"
            title_x = x1 + max(2, round(8 * self.zoom))
            title_y = y1 + max(1, round(4 * self.zoom))
            items = self._ai_regions_by_task.get(task_id)
            if items is None:
                region = self.create_polygon(
                    *self._rounded_rect(x1, y1, x2 - x1, y2 - y1,
                                        14 * self.zoom),
                    fill=theme.AI_REGION_FILL, outline=theme.AI_REGION_BORDER,
                    width=max(1, round(self.zoom)), state="normal",
                    tags=("ai_region", "region", "world"))
                label = self.create_text(
                    title_x, title_y, anchor="nw", text=region_title,
                    font=self._region_font_at_zoom(), fill=theme.TEXT_MUTED,
                    tags=("ai_region", "region", "world"))
                items = (region, label)
                self._ai_regions_by_task[task_id] = items
            else:
                region, label = items
                self.coords(label, title_x, title_y)
                self.itemconfigure(label, text=region_title,
                                   font=self._region_font_at_zoom())
                self.coords(
                    region,
                    *self._rounded_rect(x1, y1, x2 - x1, y2 - y1,
                                        14 * self.zoom))
                self.itemconfigure(region, width=max(1, round(self.zoom)))

        # Preserve the old singleton handle for integrations/tests that use
        # it to inspect one AI region; multiple Task groups use the map above.
        if len(self._ai_regions_by_task) == 1:
            self._ai_region_items = list(
                next(iter(self._ai_regions_by_task.values())))
        else:
            self._ai_region_items = []
        self.tag_lower("region")
        for region, label in self._ai_regions_by_task.values():
            self.tag_raise(label, region)

    def _node_font_at_zoom(self):
        """Scaled compact-node label font; size rebuilt only when zoom changes."""
        if self._node_font_zoom != self.zoom:
            self._node_font.configure(
                size=max(1, round(self._node_font_size * self.zoom)))
            self._node_font_zoom = self.zoom
        return self._node_font

    def _draw_node(self, node):
        info = theme.NODE_TYPES.get(node.type,
                                    {"accent": theme.UNKNOWN_ACCENT})
        selected = self.store.is_selected(node.id)
        x, y = self.world_to_screen(node.x, node.y)
        w, h = node.w * self.zoom, node.h * self.zoom
        tag = ("node", "world", f"node_{node.id}")
        radius = min(theme.NODE_RADIUS * self.zoom, h / 2)

        # One equal box for every node. Resting: fill ~10% lighter than the
        # canvas bg with a thin ~20%-lighter outline. Selected: the fill
        # stays original, only the border line color brightens to the node's
        # accent (thinner line than before, halved from 4px to 2px).
        outline = info["accent"] if selected else theme.NODE_BORDER_NORMAL
        width = max(1, round((2 if selected else 1) * self.zoom))

        # modest drop shadow, painted just behind the node body
        sd, sy = 2.0, 3.0
        ids = self._node_items.get(node.id)
        shadow_coords = self._rounded_rect(x + sd, y + sy, w, h, radius)
        frame_coords = self._rounded_rect(x, y, w, h, radius)
        label_coords = (x + w / 2, y + h / 2)
        if ids is None:
            shadow = self.create_polygon(
                shadow_coords, smooth=True, fill=theme.NODE_SHADOW,
                outline="", tags=tag)
            frame = self.create_polygon(
                frame_coords, smooth=True, fill=theme.NODE_FILL_NORMAL,
                outline=outline, width=width,
                tags=tag + (f"frame_{node.id}",))
            label = self.create_text(
                *label_coords, text=node.label, fill=theme.TEXT,
                font=self._node_font_at_zoom(),
                tags=tag + (f"label_{node.id}",))
            self._node_items[node.id] = (shadow, frame, label)
            if _PERF:
                _P["node_items"] += 3
        else:
            shadow, frame, label = ids
            self.coords(shadow, *shadow_coords)
            self.coords(frame, *frame_coords)
            self.coords(label, *label_coords)
            self.itemconfigure(frame, outline=outline, width=width)
            self.itemconfigure(label, text=node.label,
                               font=self._node_font_at_zoom())
            if _PERF:
                _P["node_item_updates"] += 3

    # -------------------------------------------------------- node drag/select
    def _node_id_at_current(self):
        for item in self.find_withtag("current"):
            for tag in self.gettags(item):
                if tag.startswith("node_"):
                    return int(tag[len("node_"):])
                if tag.startswith("card_"):
                    return int(tag[len("card_"):])
        return None

    def _style_node(self, node):
        if is_card_type(node.type):
            return  # card nodes are windows; selection is handled there
        info = theme.NODE_TYPES.get(node.type,
                                    {"accent": theme.UNKNOWN_ACCENT})
        if self.store.is_selected(node.id):
            self.itemconfig(f"frame_{node.id}",
                            outline=info["accent"],
                            width=max(1, round(2 * self.zoom)))
        else:
            self.itemconfig(f"frame_{node.id}",
                            outline=theme.NODE_BORDER_NORMAL,
                            width=max(1, round(1 * self.zoom)))

    def _apply_selection(self):
        """Restyle every node so every selected box shows the selected look."""
        for node in self.store.all():
            self._style_node(node)
        for nid, card in self._cards.items():
            node = self.store.get(nid)
            card.set_selected(node is not None and self.store.is_selected(node.id))

    # ---------------------------------------------------------- connections
    def _connection_world_point(self, node_id, port):
        node = self.store.get(node_id)
        if node is None:
            return None
        pins = theme.NODE_PINS.get(node.type)
        if not pins:
            return None
        for pin_port, side, y in pins:
            if pin_port == port:
                if side == "r":
                    return node.x + node.w - 15.5, node.y + y
                return node.x + 15.5, node.y + y
        return None

    def _connection_screen_point(self, node_id, port):
        point = self._connection_world_point(node_id, port)
        return None if point is None else self.world_to_screen(*point)

    def _connection_target_at(self, source, sx, sy):
        radius = max(10.0, 12.0 * self.zoom)
        radius_sq = radius * radius
        source_node = self.store.get(source[0])
        if source_node is None or source_node.read_only:
            return None
        candidates = connections.endpoints_for(source_node.type, source[1])
        if not candidates:
            # Wire originates on an unsupported source (incl. unknown-type
            # nodes): no valid drop targets.
            return None
        best = None
        best_dist = float("inf")
        for node in reversed(self.store.all()):
            if node.id == source[0] or node.system_generated or node.read_only:
                continue
            for target_type, target_port in candidates:
                if node.type != target_type or not self.store.can_connect(
                        source[0], source[1], node.id, target_port):
                    continue
                point = self._connection_world_point(node.id, target_port)
                if point is None:
                    continue
                x, y = self.world_to_screen(*point)
                dist = (sx - x) ** 2 + (sy - y) ** 2
                if dist < best_dist and dist <= radius_sq:
                    best_dist = dist
                    best = node.id, target_port
        return best

    def _set_connection_target(self, target):
        if target == self._connection_target:
            return
        self._connection_target = target
        self._refresh_connection_pin_styles()

    def _connection_press(self, node_id, port, x_root, y_root):
        node = self.store.get(node_id)
        if node is not None and (node.system_generated or node.read_only):
            self._notify_ai_node_interaction()
            return
        if self._connection_drag is not None:
            if self._connection_drag == (node_id, port):
                self._cancel_connection()
                return
            if (node is not None
                    and self._connection_drag[0] == node_id
                    and not node.system_generated
                    and not node.read_only
                    and connections.is_user_endpoint(node.type, port)):
                self._cancel_connection()
            elif ((node_id, port) in self._connection_compatible_targets
                  and self.store.can_connect(
                      *self._connection_drag, node_id, port)):
                self._commit_connection((node_id, port))
                return
            else:
                return
        drag_allowed = (node is not None and not node.system_generated
                        and not node.read_only
                        and connections.is_user_endpoint(node.type, port))
        if node is None or not drag_allowed:
            return
        start = self._connection_screen_point(node_id, port)
        if start is None:
            return
        self._connection_drag = (node_id, port)
        self._wire_hover_leave()
        self._select_connection(None)
        self._refresh_connection_candidates()
        self._connection_cursor = (x_root - self.winfo_rootx(),
                                   y_root - self.winfo_rooty())
        wire_color, wire_width, wire_dash = self._wire_values(
            node.type, port)
        control_pin = node.type == "task" and port in ("next", "after")
        self._connection_line = self.create_line(
            *self._wire_coords(start, self._connection_cursor, node),
            fill=wire_color, width=wire_width, dash=wire_dash or "",
            arrow=tk.NONE if control_pin else tk.LAST,
            tags="connection_drag")
        self.bind_all("<Motion>", self._connection_motion)
        self.bind_all("<ButtonRelease-1>", self._connection_release)
        self._animate_wire_styles()
        self._connection_motion(SimpleNamespace(
            x_root=x_root, y_root=y_root))

    def _connection_motion(self, event):
        if self._connection_drag is None:
            return
        source_node, source_port = self._connection_drag
        start = self._connection_screen_point(source_node, source_port)
        if start is None:
            self._cancel_connection()
            return
        self._connection_cursor = (
            event.x_root - self.winfo_rootx(),
            event.y_root - self.winfo_rooty())
        target = self._connection_target_at(
            self._connection_drag, *self._connection_cursor)
        self._set_connection_target(target)
        preview = self._connection_preview_points()
        if preview is None:
            self._cancel_connection()
            return
        start, end, source, target_node_obj, source_port, target_port = preview
        self.coords(self._connection_line, *self._wire_coords(
            start, end, source, target_node_obj))
        wire_color, wire_width, wire_dash = self._wire_values(
            source.type, source_port,
            target_node_obj.type if target_node_obj is not None else None,
            target_port)
        self.itemconfigure(
            self._connection_line, fill=wire_color, width=wire_width,
            dash=wire_dash or "",
            arrow=(tk.NONE if source.type == "task"
                   and source_port in ("next", "after") else tk.LAST))

    def _connection_preview_points(self):
        if self._connection_drag is None:
            return None
        first_node, first_port = self._connection_drag
        first = self._connection_screen_point(first_node, first_port)
        if first is None:
            return None
        target = self._connection_target
        if target is None:
            return (first, self._connection_cursor,
                    self.store.get(first_node), None, first_port, None)
        second_node, second_port = target
        second = self._connection_screen_point(second_node, second_port)
        a, b = self.store.get(first_node), self.store.get(second_node)
        if second is None or a is None or b is None:
            return first, self._connection_cursor, a, None, first_port, None
        canonical = connections.canonical_user_edge(
            a.type, first_port, b.type, second_port)
        if canonical == (a.type, first_port, b.type, second_port):
            return first, second, a, b, first_port, second_port
        return second, first, b, a, second_port, first_port

    def _refresh_connection_candidates(self):
        self._connection_compatible_targets = set()
        if self._connection_drag is not None:
            source_id, source_port = self._connection_drag
            source = self.store.get(source_id)
            if source is None or source.system_generated or source.read_only:
                self._cancel_connection()
                return
            candidates = connections.endpoints_for(source.type, source_port)
            for node in self.store.all():
                if (node.id == source_id or node.system_generated
                        or node.read_only):
                    continue
                for target_type, target_port in candidates:
                    if (node.type == target_type
                            and self.store.can_connect(
                                source_id, source_port,
                                node.id, target_port)):
                        self._connection_compatible_targets.add(
                            (node.id, target_port))
        if (self._connection_target is not None
                and self._connection_target
                not in self._connection_compatible_targets):
            self._set_connection_target(None)
        self._refresh_connection_pin_styles()

    def _refresh_connection_pin_styles(self):
        connected = set()
        for edge in self.store.connections():
            connected.add((edge.source_node, edge.source_port))
            connected.add((edge.target_node, edge.target_port))
        active = self._connection_drag
        for node_id, card in self._cards.items():
            node = self.store.get(node_id)
            if node is None:
                continue
            for port, _side, _y in theme.NODE_PINS.get(node.type, ()):
                state = "normal"
                if active is not None:
                    pin = (node_id, port)
                    if pin == active:
                        state = "active"
                    elif pin == self._connection_target:
                        state = "hover"
                    elif pin in self._connection_compatible_targets:
                        state = "compatible"
                    else:
                        state = "dim"
                self._set_pin_interaction_style(
                    card, node, port, state, (node_id, port) in connected)

    @staticmethod
    def _set_pin_interaction_style(card, node, port, state, connected):
        dots = getattr(card, "_port_dots", {})
        dot = dots.get(port)
        if dot is None and port in ("data", "context"):
            dot = (getattr(card, "_pin_dot", None)
                   or getattr(card, "_output_dot", None))
        if dot is None:
            return
        semantic = theme.PORT_SEMANTICS.get((node.type, port))
        if semantic is None:
            return
        color = theme.SEMANTIC_COLORS[semantic]
        highlighted = state in ("compatible", "active", "hover")
        if hasattr(card, "_port_highlights"):
            card._port_highlights[port] = highlighted
        if port == "data" and hasattr(card, "_input_highlighted"):
            card._input_highlighted = highlighted
        if port == "data" and hasattr(card, "_output_highlighted"):
            card._output_highlighted = highlighted
        outline = {
            "normal": color,
            "compatible": color,
            "active": theme.WIRE_HOVER,
            "hover": theme.WIRE_HOVER,
            "dim": theme.WIRE_DIM,
        }[state]
        width = {"normal": 1.5, "compatible": 2.5,
                 "active": 3.0, "hover": 3.0, "dim": 1.0}[state]
        card.itemconfigure(dot, fill=color if connected else "",
                           outline=outline, width=max(1, round(width * card._zoom)))

    def _connection_release(self, event):
        if self._connection_drag is None:
            return
        self._connection_motion(event)
        if self._connection_drag is None:
            return
        target = self._connection_target
        if target is not None:
            self._commit_connection(target)
            return
        start = self._connection_screen_point(*self._connection_drag)
        point = (event.x_root - self.winfo_rootx(),
                 event.y_root - self.winfo_rooty())
        if start is not None and math.dist(start, point) <= max(12, 14 * self.zoom):
            # A click on the source selects it; the user can now choose any
            # compatible pin. Motion remains bound for the preview wire.
            self.unbind_all("<ButtonRelease-1>")
            self._connection_cursor = start
            self._set_connection_target(None)
            self._refresh_connection_pin_styles()
            self._animate_wire_styles()
            return
        self._cancel_connection()

    def _commit_connection(self, target):
        if self._connection_drag is None:
            return False
        source_node, source_port = self._connection_drag
        if not self.store.can_connect(source_node, source_port, *target):
            return False
        connection = self.store.connect(source_node, source_port, *target)
        if connection is None:
            return False
        self._cancel_connection()
        self._render_connection(connection)
        self._select_connection(None)
        self._routes_need_settle = True
        self._routes_to_settle.add(connection)
        self._settle_wire_routes()
        self._sync_port_colors()
        self._notify_flow_change()
        return True

    def _escape_connection_selection(self, _event=None):
        if self._connection_drag is None:
            return
        self._cancel_connection()
        return "break"

    def _cancel_connection(self):
        self.unbind_all("<Motion>")
        self.unbind_all("<ButtonRelease-1>")
        if self._connection_line is not None:
            self.delete(self._connection_line)
        self._connection_line = None
        self._connection_drag = None
        self._connection_cursor = None
        self._connection_compatible_targets = set()
        self._set_connection_target(None)
        self._refresh_connection_pin_styles()
        self._refresh_highlighted_wire_ports()
        self._animate_wire_styles()

    def _show_connection_reason(self, source_node, source_port,
                                target_node, target_port):
        """Transient label at the dropped target explaining why an edge was
        rejected (illegal pairing or a bad port name); hides after 2.5s."""
        end = self._connection_screen_point(target_node, target_port)
        if end is None:
            return
        message = self.store.connect_reason(
            source_node, source_port, target_node, target_port)
        if not message:
            return
        for item in self._connection_reason_items:
            self.delete(item)
        self._connection_reason_items = [self.create_text(
            end[0], end[1] - 12, text=message, anchor="s",
            font=self._region_font_at_zoom(), fill=theme.WIRE_HOVER,
            tags=("connection_reason", "world"))]
        self.after(2500, self._hide_connection_reason)

    def _hide_connection_reason(self):
        items, self._connection_reason_items = (
            self._connection_reason_items, [])
        try:
            for item in items:
                self.delete(item)
        except tk.TclError:
            pass

    def _wire_values(self, source_type, source_port, target_type=None,
                     target_port=None):
        """(fill, width, dash) for an edge: user edges take the source
        accent solid at 2, entry/return edges AI_ACCENT solid at 3, exec
        edges AI_ACCENT dashed at 2. Preview (no target yet) uses the source
        accent solid 2; illegal pairings fall back to NODE_BORDER_NORMAL
        (the old invalid-edge gray)."""
        info = theme.NODE_TYPES.get(source_type,
                                    {"accent": theme.UNKNOWN_ACCENT})
        if source_type == "task" and source_port in ("next", "after"):
            return theme.CONTROL_COLOR, 2, (5, 3)
        if target_type is None:
            return info["accent"], 2, ""
        kind = connections.kind_of(source_type, source_port,
                                   target_type, target_port)
        if kind == "CONTROL":
            return theme.CONTROL_COLOR, 2, (5, 3)
        if kind == "DATA":
            semantic = theme.PORT_SEMANTICS.get((source_type, source_port), "ai")
            return theme.SEMANTIC_COLORS[semantic], 2, ""
        return theme.NODE_BORDER_NORMAL, 2, ""

    def _wire_base_width(self, connection):
        """Un-emphasized width for a connection: entry/return stay at 3 so
        the hover emphasis bumps to 4 instead of flattening back to 2."""
        source = self.store.get(connection.source_node)
        target = self.store.get(connection.target_node)
        if source is None or target is None:
            return 2
        return 2

    def _render_connection(self, connection, force_route=False, preview=False):
        source = self.store.get(connection.source_node)
        target = self.store.get(connection.target_node)
        start = self._connection_world_point(
            connection.source_node, connection.source_port)
        end = self._connection_world_point(
            connection.target_node, connection.target_port)
        if source is None or target is None or start is None or end is None:
            return
        signature = (start, end, source.x, source.y, target.x, target.y)
        cached = self._connection_paths.get(connection)
        if force_route or cached is None or cached[1] != signature:
            path = self._route_wire(start, end, source, target, connection,
                                    preview=preview)
            self._connection_paths[connection] = (
                self._routing_revision, signature, path,
                FlowCanvas._path_bounds(path))
        else:
            path = cached[2]
        coords = [value for point in path
                  for value in self.world_to_screen(*point)]
        item = self._connection_items.get(connection)
        color, width, dash = self._wire_values(
            source.type, connection.source_port,
            target.type, connection.target_port)
        if item is None:
            tag = (f"connection_{connection.source_node}_"
                   f"{connection.target_node}")
            halo = self.create_line(
                *coords, fill=color, width=6, stipple="gray50",
                capstyle=tk.ROUND, joinstyle=tk.ROUND,
                state="hidden", tags=("connection_halo", "world", tag))
            item = self.create_line(
                *coords, fill=color, width=width, dash=dash or "",
                arrow=tk.LAST if connection.type != "CONTROL" else tk.NONE,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags=("connection", "world", tag))
            self._connection_items[connection] = item
            self._connection_halos[connection] = halo
        else:
            self.coords(item, *coords)
            self.itemconfigure(item, fill=color, width=width,
                               dash=dash or "")
            halo = self._connection_halos.get(connection)
            if halo is not None:
                self.coords(halo, *coords)
                self.itemconfigure(halo, fill=color)

    def _wire_hover_motion(self, event):
        if self._connection_drag is not None or self._drag is not None:
            return
        connection, _distance = self._wire_nearest(event.x, event.y)
        if connection == self._hovered_connection:
            return
        self._hovered_connection = connection
        self.configure(cursor="hand2" if connection is not None else "")
        self._refresh_highlighted_wire_ports()
        self._animate_wire_styles()

    def _wire_hover_leave(self, _event=None):
        if self._hovered_connection is None:
            return
        self._hovered_connection = None
        self.configure(cursor="")
        self._refresh_highlighted_wire_ports()
        self._animate_wire_styles()

    def _wire_nearest(self, sx, sy):
        best = None
        wx, wy = self.screen_to_world(sx, sy)
        radius = 8.0 / self.zoom
        for connection, cached in self._connection_paths.items():
            path = cached[2]
            bounds = (cached[3] if len(cached) > 3
                      else FlowCanvas._path_bounds(path))
            if (wx < bounds[0] - radius or wx > bounds[2] + radius
                    or wy < bounds[1] - radius or wy > bounds[3] + radius):
                continue
            screen_path = [self.world_to_screen(*point) for point in path]
            if (not screen_path
                    or sx < min(p[0] for p in screen_path) - 8
                    or sx > max(p[0] for p in screen_path) + 8
                    or sy < min(p[1] for p in screen_path) - 8
                    or sy > max(p[1] for p in screen_path) + 8):
                continue
            distance = min(
                self._point_segment_distance(sx, sy, a, b)
                for a, b in zip(screen_path, screen_path[1:])
            ) if len(screen_path) > 1 else math.inf
            if distance > 8.0:
                continue
            tie_preference = (connection == self._hovered_connection
                              or connection == self._selected_connection)
            candidate = (distance, not tie_preference,
                         connection.source_node, connection.target_node,
                         connection)
            if best is None or candidate[:4] < best[:4]:
                best = candidate
        return (None, math.inf) if best is None else (best[4], best[0])

    @staticmethod
    def _point_segment_distance(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        if not length_sq:
            return math.hypot(px - a[0], py - a[1])
        t = max(0.0, min(1.0,
                         ((px - a[0]) * dx + (py - a[1]) * dy)
                         / length_sq))
        return math.hypot(px - (a[0] + t * dx),
                          py - (a[1] + t * dy))

    def _select_connection(self, connection):
        if self._selected_connection == connection:
            return
        self._selected_connection = connection
        self._refresh_highlighted_wire_ports()
        self._animate_wire_styles()

    def _refresh_highlighted_wire_ports(self):
        highlighted = set()
        for connection in (self._hovered_connection,
                           self._selected_connection):
            if connection is not None:
                highlighted.add((connection.source_node,
                                 connection.source_port))
                highlighted.add((connection.target_node,
                                 connection.target_port))
        for node_id, port in self._highlighted_wire_ports - highlighted:
            self._set_card_port_highlight(node_id, port, False)
        for node_id, port in highlighted - self._highlighted_wire_ports:
            self._set_card_port_highlight(node_id, port, True)
        self._highlighted_wire_ports = highlighted

    def _set_card_port_highlight(self, node_id, port, highlighted):
        card = self._cards.get(node_id)
        if card is None:
            return
        if hasattr(card, "set_port_highlight"):
            card.set_port_highlight(port, highlighted, theme.WIRE_HOVER)
        elif port in ("data", "context"):
            if hasattr(card, "set_output_highlight"):
                card.set_output_highlight(highlighted, theme.WIRE_HOVER)
        elif port == "data" and hasattr(card, "set_input_highlight"):
            card.set_input_highlight(highlighted, theme.WIRE_HOVER)

    def _animate_wire_styles(self):
        target = frozenset(
            connection for connection in self._connection_items
            if (connection == self._hovered_connection
                or connection == self._selected_connection))
        if self._wire_style_job is not None:
            self.after_cancel(self._wire_style_job)
            self._wire_style_job = None
        self._wire_style_target = target
        transitions = []
        for connection, line in self._connection_items.items():
            halo = self._connection_halos.get(connection)
            emphasized = (connection == self._hovered_connection
                          or connection == self._selected_connection)
            base = self._wire_base_width(connection)
            line_start = float(self.itemcget(line, "width"))
            halo_visible = (halo is not None
                            and self.itemcget(halo, "state") != "hidden")
            halo_start = (float(self.itemcget(halo, "width"))
                          if halo_visible else 0.0)
            line_end = base + 1 if emphasized else base
            halo_end = 6.0 if emphasized else 0.0
            source = self.store.get(connection.source_node)
            target_node = self.store.get(connection.target_node)
            base_color = self._wire_values(
                source.type, connection.source_port,
                target_node.type, connection.target_port)[0]
            color_start = str(self.itemcget(line, "fill"))
            color_end = (theme.WIRE_DIM
                         if self._connection_drag is not None and not emphasized
                         else (base_color if emphasized or not target
                               else theme.WIRE_DIM))
            if (abs(line_start - line_end) < 0.05
                    and ((halo_end > 0) == halo_visible)
                    and (halo is None or abs(halo_start - halo_end) < 0.05)
                    and color_start == color_end):
                continue
            if color_start != color_end:
                self.itemconfigure(line, fill=color_end)
            transitions.append((line, halo, line_start, halo_start,
                                line_end, halo_end))
        if transitions:
            self._wire_style_animation = transitions
            self._wire_style_job = self.after(16, self._step_wire_styles, 1)

    def _step_wire_styles(self, frame):
        self._wire_style_job = None
        amount = min(1.0, frame / 4)
        live_items = set(self._connection_items.values())
        for line, halo, line_start, halo_start, line_end, halo_end in (
                self._wire_style_animation or ()):
            if line not in live_items:
                continue
            width = line_start + (line_end - line_start) * amount
            self.itemconfigure(line, width=width)
            if halo is not None:
                halo_width = halo_start + (halo_end - halo_start) * amount
                self.itemconfigure(
                    halo, width=halo_width,
                    state="normal" if halo_end or frame < 4 else "hidden")
        if frame < 4:
            self._wire_style_job = self.after(
                16, self._step_wire_styles, frame + 1)
        else:
            self._wire_style_animation = None

    def _wire_coords(self, start, end, source_node=None, target_node=None):
        """Return a screen-space path for a temporary dragged connection."""
        world_start = self.screen_to_world(*start)
        world_end = self.screen_to_world(*end)
        path = self._route_wire(world_start, world_end,
                                source_node, target_node)
        return [value for point in path
                for value in self.world_to_screen(*point)]

    def _route_wire(self, start, end, source_node=None, target_node=None,
                    connection=None, preview=False):
        """Route from exact pin anchors around cards and existing wires."""
        if source_node is None or target_node is None:
            return [start, end]

        source_direction = self._pin_outward_direction(
            source_node, connection.source_port if connection else None,
            start)
        target_direction = self._pin_outward_direction(
            target_node, connection.target_port if connection else None,
            end)
        lead = 36.0
        clearance = theme.WIRE_CARD_CLEARANCE
        nodes = self.store.all()
        scene_obstacles = [
            (node.x - clearance, node.y - clearance,
             node.x + node.w + clearance, node.y + node.h + clearance)
            for node in nodes
            if node.id not in (source_node.id, target_node.id)]
        endpoint_groups = {
            node.execution_task_id for node in (source_node, target_node)
            if node.system_generated
        }
        region_obstacles = [
            (bounds[0] - theme.WIRE_REGION_CLEARANCE,
             bounds[1] - theme.WIRE_REGION_CLEARANCE,
             bounds[2] + theme.WIRE_REGION_CLEARANCE,
             bounds[3] + theme.WIRE_REGION_CLEARANCE)
            for task_id, bounds in _execution_region_bounds(nodes)
            if task_id not in endpoint_groups
        ]
        route_obstacles = [*scene_obstacles, *region_obstacles]

        def clear_stub(anchor, direction):
            for distance in (lead, 24.0, 12.0, 0.0):
                point = (anchor[0] + direction[0] * distance,
                         anchor[1] + direction[1] * distance)
                if not self._path_hits_obstacles((anchor, point),
                                                 route_obstacles):
                    return point
            return anchor

        route_start = clear_stub(start, source_direction)
        route_end = clear_stub(end, target_direction)
        detour = max(240.0, min(400.0,
                                math.dist(route_start, route_end) * 0.15 + 180))
        corridor = (min(route_start[0], route_end[0]) - detour,
                    min(route_start[1], route_end[1]) - detour,
                    max(route_start[0], route_end[0]) + detour,
                    max(route_start[1], route_end[1]) + detour)
        obstacles = [
            box for box in route_obstacles
            if (box[0] <= corridor[2]
                and box[2] >= corridor[0]
                and box[1] <= corridor[3]
                and box[3] >= corridor[1])]
        other_paths = []
        other_path_bounds = {}
        if not preview:
            for other, cached in self._connection_paths.items():
                if other == connection:
                    continue
                x0, y0, x1, y1 = (cached[3] if len(cached) > 3
                                  else FlowCanvas._path_bounds(cached[2]))
                if (x1 >= corridor[0] and x0 <= corridor[2]
                        and y1 >= corridor[1] and y0 <= corridor[3]):
                    other_paths.append((other, cached[2]))
                    other_path_bounds[other] = (x0, y0, x1, y1)
        execution_wire = (connection is not None
                         and connection.ownership == "SYSTEM")
        execution_wire |= (source_node.system_generated
                           or target_node.system_generated)
        user_contract_wire = (
            connection is not None and connection.ownership == "USER"
            and source_node.type == "task"
            and connection.source_port == "contract"
            and target_node.type == "response"
            and connection.target_port == "contract"
            and any(node.system_generated for node in nodes))
        if user_contract_wire:
            # Keep the authored Contract branch below the Task. This leaves
            # the short gap above the Task available for its Task->Plan wire.
            lane_y = max(source_node.y + source_node.h,
                         target_node.y + target_node.h) + 32.0
            path = [start, route_start,
                    (route_start[0], lane_y), (route_end[0], lane_y),
                    route_end, end]
            if not self._path_obstacle_cost(path, route_obstacles):
                rounded = self._round_wire_path(path)
                if not self._path_obstacle_cost(rounded, route_obstacles):
                    return rounded
        if execution_wire:
            # Execution connections have a known two-lane shape. Try short
            # pin-to-pin corridors first so Task->Plan and Evaluation->Result
            # do not get routed around the AI region boundary.
            midline = (route_start[1] + route_end[1]) / 2
            lane_ys = {route_start[1], route_end[1], midline}
            x_min = min(route_start[0], route_end[0])
            x_max = max(route_start[0], route_end[0])
            relevant_obstacles = [
                box for box in obstacles
                if box[0] <= x_max + lead and box[2] >= x_min - lead]
            for _x0, y0, _x1, y1 in relevant_obstacles:
                lane_ys.update((y0 - 32.0, y1 + 32.0))
            paths = []
            for lane_y in lane_ys:
                paths.append([start, route_start,
                              (route_start[0], lane_y),
                              (route_end[0], lane_y), route_end, end])
            corridor_x = max(route_start[0], route_end[0]) + 16.0
            for x in (route_start[0], route_end[0],
                      (route_start[0] + route_end[0]) / 2, corridor_x):
                paths.append([start, route_start,
                              (x, route_start[1]), (x, route_end[1]),
                              route_end, end])
            other_bounds = [
                (other_edge, other,
                 (min(point[0] for point in other),
                  min(point[1] for point in other),
                  max(point[0] for point in other),
                  max(point[1] for point in other)))
                for other_edge, other in other_paths
            ]

            def overlaps(first, second, padding=0.0):
                return not (first[2] + padding < second[0]
                            or second[2] + padding < first[0]
                            or first[3] + padding < second[1]
                            or second[3] + padding < first[1])

            candidates = []
            for path in paths:
                compact = []
                for point in path:
                    if not compact or point != compact[-1]:
                        compact.append(point)
                if self._path_obstacle_cost(compact, route_obstacles):
                    continue
                length = sum(math.dist(first, second)
                             for first, second in zip(compact, compact[1:]))
                bounds = (min(point[0] for point in compact),
                          min(point[1] for point in compact),
                          max(point[0] for point in compact),
                          max(point[1] for point in compact))
                nearby_paths = [(other_edge, other, other_box)
                                for other_edge, other, other_box in other_bounds
                                if overlaps(bounds, other_box, 16.0)]
                crossings = sum(
                    self._paths_cross(
                        compact, other,
                        self._shared_wire_points(connection, other_edge))
                    for other_edge, other, other_box in nearby_paths
                    if overlaps(bounds, other_box))
                candidates.append((crossings, length, compact, nearby_paths))
            if candidates:
                fewest_crossings = min(item[0] for item in candidates)
                best = []
                for crossings, length, compact, nearby_paths in candidates:
                    if crossings != fewest_crossings:
                        continue
                    spacing = sum(self._wire_spacing_cost(
                        compact, other, connection, other_edge)
                        for other_edge, other, _bounds in nearby_paths)
                    best.append((length + spacing * 2, compact))
                rounded = self._round_wire_path(
                    min(best, key=lambda item: item[0])[1])
                if not self._path_obstacle_cost(rounded, route_obstacles):
                    return rounded
        lanes = {0.0, -32.0, 32.0, -72.0, 72.0, -112.0, 112.0}
        midline = (route_start[1] + route_end[1]) / 2
        for x0, y0, x1, y1 in obstacles:
            if x1 < min(route_start[0], route_end[0]) or x0 > max(
                    route_start[0], route_end[0]):
                continue
            # Leave room for the corner-rounding radius outside the padded
            # card obstacle, so smoothing cannot clip the card edge.
            for edge_y in (y0 - 32.0, y1 + 32.0):
                lane = round((edge_y - midline) / 0.75, 1)
                if abs(lane) <= 144.0:
                    lanes.add(lane)
        curve_candidates = []
        for lane in sorted(lanes, key=lambda value: (abs(value), value)):
            path = self._curve_wire_path(
                start, end, route_start, route_end,
                source_direction, target_direction, lane)
            obstacle_cost = self._path_obstacle_cost(path, route_obstacles)
            blocked = obstacle_cost > 0
            length = sum(math.dist(first, second)
                         for first, second in zip(path, path[1:]))
            if blocked:
                score = length + obstacle_cost + abs(lane) * 0.3
                curve_candidates.append((True, 0, score, path))
                continue
            path_bounds = FlowCanvas._path_bounds(path)
            nearby = [
                (other_edge, other, other_path_bounds[other_edge])
                for other_edge, other in other_paths
                if (path_bounds[0] <= other_path_bounds[other_edge][2] + 16.0
                    and path_bounds[2] >= other_path_bounds[other_edge][0] - 16.0
                    and path_bounds[1] <= other_path_bounds[other_edge][3] + 16.0
                    and path_bounds[3] >= other_path_bounds[other_edge][1] - 16.0)]
            crossings = sum(self._paths_cross(
                path, other, self._shared_wire_points(connection, other_edge))
                for other_edge, other, bounds in nearby
                if (path_bounds[0] <= bounds[2]
                    and path_bounds[2] >= bounds[0]
                    and path_bounds[1] <= bounds[3]
                    and path_bounds[3] >= bounds[1]))
            spacing = sum(self._wire_spacing_cost(
                path, other, connection, other_edge)
                for other_edge, other, _bounds in nearby)
            # Execution wires must be allowed to cross the AI region boundary
            # to reach their real pins.
            boundary = (0.0 if execution_wire
                        else FlowCanvas._ai_boundary_cost(self, path))
            score = (length + crossings * 2000 + spacing * 2
                     + abs(lane) * 0.3 + obstacle_cost + boundary * 8)
            curve_candidates.append((blocked, crossings, score, path))
        available = [candidate for candidate in curve_candidates
                     if not candidate[0] and not candidate[1]]
        if available:
            return min(available, key=lambda candidate: candidate[2])[3]

        routed = self._visibility_route(
            route_start, route_end, route_obstacles, (), connection,
            ignore_ai_boundary=execution_wire,
            region_obstacles=region_obstacles)
        alternatives = [] if routed is None else [routed]
        expanded_bounds = None
        if routed is None:
            left = min(route_start[0], route_end[0])
            right = max(route_start[0], route_end[0])
            blocking = [box for box in route_obstacles
                        if box[0] <= right and box[2] >= left]
            if blocking:
                margin = theme.WIRE_LOCAL_MARGIN_MIN
                expanded_bounds = (
                    min(left, *(box[0] for box in blocking)) - margin,
                    min(route_start[1], route_end[1],
                        *(box[1] for box in blocking)) - margin,
                    max(right, *(box[2] for box in blocking)) + margin,
                    max(route_start[1], route_end[1],
                        *(box[3] for box in blocking)) + margin,
                )
                routed = self._visibility_route(
                    route_start, route_end, route_obstacles, (), connection,
                    ignore_ai_boundary=execution_wire,
                    region_obstacles=region_obstacles,
                    search_bounds=expanded_bounds)
                if routed is not None:
                    alternatives.append(routed)
        if routed is None:
            card_interiors = [
                (node.x, node.y, node.x + node.w, node.y + node.h)
                for node in nodes
                if node.id not in (source_node.id, target_node.id)
            ]
            direct = self._visibility_route(
                start, end, card_interiors, (), connection,
                ignore_ai_boundary=True, search_bounds=expanded_bounds)
            if direct is not None:
                rounded = self._round_wire_path(direct)
                return (direct if self._path_hits_obstacles(
                    rounded, card_interiors) else rounded)
        if routed is None:
            # If node geometry makes an obstacle-free route impossible,
            # keep the least-obstructed curve that still accounts for wires.
            routed = min(curve_candidates, key=lambda candidate: candidate[2])[3]
            return routed
        ranked = []
        for candidate in alternatives:
            path = [start, *candidate, end]
            rounded = self._round_wire_path(path)
            rendered = (path if self._path_hits_obstacles(
                rounded, route_obstacles) else rounded)
            if self._path_hits_obstacles(rendered, route_obstacles):
                continue
            bounds = FlowCanvas._path_bounds(rendered)
            nearby = [
                (other_edge, other, other_path_bounds[other_edge])
                for other_edge, other in other_paths
                if (bounds[0] <= other_path_bounds[other_edge][2] + 16.0
                    and bounds[2] >= other_path_bounds[other_edge][0] - 16.0
                    and bounds[1] <= other_path_bounds[other_edge][3] + 16.0
                    and bounds[3] >= other_path_bounds[other_edge][1] - 16.0)]
            crossings = sum(self._paths_cross(
                rendered, other,
                self._shared_wire_points(connection, other_edge))
                for other_edge, other, other_bounds in nearby
                if (bounds[0] <= other_bounds[2]
                    and bounds[2] >= other_bounds[0]
                    and bounds[1] <= other_bounds[3]
                    and bounds[3] >= other_bounds[1]))
            spacing = sum(self._wire_spacing_cost(
                rendered, other, connection, other_edge)
                for other_edge, other, _bounds in nearby)
            score = (FlowCanvas._route_shape_cost(path)
                     + crossings * 240 + spacing * 1.5)
            ranked.append((score, rendered))
        return min(ranked, key=lambda item: item[0])[1]

    def _shared_wire_points(self, first, second):
        if first is None or second is None:
            return ()
        shared = []
        if (first.source_node == second.source_node
                and first.source_port == second.source_port):
            point = self._connection_world_point(first.source_node,
                                                 first.source_port)
            if point is not None:
                shared.append(point)
        if (first.target_node == second.target_node
                and first.target_port == second.target_port):
            point = self._connection_world_point(first.target_node,
                                                 first.target_port)
            if point is not None:
                shared.append(point)
        return tuple(shared)

    @staticmethod
    def _path_bounds(path):
        return (min(point[0] for point in path),
                min(point[1] for point in path),
                max(point[0] for point in path),
                max(point[1] for point in path))

    @staticmethod
    def _route_shape_cost(path):
        length = sum(math.dist(first, second)
                     for first, second in zip(path, path[1:]))
        direction = 1 if path[-1][0] >= path[0][0] else -1
        progress = [direction * (point[0] - path[0][0]) for point in path]
        overshoot = max(0.0, max(progress) - progress[-1])
        reversal = sum(max(0.0, first - second)
                       for first, second in zip(progress, progress[1:]))
        vectors = [(second[0] - first[0], second[1] - first[1])
                   for first, second in zip(path, path[1:])
                   if math.dist(first, second) > 1e-6]
        bends = sum(
            abs(first[0] * second[1] - first[1] * second[0]) > 1e-6
            or first[0] * second[0] + first[1] * second[1] < 0
            for first, second in zip(vectors, vectors[1:]))
        return length + overshoot * 12 + reversal * 8 + bends * 24

    @staticmethod
    def _path_obstacle_cost(path, obstacles):
        """Penalize each card touched, with extra cost for long intrusion."""
        cost = 0.0
        path_bounds = FlowCanvas._path_bounds(path)
        for box in obstacles:
            if (path_bounds[2] < box[0] or path_bounds[0] > box[2]
                    or path_bounds[3] < box[1] or path_bounds[1] > box[3]):
                continue
            inside = [math.dist(first, second)
                      for first, second in zip(path, path[1:])
                      if (min(first[0], second[0]) <= box[2]
                          and max(first[0], second[0]) >= box[0]
                          and min(first[1], second[1]) <= box[3]
                          and max(first[1], second[1]) >= box[1]
                          and FlowCanvas._segment_hits_rect(first, second, *box))]
            if inside:
                cost += 10000.0 + sum(inside) * 20.0
        return cost

    @staticmethod
    def _path_hits_obstacles(path, obstacles):
        for first, second in zip(path, path[1:]):
            left, right = sorted((first[0], second[0]))
            top, bottom = sorted((first[1], second[1]))
            for x0, y0, x1, y1 in obstacles:
                if (right < x0 or left > x1
                        or bottom < y0 or top > y1):
                    continue
                if FlowCanvas._segment_hits_rect(
                        first, second, x0, y0, x1, y1):
                    return True
        return False

    def _ai_boundary_cost(self, path):
        boundaries = [bounds for _task_id, bounds
                      in _execution_region_bounds(self.store.all())]
        if not boundaries:
            return 0.0
        cost = 0.0
        for first, second in zip(path, path[1:]):
            x0, y0 = first
            x1, y1 = second
            for boundary in boundaries:
                if abs(y1 - y0) < 1.0:
                    if min(abs(y0 - boundary[1]),
                           abs(y0 - boundary[3])) <= 6.0:
                        cost += max(0.0, min(max(x0, x1), boundary[2])
                                    - max(min(x0, x1), boundary[0]))
                elif abs(x1 - x0) < 1.0:
                    if min(abs(x0 - boundary[0]),
                           abs(x0 - boundary[2])) <= 6.0:
                        cost += max(0.0, min(max(y0, y1), boundary[3])
                                    - max(min(y0, y1), boundary[1]))
        return cost

    @staticmethod
    def _curve_wire_path(start, end, route_start, route_end,
                         source_direction, target_direction, lane):
        distance = math.dist(route_start, route_end)
        handle = min(120.0, max(28.0, distance * 0.32))
        first_control = (
            route_start[0] + source_direction[0] * handle,
            route_start[1] + source_direction[1] * handle + lane)
        second_control = (
            route_end[0] + target_direction[0] * handle,
            route_end[1] + target_direction[1] * handle + lane)
        path = [start]
        for step in range(25):
            t = step / 24
            inverse = 1 - t
            path.append((
                inverse ** 3 * route_start[0]
                + 3 * inverse ** 2 * t * first_control[0]
                + 3 * inverse * t ** 2 * second_control[0]
                + t ** 3 * route_end[0],
                inverse ** 3 * route_start[1]
                + 3 * inverse ** 2 * t * first_control[1]
                + 3 * inverse * t ** 2 * second_control[1]
                + t ** 3 * route_end[1]))
        path.append(end)
        return path

    @staticmethod
    def _pin_outward_direction(node, port, point):
        pins = theme.NODE_PINS.get(node.type, ())
        side = next((side for candidate, side, _y in pins
                     if candidate == port), None)
        if side is None:
            side = "r" if point[0] >= node.x + node.w / 2 else "l"
        return (1.0, 0.0) if side == "r" else (-1.0, 0.0)

    @staticmethod
    def _round_wire_path(points, radius=10.0):
        """Round visibility-route corners while preserving both pin anchors."""
        if len(points) < 3:
            return points
        result = [points[0]]
        for previous, corner, following in zip(
                points, points[1:], points[2:]):
            incoming = math.dist(previous, corner)
            outgoing = math.dist(corner, following)
            if incoming < 1e-6 or outgoing < 1e-6:
                continue
            incoming_vector = (corner[0] - previous[0],
                               corner[1] - previous[1])
            outgoing_vector = (following[0] - corner[0],
                               following[1] - corner[1])
            if (incoming_vector[0] * outgoing_vector[0]
                    + incoming_vector[1] * outgoing_vector[1]
                    <= -0.9 * incoming * outgoing):
                result.append(corner)
                continue
            cut = min(radius, incoming * 0.35, outgoing * 0.35)
            before = (corner[0] + (previous[0] - corner[0]) * cut / incoming,
                      corner[1] + (previous[1] - corner[1]) * cut / incoming)
            after = (corner[0] + (following[0] - corner[0]) * cut / outgoing,
                     corner[1] + (following[1] - corner[1]) * cut / outgoing)
            result.append(before)
            for step in range(1, 5):
                t = step / 4
                inverse = 1 - t
                result.append((
                    inverse * inverse * before[0]
                    + 2 * inverse * t * corner[0] + t * t * after[0],
                    inverse * inverse * before[1]
                    + 2 * inverse * t * corner[1] + t * t * after[1]))
        result.append(points[-1])
        return result

    def _route_all_connections(self, connections=None):
        """Route the graph as a stable set so wires account for one another."""
        edges = sorted(self.store.connections(), key=lambda edge:
                       (edge.type != "CONTROL", edge.source_node,
                        edge.source_port,
                        edge.target_node, edge.target_port))
        if not edges:
            self._connection_paths.clear()
            return
        requested = (edges if connections is None else sorted(
            connections, key=lambda edge:
            (edge.type != "CONTROL", edge.source_node, edge.source_port,
             edge.target_node, edge.target_port)))
        full_route = connections is None or set(requested) == set(edges)
        live = set(edges)
        if full_route:
            self._connection_paths = {}
        else:
            self._connection_paths = {
                edge: cached for edge, cached in self._connection_paths.items()
                if edge in live
            }
        for edge in requested:
            self._cache_connection_route(edge)
        eligible = set(requested)

        def network_cost():
            conflicts = set()
            cost = 0.0
            paths = {edge: self._connection_paths.get(
                edge, (None, None, ()))[2] for edge in edges}

            def path_bounds(path):
                return (min(point[0] for point in path),
                        min(point[1] for point in path),
                        max(point[0] for point in path),
                        max(point[1] for point in path))

            bounds = {edge: path_bounds(path) for edge, path in paths.items()
                      if path}

            def nearby(first, second, gap=16.0):
                return not (first[2] + gap < second[0]
                            or second[2] + gap < first[0]
                            or first[3] + gap < second[1]
                            or second[3] + gap < first[1])

            for index, edge in enumerate(edges):
                path = paths[edge]
                for other in edges[index + 1:]:
                    other_path = paths[other]
                    if not path or not other_path:
                        continue
                    if edge not in eligible and other not in eligible:
                        continue
                    if not nearby(bounds[edge], bounds[other]):
                        continue
                    crossed = self._paths_cross(
                        path, other_path,
                        self._shared_wire_points(edge, other))
                    spacing = self._wire_spacing_cost(
                        path, other_path, edge, other)
                    if crossed or spacing > 0.0:
                        if edge in eligible:
                            conflicts.add(edge)
                        if other in eligible:
                            conflicts.add(other)
                    cost += (10000.0 if crossed else 0.0) + spacing
            return cost, conflicts

        # Re-route only wires involved in crossings or close parallel runs.
        # A few stable coordinate-descent passes let earlier wires account
        # for routes selected later without allowing unbounded oscillation.
        for pass_index in range(3):
            old_cost, conflicts = network_cost()
            if not conflicts:
                break
            previous = dict(self._connection_paths)
            order = requested if pass_index % 2 == 0 else reversed(requested)
            for edge in order:
                if edge in conflicts:
                    self._cache_connection_route(edge)
            new_cost, _new_conflicts = network_cost()
            if new_cost >= old_cost - 1e-6:
                self._connection_paths = previous
                break

    def _cache_connection_route(self, edge):
        source = self.store.get(edge.source_node)
        target = self.store.get(edge.target_node)
        start = self._connection_world_point(
            edge.source_node, edge.source_port)
        end = self._connection_world_point(
            edge.target_node, edge.target_port)
        if source is None or target is None or start is None or end is None:
            self._connection_paths.pop(edge, None)
            return
        signature = (start, end, source.x, source.y, target.x, target.y)
        path = self._route_wire(start, end, source, target, edge)
        self._connection_paths[edge] = (
            self._routing_revision, signature, path,
            FlowCanvas._path_bounds(path))

    @staticmethod
    def _wire_spacing_cost(first, second, first_connection,
                           second_connection):
        """Prefer curved routes that leave a small gap between wire strokes."""
        minimum_gap = 16.0
        first_bounds = FlowCanvas._path_bounds(first)
        second_bounds = FlowCanvas._path_bounds(second)
        if (first_bounds[2] + minimum_gap < second_bounds[0]
                or second_bounds[2] + minimum_gap < first_bounds[0]
                or first_bounds[3] + minimum_gap < second_bounds[1]
                or second_bounds[3] + minimum_gap < first_bounds[1]):
            return 0.0
        cost = 0.0
        shared_source = (first_connection is not None
                         and second_connection is not None
                         and first_connection.source_node
                         == second_connection.source_node
                         and first_connection.source_port
                         == second_connection.source_port)
        shared_target = (first_connection is not None
                         and second_connection is not None
                         and first_connection.target_node
                         == second_connection.target_node
                         and first_connection.target_port
                         == second_connection.target_port)
        sampled_first = first[::3]
        sampled_second = second[::3]
        if sampled_first[-1] != first[-1]:
            sampled_first.append(first[-1])
        if sampled_second[-1] != second[-1]:
            sampled_second.append(second[-1])
        other_segments = list(zip(sampled_second, sampled_second[1:]))
        for index, point in enumerate(sampled_first):
            if shared_source and index < 2:
                continue
            if shared_target and index >= len(sampled_first) - 2:
                continue
            nearest = min(FlowCanvas._point_segment_distance(
                *point, a, b) for a, b in other_segments)
            if nearest < minimum_gap:
                cost += (minimum_gap - nearest) * 4.5
        return cost

    def _visibility_route(self, start, end, obstacles, other_paths,
                         connection=None, ignore_ai_boundary=False,
                         region_obstacles=(), search_bounds=None):
        """Find an obstacle-free orthogonal path when local lanes are blocked."""
        # Leave enough clearance for _round_wire_path's smoothing radius;
        # paths two pixels from a card edge can curve back into its outline.
        padding = 14.0
        margin = max(
            theme.WIRE_LOCAL_MARGIN_MIN,
            min(theme.WIRE_LOCAL_MARGIN_MAX,
                math.dist(start, end) * 0.2
                + theme.WIRE_LOCAL_MARGIN_BASE),
        )
        bounds = search_bounds or (
            min(start[0], end[0]) - margin,
            min(start[1], end[1]) - margin,
            max(start[0], end[0]) + margin,
            max(start[1], end[1]) + margin,
        )
        blocking_regions = [
            box for box in region_obstacles
            if (box[0] <= max(start[0], end[0])
                and box[2] >= min(start[0], end[0])
                and box[1] <= max(start[1], end[1])
                and box[3] >= min(start[1], end[1]))
        ]
        if blocking_regions:
            bounds = (
                min(bounds[0], *(box[0] - margin
                                  for box in blocking_regions)),
                min(bounds[1], *(box[1] - margin
                                  for box in blocking_regions)),
                max(bounds[2], *(box[2] + margin
                                  for box in blocking_regions)),
                max(bounds[3], *(box[3] + margin
                                  for box in blocking_regions)),
            )
        local_obstacles = [
            box for box in obstacles
            if (box[0] <= bounds[2] and box[2] >= bounds[0]
                and box[1] <= bounds[3] and box[3] >= bounds[1])
        ]
        if any(x0 < point[0] < x1 and y0 < point[1] < y1
               for point in (start, end)
               for x0, y0, x1, y1 in local_obstacles):
            return None
        xs = {start[0], end[0], bounds[0], bounds[2]}
        ys = {start[1], end[1], bounds[1], bounds[3]}
        for x0, y0, x1, y1 in local_obstacles:
            xs.update(value for value in (x0 - padding, x1 + padding)
                      if bounds[0] <= value <= bounds[2])
            ys.update(value for value in (y0 - padding, y1 + padding)
                      if bounds[1] <= value <= bounds[3])
        boundaries = []
        if not ignore_ai_boundary:
            boundaries = [
                region for _task_id, region
                in _execution_region_bounds(self.store.all())
                if (region[0] <= bounds[2] and region[2] >= bounds[0]
                    and region[1] <= bounds[3] and region[3] >= bounds[1])
            ]
            for boundary in boundaries:
                xs.update(value for value in
                          (boundary[0] - 6.0, boundary[2] + 6.0)
                          if bounds[0] <= value <= bounds[2])
                ys.update(value for value in
                          (boundary[1] - 6.0, boundary[3] + 6.0)
                          if bounds[1] <= value <= bounds[3])
        xs, ys = sorted(xs), sorted(ys)
        x_index = {value: index for index, value in enumerate(xs)}
        y_index = {value: index for index, value in enumerate(ys)}
        source = (x_index[start[0]], y_index[start[1]])
        target = (x_index[end[0]], y_index[end[1]])
        initial = (*source, -1)
        distances = {initial: 0.0}
        parents = {}
        heuristic = lambda x, y: abs(xs[x] - end[0]) + abs(ys[y] - end[1])
        wire_paths = []
        for other_connection, path in other_paths:
            wire_paths.append((
                other_connection, path,
                (min(point[0] for point in path),
                 min(point[1] for point in path),
                 max(point[0] for point in path),
                 max(point[1] for point in path))))
        queue = [(heuristic(*source), 0.0, *source, -1)]
        finish = None
        while queue:
            _estimate, cost, x, y, direction = heapq.heappop(queue)
            state = (x, y, direction)
            if cost != distances.get(state):
                continue
            if (x, y) == target:
                finish = state
                break
            point = (xs[x], ys[y])
            neighbors = []
            if x:
                neighbors.append((x - 1, y, 0))
            if x + 1 < len(xs):
                neighbors.append((x + 1, y, 0))
            if y:
                neighbors.append((x, y - 1, 1))
            if y + 1 < len(ys):
                neighbors.append((x, y + 1, 1))
            for nx, ny, next_direction in neighbors:
                next_point = (xs[nx], ys[ny])
                if any(self._segment_hits_rect(point, next_point, *box)
                       for box in local_obstacles):
                    continue
                edge_cost = (abs(point[0] - next_point[0])
                             + abs(point[1] - next_point[1]))
                for boundary in boundaries:
                    horizontal_border = (
                        abs(next_point[1] - point[1]) < 1.0
                        and min(abs(point[1] - boundary[1]),
                                abs(point[1] - boundary[3])) <= 6.0
                        and max(min(point[0], next_point[0]), boundary[0])
                        < min(max(point[0], next_point[0]), boundary[2]))
                    vertical_border = (
                        abs(next_point[0] - point[0]) < 1.0
                        and min(abs(point[0] - boundary[0]),
                                abs(point[0] - boundary[2])) <= 6.0
                        and max(min(point[1], next_point[1]), boundary[1])
                        < min(max(point[1], next_point[1]), boundary[3]))
                    if horizontal_border or vertical_border:
                        edge_cost += (abs(point[0] - next_point[0])
                                      + abs(point[1] - next_point[1])) * 8.0
                segment_box = (min(point[0], next_point[0]),
                               min(point[1], next_point[1]),
                               max(point[0], next_point[0]),
                               max(point[1], next_point[1]))
                for other_connection, path, path_box in wire_paths:
                    if (segment_box[2] < path_box[0]
                            or segment_box[0] > path_box[2]
                            or segment_box[3] < path_box[1]
                            or segment_box[1] > path_box[3]):
                        continue
                    allowed_shared = ()
                    shared_source = (connection is not None
                                     and other_connection.source_node
                                     == connection.source_node
                                     and other_connection.source_port
                                     == connection.source_port)
                    shared_target = (connection is not None
                                     and other_connection.target_node
                                     == connection.target_node
                                     and other_connection.target_port
                                     == connection.target_port)
                    if (connection is not None
                            and other_connection.source_node
                            == connection.source_node
                            and other_connection.source_port
                            == connection.source_port):
                        allowed_shared = (start,)
                    elif (connection is not None
                          and other_connection.target_node
                          == connection.target_node
                          and other_connection.target_port
                          == connection.target_port):
                        allowed_shared = (end,)
                    if self._paths_cross([point, next_point], path,
                                         allowed_shared):
                        edge_cost += 2000
                    if not ((shared_source and point == start)
                            or (shared_target and next_point == end)):
                        for a, b in zip(path, path[1:]):
                            separation = min(
                                FlowCanvas._point_segment_distance(
                                    point[0], point[1], a, b),
                                FlowCanvas._point_segment_distance(
                                    next_point[0], next_point[1], a, b),
                                FlowCanvas._point_segment_distance(
                                    a[0], a[1], point, next_point),
                                FlowCanvas._point_segment_distance(
                                    b[0], b[1], point, next_point))
                            if separation < 16.0:
                                edge_cost += (16.0 - separation) * 2.0
                turn = 20 if direction >= 0 and direction != next_direction else 0
                next_state = (nx, ny, next_direction)
                next_cost = cost + edge_cost + turn
                if next_cost < distances.get(next_state, math.inf):
                    distances[next_state] = next_cost
                    parents[next_state] = state
                    estimate = next_cost + heuristic(nx, ny)
                    heapq.heappush(queue, (estimate, next_cost, nx, ny,
                                           next_direction))
        if finish is None:
            return None
        route = []
        state = finish
        while state != initial:
            route.append((xs[state[0]], ys[state[1]]))
            state = parents[state]
        route.append(start)
        route.reverse()
        return self._simplify_wire_path(route)

    @staticmethod
    def _simplify_wire_path(points):
        simplified = []
        for point in points:
            if simplified and point == simplified[-1]:
                continue
            if len(simplified) >= 2:
                a, b = simplified[-2:]
                if ((a[0] == b[0] == point[0])
                        or (a[1] == b[1] == point[1])):
                    simplified[-1] = point
                    continue
            simplified.append(point)
        return simplified

    @staticmethod
    def _paths_cross(first, second, shared_endpoints=()):
        if (not first or not second
                or max(point[0] for point in first)
                < min(point[0] for point in second)
                or max(point[0] for point in second)
                < min(point[0] for point in first)
                or max(point[1] for point in first)
                < min(point[1] for point in second)
                or max(point[1] for point in second)
                < min(point[1] for point in first)):
            return False
        for a, b in zip(first, first[1:]):
            for c, d in zip(second, second[1:]):
                if (max(a[0], b[0]) < min(c[0], d[0])
                        or max(c[0], d[0]) < min(a[0], b[0])
                        or max(a[1], b[1]) < min(c[1], d[1])
                        or max(c[1], d[1]) < min(a[1], b[1])):
                    continue
                if not FlowCanvas._segments_intersect(a, b, c, d):
                    continue
                shared = {point for point in (a, b) if point in (c, d)}
                collinear = (
                    abs((b[0] - a[0]) * (c[1] - a[1])
                        - (b[1] - a[1]) * (c[0] - a[0])) < 1e-8
                    and abs((b[0] - a[0]) * (d[1] - a[1])
                            - (b[1] - a[1]) * (d[0] - a[0])) < 1e-8)
                if collinear:
                    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
                    overlap = min(max(a[axis], b[axis]),
                                  max(c[axis], d[axis])) - max(
                                      min(a[axis], b[axis]),
                                      min(c[axis], d[axis]))
                    if overlap > 1.0:
                        return True
                elif not (shared & set(shared_endpoints)):
                    return True
        return False

    @staticmethod
    def _segments_intersect(a, b, c, d):
        def orient(p, q, r):
            return ((q[0] - p[0]) * (r[1] - p[1])
                    - (q[1] - p[1]) * (r[0] - p[0]))

        return (orient(a, b, c) * orient(a, b, d) <= 0
                and orient(c, d, a) * orient(c, d, b) <= 0
                and max(min(a[0], b[0]), min(c[0], d[0]))
                <= min(max(a[0], b[0]), max(c[0], d[0]))
                and max(min(a[1], b[1]), min(c[1], d[1]))
                <= min(max(a[1], b[1]), max(c[1], d[1])))

    @staticmethod
    def _segment_hits_rect(start, end, x0, y0, x1, y1):
        """Return whether a line segment intersects an axis-aligned box."""
        sx, sy = start
        ex, ey = end
        dx, dy = ex - sx, ey - sy
        lower, upper = 0.0, 1.0
        for p, q in ((-dx, sx - x0), (dx, x1 - sx),
                     (-dy, sy - y0), (dy, y1 - sy)):
            if abs(p) < 1e-12:
                if q < 0:
                    return False
                continue
            t = q / p
            if p < 0:
                lower = max(lower, t)
            else:
                upper = min(upper, t)
            if lower > upper:
                return False
        return True

    def _scene_route_signature(self, connections):
        nodes = tuple((node.id, node.type, node.x, node.y, node.w, node.h,
                       node.execution_task_id)
                      for node in self.store.all())
        return nodes, tuple(connections)

    def _affected_routes(self, connections, previous, current,
                         removed_paths):
        if previous is None:
            return None
        old_nodes = {node[0]: node for node in previous[0]}
        new_nodes = {node[0]: node for node in current[0]}
        changed_ids = {node_id for node_id in old_nodes.keys() | new_nodes.keys()
                       if old_nodes.get(node_id) != new_nodes.get(node_id)}
        if any(node[1] in theme.AI_NODE_TYPES
               for node_id in changed_ids
               for node in (old_nodes.get(node_id), new_nodes.get(node_id))
               if node is not None):
            return None
        clearance = theme.WIRE_CARD_CLEARANCE + 16.0
        changed_boxes = [
            (node[2] - clearance, node[3] - clearance,
             node[2] + node[4] + clearance,
             node[3] + node[5] + clearance)
            for node_id in changed_ids
            for node in (old_nodes.get(node_id), new_nodes.get(node_id))
            if node is not None
        ]
        old_edges = set(previous[1])
        affected = set(connections) - old_edges
        removed_bounds = [
            cached[3] if len(cached) > 3
            else FlowCanvas._path_bounds(cached[2])
            for cached in removed_paths.values()
        ]
        for edge in connections:
            cached = self._connection_paths.get(edge)
            if (cached is None or edge.source_node in changed_ids
                    or edge.target_node in changed_ids):
                affected.add(edge)
                continue
            if changed_boxes and self._path_hits_obstacles(
                    cached[2], changed_boxes):
                affected.add(edge)
                continue
            bounds = (cached[3] if len(cached) > 3
                      else FlowCanvas._path_bounds(cached[2]))
            if any(bounds[0] <= other[2] + 16.0
                   and bounds[2] >= other[0] - 16.0
                   and bounds[1] <= other[3] + 16.0
                   and bounds[3] >= other[1] - 16.0
                   for other in removed_bounds):
                affected.add(edge)
        return [edge for edge in connections if edge in affected]

    def _sync_connections(self):
        connections = self.store.connections()
        live = set(connections)
        removed_paths = {edge: cached
                         for edge, cached in self._connection_paths.items()
                         if edge not in live}
        for connection, item in list(self._connection_items.items()):
            if connection not in live:
                self.delete(item)
                halo = self._connection_halos.pop(connection, None)
                if halo is not None:
                    self.delete(halo)
                del self._connection_items[connection]
                self._connection_paths.pop(connection, None)
        for connection in list(self._connection_halos):
            if connection not in live:
                self.delete(self._connection_halos.pop(connection))
        if self._hovered_connection not in live:
            self._hovered_connection = None
        if self._selected_connection not in live:
            self._selected_connection = None
        self._refresh_highlighted_wire_ports()
        scene_signature = self._scene_route_signature(connections)
        if (scene_signature != self._route_scene_signature
                or any(edge not in self._connection_paths
                       for edge in connections)):
            affected = self._affected_routes(
                connections, self._route_scene_signature,
                scene_signature, removed_paths)
            if affected is None:
                self._route_all_connections(connections)
            elif affected:
                self._route_all_connections(affected)
            self._route_scene_signature = scene_signature
        for connection in connections:
            self._render_connection(connection)
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle.clear()
        self._route_drag_positions.clear()
        if connections:
            self.tag_lower("connection_halo")
            self.tag_lower("grid")
        self._refresh_connection_drag()
        self._animate_wire_styles()
        self._sync_port_colors()
        self._refresh_connection_candidates()
        if self._connection_drag is not None:
            self._refresh_connection_drag()

    def _sync_port_colors(self):
        """Fill semantic pins at either end of every visible connection."""
        connected = set()
        for edge in self.store.connections():
            connected.add((edge.source_node, edge.source_port))
            connected.add((edge.target_node, edge.target_port))
        for nid, card in self._cards.items():
            setter = getattr(card, "set_port_connected", None)
            if setter is None:
                continue
            for port, _side, _y in theme.NODE_PINS.get(
                    self.store.get(nid).type, ()):
                setter(port, (nid, port) in connected)

    def _response_contract_changed(self, response_id):
        response = self.store.get(response_id)
        if response is not None:
            for edge in self.store.connections():
                if (edge.target_node == response_id
                        and edge.target_port == "contract"):
                    task = self.store.get(edge.source_node)
                    if task is not None and task.type == "task":
                        task.contract.update({
                            "format": response.response_format.lower(),
                            "style": [style.lower()
                                      for style in response.response_styles],
                        })
        self._notify_flow_change()

    def _refresh_connection_drag(self):
        if self._connection_drag is None or self._connection_line is None:
            return
        cursor = self._connection_cursor
        if cursor is not None:
            self._connection_motion(SimpleNamespace(
                x_root=self.winfo_rootx() + cursor[0],
                y_root=self.winfo_rooty() + cursor[1]))

    def _update_connections_for_node(self, node_id):
        node = self.store.get(node_id)
        if node is None:
            return
        if node.type in ("plan", "action", "evaluation"):
            self._draw_ai_region()
        self._routing_revision += 1
        self._routes_need_settle = True
        previous = self._route_drag_positions.get(node_id)
        if (previous is None and self._drag_from_card
                and self._drag == node_id and self._grab is not None):
            previous = (self._grab[2], self._grab[3])
        if previous is None:
            previous = (node.x, node.y)
        old_rect = (
            previous[0] - theme.WIRE_CARD_CLEARANCE,
            previous[1] - theme.WIRE_CARD_CLEARANCE,
            previous[0] + node.w + theme.WIRE_CARD_CLEARANCE,
            previous[1] + node.h + theme.WIRE_CARD_CLEARANCE,
        )
        rect = (node.x - theme.WIRE_CARD_CLEARANCE,
                node.y - theme.WIRE_CARD_CLEARANCE,
                node.x + node.w + theme.WIRE_CARD_CLEARANCE,
                node.y + node.h + theme.WIRE_CARD_CLEARANCE)
        self._route_drag_positions[node_id] = (node.x, node.y)
        for connection in self.store.connections():
            cached = self._connection_paths.get(connection)
            incident = (connection.source_node == node_id
                        or connection.target_node == node_id)
            bounds = None
            if cached is not None:
                bounds = (cached[3] if len(cached) > 3
                          else FlowCanvas._path_bounds(cached[2]))
            near_new = (bounds is not None
                        and bounds[0] <= rect[2] and bounds[2] >= rect[0]
                        and bounds[1] <= rect[3] and bounds[3] >= rect[1])
            near_old = (bounds is not None
                        and bounds[0] <= old_rect[2]
                        and bounds[2] >= old_rect[0]
                        and bounds[1] <= old_rect[3]
                        and bounds[3] >= old_rect[1])
            crosses_new_card = (near_new and any(
                self._segment_hits_rect(first, second, *rect)
                for first, second in zip(cached[2], cached[2][1:])))
            crosses_old_card = (near_old and any(
                self._segment_hits_rect(first, second, *old_rect)
                for first, second in zip(cached[2], cached[2][1:])))
            if incident or crosses_new_card or crosses_old_card:
                self._routes_to_settle.add(connection)
            if incident or crosses_new_card:
                self._render_connection(connection, force_route=True,
                                        preview=True)
        if self._connection_drag is not None:
            self._refresh_connection_candidates()
            self._refresh_connection_drag()

    def _settle_wire_routes(self):
        if not self._routes_need_settle:
            return
        self._routing_revision += 1
        live = self.store.connections()
        if self._routes_need_full_settle:
            connections = live
        else:
            connections = [edge for edge in live
                           if edge in self._routes_to_settle]
        previous_paths = {
            edge: self._connection_paths[edge][2]
            for edge in connections if edge in self._connection_paths
        }
        if self._routes_need_full_settle:
            self._route_all_connections()
        elif connections:
            self._route_all_connections(connections)
        for connection in connections:
            self._render_connection(connection)
        if self._drag_from_card:
            self._fade_settled_routes(previous_paths)
        self._route_scene_signature = self._scene_route_signature(live)
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle.clear()
        self._route_drag_positions.clear()
        self.tag_lower("connection_halo")
        self.tag_lower("grid")

    def _clear_route_transitions(self):
        if self._route_transition_job is not None:
            self.after_cancel(self._route_transition_job)
            self._route_transition_job = None
        for edge, overlay in self._route_transition_overlays.items():
            self.delete(overlay)
            line = self._connection_items.get(edge)
            if line is not None:
                self.itemconfigure(line, stipple="")
        self._route_transition_overlays.clear()

    def _fade_settled_routes(self, previous_paths):
        self._clear_route_transitions()
        viewport = (0, 0, self.winfo_width(), self.winfo_height())
        for edge, previous in previous_paths.items():
            current = self._connection_paths.get(edge)
            line = self._connection_items.get(edge)
            if current is None or line is None or previous == current[2]:
                continue
            bounds = FlowCanvas._path_bounds(previous)
            first = self.world_to_screen(bounds[0], bounds[1])
            last = self.world_to_screen(bounds[2], bounds[3])
            if (last[0] < viewport[0] or first[0] > viewport[2]
                    or last[1] < viewport[1] or first[1] > viewport[3]):
                continue
            coords = [value for point in previous
                      for value in self.world_to_screen(*point)]
            overlay = self.create_line(
                *coords, fill=self.itemcget(line, "fill"),
                width=self.itemcget(line, "width"),
                dash=self.itemcget(line, "dash"),
                arrow=tk.LAST if edge.type != "CONTROL" else tk.NONE,
                capstyle=tk.ROUND, joinstyle=tk.ROUND,
                tags=("connection_transition", "world"))
            self._route_transition_overlays[edge] = overlay
            self.itemconfigure(line, stipple="gray12")
        if self._route_transition_overlays:
            self._route_transition_job = self.after(
                24, self._step_route_transitions, 1)

    def _step_route_transitions(self, frame):
        self._route_transition_job = None
        new_stipple = ("gray25", "gray50", "gray75", "")[frame - 1]
        old_stipple = ("gray75", "gray50", "gray25", "")[frame - 1]
        for edge, overlay in self._route_transition_overlays.items():
            line = self._connection_items.get(edge)
            if line is not None:
                self.itemconfigure(line, stipple=new_stipple)
            self.itemconfigure(overlay, stipple=old_stipple)
        if frame == 4:
            self._clear_route_transitions()
        else:
            self._route_transition_job = self.after(
                24, self._step_route_transitions, frame + 1)

    def _press(self, event):
        nid = self._node_id_at_current()
        node = self.store.get(nid) if nid is not None else None
        if node is not None and (node.system_generated or node.read_only):
            self._notify_ai_node_interaction()
            return "break"
        self.focus_set()
        if self._connection_drag is not None:
            self._cancel_connection()
            return "break"
        wire, _distance = self._wire_nearest(event.x, event.y)
        if wire is not None:
            self.store.select_many(())
            self._select_connection(wire)
            self._sel_box_start = None
            self._drag = None
            self._apply_selection()
            return
        self._wire_hover_leave()
        self._select_connection(None)
        if nid is not None:
            node = self.store.get(nid)
            if getattr(event, "state", 0) & 0x1:  # Shift-click toggles
                self.store.toggle_select(nid)
            else:
                self.store.select(nid)
            self._drag = (None if node.system_generated or node.read_only else
                          (nid, event.x, event.y, node.x, node.y))
        else:
            self.store.select_many(())
            self._sel_box_start = (event.x, event.y)
            self._draw_sel_box(event.x, event.y)
        self._apply_selection()

    def _draw_sel_box(self, x, y):
        x0, y0 = self._sel_box_start
        if self._sel_box is None:
            self._sel_box = self.create_rectangle(
                x0, y0, x, y, fill=theme.SELECT, stipple="gray12",
                outline=theme.SELECT, width=1, tags="sel_box")
        else:
            self.coords(self._sel_box, x0, y0, x, y)
        self.tag_raise("sel_box")
        self._zoom_controls.tkraise()

    def _finish_sel_box(self, event):
        """Release of an LMB selection box: delete the overlay rectangle and
        apply the selection. A sub-4px drag is a plain click -> clear."""
        start = self._sel_box_start
        self._sel_box_start = None
        if self._sel_box is not None:
            self.delete(self._sel_box)
            self._sel_box = None
        if start is None:
            return
        x0, y0 = start
        x1, y1 = event.x, event.y
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            self.store.select_many(())
            self._apply_selection()
            return
        wx0, wy0 = self.screen_to_world(x0, y0)
        wx1, wy1 = self.screen_to_world(x1, y1)
        left, right = sorted((wx0, wx1))
        top, bottom = sorted((wy0, wy1))
        # Fully contained: the node rect must sit inside the box.
        contained = [node for node in self.store.all()
                     if left <= node.x and node.x + node.w <= right
                     and top <= node.y and node.y + node.h <= bottom]
        if any(node.system_generated or node.read_only for node in contained):
            self._notify_ai_node_interaction()
        inside = [node.id for node in contained
                  if not node.system_generated and not node.read_only]
        self.store.select_many(
            inside, add=bool(getattr(event, "state", 0) & 0x1))
        self._apply_selection()

    def _motion(self, event):
        if _PERF:
            _P["node_drag_events"] += 1
        if self._drag_from_card:
            return
        if self._sel_box_start is not None:
            self._draw_sel_box(event.x, event.y)
            return
        if self._drag is not None:
            nid, gx, gy, start_x, start_y = self._drag
            n = self.store.get(nid)
            if n is None or n.read_only or n.system_generated:
                self._drag = None
                return
            tx = start_x + (event.x - gx) / self.zoom
            ty = start_y + (event.y - gy) / self.zoom
            mx = grid_step(theme.CREATE_GRID_X, self.zoom)
            my = grid_step(theme.CREATE_GRID_Y, self.zoom)
            # nodes roam an unbounded plane (negative world coords included) —
            # no viewport bound, no world bound; only snapping applies
            sx, sy = snap_to_grid(tx, ty, grid_x=mx, grid_y=my)
            delta_x = sx - n.x
            delta_y = sy - n.y
            if delta_x or delta_y:
                self.store.move_delta(nid, delta_x, delta_y)
                self.move(f"node_{nid}", delta_x * self.zoom, delta_y * self.zoom)
                self._update_connections_for_node(nid)
            return

    def _release(self, event):
        # only the canvas node drag (tuple form) ends here; an int _drag is
        # a card drag in progress, handled by _card_release via bind_all.
        # The node is already on the shared snap grid from the last motion event;
        # release does not re-snap.
        if self._sel_box_start is not None:
            self._finish_sel_box(event)
        if isinstance(self._drag, tuple):
            self._drag = None
            self._settle_wire_routes()

    # ------------------------------------------------------- task card drag
    def _card_press(self, nid, x_root, y_root, state=0):
        """Drag start from a card's free surface (root coords). Shift adds
        the card to the selection (toggling it); plain press replaces."""
        node = self.store.get(nid)
        if node is None:
            return
        if node.system_generated or node.read_only:
            self._notify_ai_node_interaction()
            return
        point = (x_root - self.winfo_rootx(),
                 y_root - self.winfo_rooty())
        radius = max(10.0, 12.0 * self.zoom)
        for port, _side, _y in theme.NODE_PINS.get(node.type, ()):
            pin = self._connection_screen_point(nid, port)
            if pin is not None and math.dist(point, pin) <= radius:
                self._connection_press(nid, port, x_root, y_root)
                return
        self.focus_set()
        self._wire_hover_leave()
        self._select_connection(None)
        if state & 0x1:
            self.store.toggle_select(nid)
        else:
            self.store.select(nid)
        self._apply_selection()
        self._drag = nid
        self._grab = (x_root, y_root, node.x, node.y)
        self._drag_from_card = True
        if self._drag_motion_job is not None:
            self.after_cancel(self._drag_motion_job)
            self._drag_motion_job = None
        self._pending_card_motion = None
        self._last_drag_frame = 0.0
        self.bind_all("<Motion>", self._card_motion)
        self.bind_all("<ButtonRelease-1>", self._card_release)

    def _card_motion(self, event):
        if _PERF:
            _P["card_drag_events"] += 1
        if self._drag is None or not self._drag_from_card:
            return
        self._pending_card_motion = (event.x_root, event.y_root)
        if self._drag_motion_job is not None:
            return
        elapsed = time.perf_counter() - self._last_drag_frame
        if elapsed < 1 / 60:
            delay = max(1, math.ceil((1 / 60 - elapsed) * 1000))
            self._drag_motion_job = self.after(delay, self._flush_card_motion)
            return
        self._flush_card_motion()

    def _flush_card_motion(self):
        self._drag_motion_job = None
        pending = self._pending_card_motion
        self._pending_card_motion = None
        if pending is None or self._drag is None or not self._drag_from_card:
            return
        self._move_card_to(*pending)
        self._last_drag_frame = time.perf_counter()

    def _move_card_to(self, x_root, y_root):
        nid = self._drag
        n = self.store.get(nid)
        if n is None:
            self._card_release()
            return
        gx, gy, start_x, start_y = self._grab
        tx = start_x + (x_root - gx) / self.zoom
        ty = start_y + (y_root - gy) / self.zoom
        mx = grid_step(theme.CREATE_GRID_X, self.zoom)
        my = grid_step(theme.CREATE_GRID_Y, self.zoom)
        # Keep drag motion snapped and lightweight. The final drop is clamped
        # to the visible canvas and collision-corrected in _card_release.
        sx, sy = snap_to_grid(tx, ty, grid_x=mx, grid_y=my)
        delta_x = sx - n.x
        delta_y = sy - n.y
        if delta_x or delta_y:
            self.store.move_delta(nid, delta_x, delta_y)
            self.move(f"card_{nid}", delta_x * self.zoom, delta_y * self.zoom)
            self._update_connections_for_node(nid)
            if self._connection_drag is not None:
                self._connection_motion(SimpleNamespace(
                    x_root=x_root, y_root=y_root))

    def _card_release(self, event=None):
        if self._connection_drag is not None and not self._drag_from_card:
            return
        if self._drag_motion_job is not None:
            self.after_cancel(self._drag_motion_job)
            self._drag_motion_job = None
        self._flush_card_motion()
        if self._drag_from_card and self._drag is not None:
            self._resolve_card_overlap(self._drag)
        self._settle_wire_routes()
        self.unbind_all("<Motion>")
        self.unbind_all("<ButtonRelease-1>")
        self._drag = None
        self._drag_from_card = False
        if self._connection_drag is not None:
            self.bind_all("<Motion>", self._connection_motion)

    def _resolve_card_overlap(self, node_id):
        """Keep a dropped card in view and clear of other cards when possible."""
        node = self.store.get(node_id)
        if node is None:
            return
        others = [other for other in self.store.all()
                  if other.id != node_id and is_card_type(other.type)]
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw < 2 or ch < 2:
            return
        min_x, min_y = self.screen_to_world(0, 0)
        max_x = (cw - self.pan_x) / self.zoom - node.w
        max_y = (ch - self.pan_y) / self.zoom - node.h
        max_x, max_y = max(min_x, max_x), max(min_y, max_y)
        gap = 12.0 / self.zoom

        def clamp(value, low, high):
            return min(max(value, low), high)

        def is_clear(x, y):
            return all(
                x + node.w + gap <= other.x
                or other.x + other.w + gap <= x
                or y + node.h + gap <= other.y
                or other.y + other.h + gap <= y
                for other in others)

        target_x, target_y = node.x, node.y
        if (min_x <= target_x and target_x + node.w <= (cw - self.pan_x) / self.zoom
                and min_y <= target_y
                and target_y + node.h <= (ch - self.pan_y) / self.zoom
                and is_clear(target_x, target_y)):
            return

        step_x = grid_step(theme.CREATE_GRID_X, self.zoom)
        step_y = grid_step(theme.CREATE_GRID_Y, self.zoom)
        x_min = math.ceil(min_x / step_x)
        x_max = math.floor(max_x / step_x)
        y_min = math.ceil(min_y / step_y)
        y_max = math.floor(max_y / step_y)
        xs = {i * step_x for i in range(x_min, x_max + 1)}
        ys = {i * step_y for i in range(y_min, y_max + 1)}
        # If the viewport has room for the card but no grid point, its edge
        # is the only bounded placement available on that axis.
        if not xs:
            xs.add(clamp(target_x, min_x, max_x))
        if not ys:
            ys.add(clamp(target_y, min_y, max_y))

        best = None
        for x in xs:
            for y in ys:
                if not is_clear(x, y):
                    continue
                distance = (x - target_x) ** 2 + (y - target_y) ** 2
                candidate = (distance, x, y)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            # The world can extend beyond the current viewport. If it is too
            # crowded to find a legal in-view grid point, try the closest
            # grid-aligned positions just outside each neighboring card
            # before accepting any overlap.
            for other in others:
                xs.add(math.floor(
                    (other.x - node.w - gap) / step_x) * step_x)
                xs.add(math.ceil(
                    (other.x + other.w + gap) / step_x) * step_x)
                ys.add(math.floor(
                    (other.y - node.h - gap) / step_y) * step_y)
                ys.add(math.ceil(
                    (other.y + other.h + gap) / step_y) * step_y)
            for x in xs:
                for y in ys:
                    if not is_clear(x, y):
                        continue
                    distance = (x - target_x) ** 2 + (y - target_y) ** 2
                    candidate = (distance, x, y)
                    if best is None or candidate < best:
                        best = candidate
        if best is None:
            # Finite cards cannot cover the unbounded workflow plane. This
            # final position clears every card even if the viewport is tiny.
            x = max((other.x + other.w + gap for other in others),
                   default=target_x)
            x = math.ceil(x / step_x) * step_x
            y = snap_to_grid(target_y, grid_x=step_x, grid_y=step_y)
            best = (0, x, y)
        _, x, y = best
        dx, dy = x - node.x, y - node.y
        if not dx and not dy:
            return
        self.store.move_delta(node_id, dx, dy)
        if node_id in self._card_wins:
            self.move(f"card_{node_id}", dx * self.zoom, dy * self.zoom)
        self._update_connections_for_node(node_id)

    def _delete_node(self, node_id):
        node = self.store.get(node_id)
        if node is None:
            return
        if node.system_generated or node.read_only:
            self._notify_ai_node_interaction()
            return
        if (self._connection_drag is not None
                and self._connection_drag[0] == node_id):
            self._cancel_connection()
        if self._connection_target is not None \
                and self._connection_target[0] == node_id:
            self._set_connection_target(None)
        self.store.delete(node_id)
        self._routing_revision += 1
        self._teardown_card(node_id)
        self._redraw()
        self._notify_flow_change()

    def _change_node_type(self, node_id, node_type):
        node = self.store.get(node_id)
        if node is None:
            return
        if node_type in theme.AI_NODE_TYPES:
            self._notify_ai_node_interaction()
            return
        if node.system_generated or node.read_only:
            self._notify_ai_node_interaction()
            return
        node = self.store.change_type(node_id, node_type)
        if node is not None:
            self._redraw()
            self._notify_flow_change()
        return node

    # ----------------------------------------------------------------- pan
    def _zoom_box_press(self, event):
        if self.node_at(*self.screen_to_world(event.x, event.y)) is not None:
            self._zoom_box_start = None
            return
        self._zoom_box_start = (event.x, event.y)
        self._draw_zoom_box(event.x, event.y)

    def _zoom_box_motion(self, event):
        if self._zoom_box_start is not None:
            self._draw_zoom_box(event.x, event.y)

    def _draw_zoom_box(self, x, y):
        x0, y0 = self._zoom_box_start
        if self._zoom_box is None:
            self._zoom_box = self.create_rectangle(
                x0, y0, x, y, outline=theme.NODE_BORDER_NORMAL,
                dash=(4, 3), width=1, tags="zoom_box")
        else:
            self.coords(self._zoom_box, x0, y0, x, y)
        self.tag_raise(self._zoom_box)
        self._zoom_controls.tkraise()

    def _zoom_box_release(self, event):
        start = self._zoom_box_start
        self._zoom_box_start = None
        if self._zoom_box is not None:
            self.delete(self._zoom_box)
            self._zoom_box = None
        if start is None:
            return
        x0, y0 = start
        x1, y1 = event.x, event.y
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            return
        self.zoom_to_box(x0, y0, x1, y1)

    def zoom_to_box(self, x0, y0, x1, y1):
        """Zoom and center the world rectangle defined by two canvas points."""
        wx0, wy0 = self.screen_to_world(x0, y0)
        wx1, wy1 = self.screen_to_world(x1, y1)
        left, right = sorted((wx0, wx1))
        top, bottom = sorted((wy0, wy1))
        cw, ch = self.winfo_width(), self.winfo_height()
        z = max(self._zoom_min,
                min(3.0, cw / (right - left), ch / (bottom - top)))
        self.zoom = z
        self.pan_x = (cw - (left + right) * z) / 2.0
        self.pan_y = (ch - (top + bottom) * z) / 2.0
        self._redraw()

    def _pan_press(self, event):
        self._pan_start = (event.x_root, event.y_root, self.pan_x, self.pan_y)

    def _pan_motion(self, event):
        if _PERF:
            _P["pan_events"] += 1
        if self._pan_start is None:
            return
        rx, ry, px, py = self._pan_start
        self.pan_x = px + event.x_root - rx
        self.pan_y = py + event.y_root - ry
        self._schedule_view_render()

    def _pan_release(self, event):
        self._pan_start = None

    def _has_text_input_focus(self):
        try:
            focused = self.focus_get()
        except KeyError:
            return False
        return isinstance(focused, (tk.Text, tk.Entry))

    def _pan_key(self, event, dx, dy):
        # Same Text/Entry guard as _fit_key / _sort_key: keep typing in the
        # JSON editor / card fields from panning the view.
        if self._has_text_input_focus():
            return
        # Redraw path matches MMB pan (_pan_motion); the sign convention
        # differs: arrow keys move the VIEW in the key direction (Up/Left
        # move the view up/left), so content slides opposite the key.
        self.pan_x += dx
        self.pan_y += dy
        self._schedule_view_render()

    # ----------------------------------------------------------------- zoom
    def _plain_zoom(self, event, step):
        """Wheel zoom for the bind_all path.
        Guards: ignore over a Text/Entry, or over any widget
        whose master chain never reaches this canvas (library / panels)."""
        if isinstance(event.widget, (tk.Text, tk.Entry)):
            return
        w = event.widget
        while w is not None and w is not self:
            w = getattr(w, "master", None)
        if w is not self:
            return
        x = event.x_root - self.winfo_rootx()
        y = event.y_root - self.winfo_rooty()
        self._zoom_at_pointer(SimpleNamespace(x=x, y=y), step)

    def _zoom_at_pointer(self, event, step):
        if _PERF:
            _P["zoom_events"] += 1
        z = max(self._zoom_min,
                min(3.0, self.zoom * (1.1 if step > 0 else 1 / 1.1)))
        if z == self.zoom:
            return
        wx = (event.x - self.pan_x) / self.zoom
        wy = (event.y - self.pan_y) / self.zoom
        self.zoom = z
        self.pan_x = event.x - wx * z
        self.pan_y = event.y - wy * z
        self._schedule_view_render(full=True)

    def fit_all(self, event=None):
        """Pan + zoom so every node is centered in the viewport with PAD
        padding. Never touches node coords/dims or the store. Returns
        (zoom, pan_x, pan_y)."""
        cw, ch = self.winfo_width(), self.winfo_height()
        nodes = self.store.all()
        if not nodes:
            # default view: origin centered, grid visible, no crash
            self.zoom = 1.0
            self._zoom_min = 0.25
            self.pan_x = cw / 2.0
            self.pan_y = ch / 2.0
            self._redraw()
            return (1.0, cw / 2.0, ch / 2.0)
        min_x = min(n.x for n in nodes)
        max_x = max(n.x + n.w for n in nodes)
        min_y = min(n.y for n in nodes)
        max_y = max(n.y + n.h for n in nodes)
        PAD = 80.0
        bw = max(1e-6, max_x - min_x)
        bh = max(1e-6, max_y - min_y)
        z = min((cw - 2 * PAD) / bw, (ch - 2 * PAD) / bh, 3.0)
        self._zoom_min = min(0.25, max(0.12, z))
        z = max(self._zoom_min, z)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        self.zoom = z
        self.pan_x = cw / 2.0 - cx * z
        self.pan_y = ch / 2.0 - cy * z
        self._redraw()
        return (z, self.pan_x, self.pan_y)

    def _fit_button(self):
        if self.on_fit_request is not None:
            self.on_fit_request()
        else:
            self.fit_all()

    def _update_zoom_label(self):
        self._zoom_label.config(text=f"{round(self.zoom * 100)}%")

    def _fit_key(self, event):
        # Text-input guard: skip while typing in a Text/Entry (card title
        # Entry, description/purpose Text). focus_get() returns the
        # toplevel ('.') when the app window is focused (never None in
        # practice) and the canvas when the canvas is focused -- both are
        # not Text/Entry, so f/F fits in those states, as does None.
        if self._has_text_input_focus():
            return
        self.fit_all()

    # ---------------------------------------------------------------- delete
    def _delete_key(self, event):
        if self._selected_connection is not None:
            connection = self._selected_connection
            self._select_connection(None)
            if self.store.delete_connection(connection):
                self._routes_need_settle = True
                self._sync_connections()
                self._settle_wire_routes()
                self._notify_flow_change()
            return "break"
        ids = self.store.selected_ids()
        if not ids:
            return
        selected_nodes = [self.store.get(node_id) for node_id in ids]
        if any(node is not None
               and (node.system_generated or node.read_only)
               for node in selected_nodes):
            self._notify_ai_node_interaction()
            return "break"
        if len(ids) == 1:
            self._delete_node(next(iter(ids)))
            return
        for node_id in sorted(ids):
            node = self.store.get(node_id)
            if node is None or node.system_generated or node.read_only:
                continue
            self.store.delete(node_id)
            self._teardown_card(node_id)
        self.store.select_many(())
        self._routing_revision += 1
        self._redraw()
        self._notify_flow_change()

    # -------------------------------------------------------------- sort flow
    def _sort_key(self, event):
        # Same text-input guard as _fit_key: skip while typing in a Text/Entry.
        if self._has_text_input_focus():
            return
        self._sort_flow()

    def _sort_flow(self):
        """Place cards by graph dependencies without changing manual layout."""
        if not self.store.all():
            return
        traces = dict(self.store.execution_traces)
        nodes = self.store.all()
        if nodes:
            min_x = min(node.x for node in nodes)
            min_y = min(node.y for node in nodes)
            max_x = max(node.x + node.w for node in nodes)
            max_y = max(node.y + node.h for node in nodes)
            center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
        else:
            cw, ch = self.winfo_width(), self.winfo_height()
            center = self.screen_to_world(cw / 2, ch / 2)
        self.store._nodes = {nid: node for nid, node in self.store._nodes.items()
                             if not node.system_generated}
        self.store._connections = {
            key: edge for key, edge in self.store._connections.items()
            if edge.ownership == "USER"}
        node_specs = []
        for node in self.store.all():
            node_specs.append({
                "id": node.id, "type": node.type, "title": node.header,
                "description": node.description, "file_path": node.file_path,
                "file_paths": list(node.file_paths),
                "folder_path": node.folder_path,
                "purpose": node.purpose,
                "allow_permission": node.permission,
                "format": node.response_format,
                "style": tuple(node.response_styles),
                "contract": dict(node.contract),
                "migration_legacy": dict(node.migration_legacy),
                "extra_props": dict(node.extra_props),
            })
        edge_specs = [
            {"source": {"node": edge.source_node, "port": edge.source_port},
             "target": {"node": edge.target_node, "port": edge.target_port}}
            for edge in self.store.connections() if edge.ownership == "USER"
        ]
        positions = self._workflow_layout(
            {"nodes": node_specs, "edges": edge_specs}, center, traces)
        self.store.replace_graph(node_specs, edge_specs, positions)
        self.store.set_execution(traces)
        self._stack_execution_turns()
        self._routing_revision += 1
        self._routes_need_settle = False
        self._routes_need_full_settle = False
        self._routes_to_settle.clear()
        self._route_drag_positions.clear()
        self.fit_all()
        self._notify_flow_change()

    # --------------------------------------------------------------- dnd target
    def dnd_accept(self, source, event):
        return self

    def dnd_enter(self, source, event):
        self._set_preview(*self._drop_world(event), source.node_type)

    def dnd_motion(self, source, event):
        self._set_preview(*self._drop_world(event), source.node_type)

    def dnd_leave(self, source, event):
        self._clear_preview()

    def dnd_commit(self, source, event):
        self._clear_preview()
        return self.create_at(source.node_type, *self._drop_world(event))

    def create_at(self, node_type, wx, wy):
        w, h = theme.NODE_DIMS.get(
            node_type, (theme.CANVAS_NODE_W, theme.CANVAS_NODE_H))
        # Preserve the drop point when it is usable. Collision resolution
        # clamps cards to the current canvas and finds the nearest clear spot.
        x, y = snap_to_grid(wx - w / 2, wy - h / 2,
                            grid_x=grid_step(theme.CREATE_GRID_X, self.zoom),
                            grid_y=grid_step(theme.CREATE_GRID_Y, self.zoom))
        node = self.store.add(node_type, x, y, w, h)
        self._routing_revision += 1
        if node_type in CARD_TYPES:
            self._resolve_card_overlap(node.id)
        self.store.select(node.id)
        self._redraw()
        self._notify_flow_change()
        return node

    def _drop_world(self, event):
        sx = event.x_root - self.winfo_rootx()
        sy = event.y_root - self.winfo_rooty()
        return self.screen_to_world(sx, sy)

    def _set_preview(self, wx, wy, node_type="task"):
        self._clear_preview()
        w, h = theme.NODE_DIMS.get(
            node_type, (theme.CANVAS_NODE_W, theme.CANVAS_NODE_H))
        x, y = self.world_to_screen(*snap_to_grid(
            wx - w / 2, wy - h / 2,
            grid_x=grid_step(theme.CREATE_GRID_X, self.zoom),
            grid_y=grid_step(theme.CREATE_GRID_Y, self.zoom)))
        self._preview = self.create_rectangle(
            x, y, x + w * self.zoom, y + h * self.zoom,
            dash=(4, 3), outline=theme.SELECT, fill="", tags="preview")

    def _clear_preview(self):
        if self._preview is not None:
            self.delete(self._preview)
            self._preview = None
