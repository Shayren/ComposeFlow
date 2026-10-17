"""ComposeFlow shell: header, node library, flow canvas, and JSON viewer."""

import json
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox

from .. import theme
from ..compose_cli import ComposeValidationError
from ..flow_json import flow_to_json, parse_flow_json
from ..run_files import save_launch_workflow
from .future_panel import FuturePanel
from .header import Header
from .node_list import NodeList
from .flow_canvas import FlowCanvas


class ComposeFlowApp(tk.Tk):
    def __init__(self, run_id=None, output_path=None):
        super().__init__()
        self.run_id = run_id or uuid.uuid4().hex
        self.output_path = output_path or (
            Path.cwd() / ".composeflow" / "runs" / self.run_id / "workflow.json")
        self.launched_path = None
        self.report_mode = False
        self.title("ComposeFlow")
        self.minsize(960, 600)
        self.configure(bg=theme.BG)
        self._col_fracs = theme.COL_RATIO
        self._library_collapsed = False
        self._future_collapsed = False
        self._anim_job = None
        self._center(1280, 800)
        self._build()

    def collapse_library(self):
        """Node list minimizes: animate the library column down to a narrow
        rail (ratio-scaled, floored at NodeList.RAIL_MIN so the > handle
        fits fully on the rail and never overlaps the canvas)."""
        self._library_collapsed = True
        self._animate_col_to()

    def expand_library(self):
        """Restore the node list to its previous width."""
        self._library_collapsed = False
        self._animate_col_to()

    def collapse_future(self):
        """JSON/user-prompt strip minimizes: animate the panel down to a
        narrow rail (ratio-scaled, floored at FuturePanel.RAIL_MIN so the
        < handle fits fully on the rail and never overlaps the canvas);
        the node list stays put."""
        self._future_collapsed = True
        self._animate_col_to()

    def expand_future(self):
        """Restore the JSON panel to its previous width."""
        self._future_collapsed = False
        self._animate_col_to()

    def _toggle_panels_and_fit(self):
        collapse = not (self.node_list.collapsed
                        and self.future_strip.collapsed)
        for panel in (self.node_list, self.future_strip):
            if panel.collapsed != collapse:
                panel.toggle_compact()

    # --------------------------------------------------- panel collapse
    def _column_fractions(self):
        left = (theme.COL_RATIO_COLLAPSED[0] if self._library_collapsed
                else theme.COL_RATIO[0])
        right = (theme.COL_RATIO_RIGHT_COLLAPSED[2] if self._future_collapsed
                 else theme.COL_RATIO[2])
        return (left, sum(theme.COL_RATIO) - left - right, right)

    def _column_widths(self, window_width, fracs):
        total = sum(fracs)
        widths = [round(window_width * frac / total) for frac in fracs]
        if self._library_collapsed:
            widths[0] = max(widths[0], NodeList.RAIL_MIN)
        if self._future_collapsed:
            widths[2] = max(widths[2], FuturePanel.RAIL_MIN)
        widths[1] = max(0, window_width - widths[0] - widths[2])
        return widths

    def _animate_col_to(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        self.canvas.set_layout_frozen(True)
        w = self.winfo_width()
        fracs = self._column_fractions()
        target = self._column_widths(w, fracs)
        start = []
        for col, frac in enumerate(fracs):
            value = self.grid_columnconfigure(col, "minsize")
            start.append(float(value) if value
                         else w * frac / sum(fracs))
        steps, interval = 10, 20

        def step(i=0):
            if i >= steps:
                self._anim_job = None
                self._col_fracs = fracs
                self._apply_col_ratio()
                self.update_idletasks()
                self.node_list.set_animating(False)
                self.future_strip.set_animating(False)
                self.update_idletasks()
                self.canvas.set_layout_frozen(False)
                self.canvas.fit_all()
                return
            left = int(round(start[0] + (target[0] - start[0]) * i / steps))
            right = int(round(start[2] + (target[2] - start[2]) * i / steps))
            self.grid_columnconfigure(0, minsize=left)
            self.grid_columnconfigure(1, minsize=max(0, w - left - right))
            self.grid_columnconfigure(2, minsize=right)
            self._anim_job = self.after(interval, step, i + 1)

        step()

    def _apply_col_ratio(self, event=None):
        """Pin the three columns to an exact width split. Tk's grid weight
        only distributes *spare* space, so the ratio is enforced with
        per-column minsize, recomputed whenever the window resizes. The
        canvas column absorbs the remainder (the rail floor can push col0
        above its proportional share), so the three columns ALWAYS total
        the window width exactly — the JSON panel never shifts."""
        w = self.winfo_width()
        if w < 10 or self._anim_job is not None:
            return
        self._col_fracs = self._column_fractions()
        minsizes = self._column_widths(w, self._col_fracs)
        for col, minsize in enumerate(minsizes):
            self.grid_columnconfigure(col, minsize=minsize)

    def _center(self, w, h):
        """Place the window centered where the pointer is (always on the
        monitor the user is actually looking at). Fall back to the virtual
        screen center if the pointer position is unavailable."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        px, py = self.winfo_pointerx(), self.winfo_pointery()
        if not (0 <= px < sw and 0 <= py < sh):
            px, py = sw // 2, sh // 2
        x = max(0, min(px - w // 2, sw - w))
        y = max(0, min(py - h // 2, sh - h))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        # Three columns split by a strict 1 : 6 : 3 WIDTH ratio:
        # node list : flow canvas : JSON structure.
        self.grid_rowconfigure(1, weight=1)
        for col, weight in ((0, 15), (1, 55), (2, 30)):
            self.grid_columnconfigure(col, weight=weight)
        self._apply_col_ratio()
        self.bind("<Configure>", self._apply_col_ratio)

        # Header: compact top strip spanning the full width.
        self.header = Header(self)
        self.header.grid(row=0, column=0,
                         columnspan=3, sticky="ew")

        # Node library: left panel.
        self.node_list = NodeList(self)
        self.node_list.grid(row=1, column=0, sticky="nsew")

        # Flow canvas: fills the rest of the middle row.
        self.canvas = FlowCanvas(self)
        self.canvas.grid(row=1, column=1, sticky="nsew")
        self.canvas.on_fit_request = self._toggle_panels_and_fit

        # Editable semantic Flow JSON panel at the right-side 3/10 column.
        self.future_strip = FuturePanel(self)
        self.future_strip.grid(row=1, column=2, rowspan=2, sticky="nsew")
        self.future_strip.on_launch = self._launch_workflow
        self.canvas.on_flow_change = self._refresh_flow_json
        self.canvas.on_ai_node_interaction = (
            self.future_strip.show_ai_execution_notice)
        self.node_list.on_ai_node_interaction = (
            self.future_strip.show_ai_execution_notice)
        self.future_strip.on_json_change = self._apply_flow_json
        self._refresh_flow_json()

    def destroy(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        super().destroy()

    def reset_for_test(self):
        """Rebuild the app's content while keeping its window alive."""
        geometry = self.geometry()
        # Let queued widget events finish while their canvas/card bindings are
        # still alive; otherwise a late drag event can target a destroyed canvas.
        self.update()
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        self.unbind("<Configure>")
        progress_window = getattr(self, "test_bench_window", None)
        for child in self.winfo_children():
            if child is progress_window:
                continue
            child.destroy()
        self._col_fracs = theme.COL_RATIO
        self._library_collapsed = False
        self._future_collapsed = False
        self.geometry(geometry)
        self._build()
        self.update_idletasks()

    def _refresh_flow_json(self):
        self.future_strip.set_json(flow_to_json(self.canvas.store))

    def _launch_workflow(self):
        if self.report_mode:
            return
        self.future_strip.set_launch_busy(True)
        self.update_idletasks()
        draft = self.future_strip.viewer.get("1.0", "end-1c")
        try:
            applied = self._apply_flow_json(draft)
            if applied is not True:
                raise ComposeValidationError(str(applied))
            if "schemaVersion" not in json.loads(draft):
                draft = flow_to_json(self.canvas.store)
            save_launch_workflow(draft, self.output_path)
        except (ComposeValidationError, ValueError, OSError) as exc:
            self.future_strip.set_validation_status(str(exc))
            messagebox.showerror("Cannot launch workflow", str(exc), parent=self)
            self.future_strip.set_launch_busy(False)
            return
        self.launched_path = self.output_path
        self.after_idle(self.destroy)

    def show_report(self, document):
        result = self._apply_flow_json(document, auto_layout=True)
        if result is not True:
            raise ComposeValidationError(str(result))
        self.future_strip.set_json(document)
        self.report_mode = True
        self.future_strip.set_launch_busy(True)
        self.title("ComposeFlow — Report mode")

    def _apply_flow_json(self, text, auto_layout=False):
        try:
            if text == "":
                workflow = {"nodes": [], "edges": []}
            else:
                current_node_ids = {node.id for node in self.canvas.store.all()}
                workflow = parse_flow_json(text, current_node_ids)
        except ValueError as exc:
            return str(exc)
        execution = workflow.get("execution", {})
        traces = execution.get("traces", {})
        if auto_layout:
            self.canvas.apply_workflow(
                workflow, auto_layout=True, execution_traces=traces)
        else:
            self.canvas.apply_workflow(workflow)
            self.canvas.apply_execution(traces)
        return True
