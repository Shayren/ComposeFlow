"""Editable AI Execution node card (Plan / Action / Evaluation).

Mirrors ContextCard's chrome (editable header Entry, description Text,
[x] delete, divider style) with the pins read from the per-type
`theme.NODE_PINS` layout instead of a fixed single pin. Input dots accept
connections as targets; output (right-docked) dots start a connection,
with hover rings mirroring TaskCard. Connection validation is delegated to
the rules module via the canvas, not repeated here.

# ponytail: ExecutionCard mirrors TaskCard's pin interaction; merge into a
# shared pin renderer only if a 5th interactive card type appears.
"""

import tkinter as tk

from .title_marquee import TitleMarquee

from .. import theme
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class ExecutionCard(tk.Canvas):
    """Rounded card with semantic pins and read-only execution content."""

    PLACEHOLDER = "Enter the text...."

    def __init__(self, master, node_type, header="Plan Header",
                 get_node=None, **kw):
        self.node_type = node_type
        self._accent = theme.NODE_TYPES[node_type]["accent"]
        self._pins = theme.NODE_PINS[node_type]
        self.card_w, self.card_h = theme.NODE_DIMS[node_type]
        self._divider_y = max(pin_y for _port, _side, pin_y in self._pins) + 15
        self._box_top = self._divider_y + 22
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=self.card_w,
                         height=self.card_h, **kw)
        self.selected = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_connect_press = None
        self.on_data_change = None
        self._get_node = get_node
        self._port_highlights = {port: False
                                 for port, _side, _y in self._pins}
        self._zoom = 1.0
        node = get_node() if get_node else None
        self._read_only = bool(node and (node.system_generated or node.read_only))
        self._header_text = node.header if node else header
        self._description_text = (node.description if node and node.description
                                  else self.PLACEHOLDER)
        self.bind("<ButtonPress-1>", self._fwd_press)
        self.bind("<B1-Motion>", self._fwd_motion)
        self.bind("<ButtonRelease-1>", self._fwd_release)
        self._build()

    def _z(self, value):
        return value * self._zoom

    def _font(self, spec, slant=None):
        return scaled_font(self, spec, self._zoom, slant)

    def _build(self):
        if getattr(self, "header", None) is not None:
            self._header_text = self.header.get()
        if getattr(self, "description", None) is not None:
            value = self.description.get("1.0", "end-1c")
            if value:
                self._description_text = value
            self.description.destroy()
        self.delete("all")
        w, h = self.card_w, self.card_h
        self._body = self.create_polygon(
            rounded_rect_points(self._z(1), self._z(1), self._z(w - 2),
                                self._z(h - 2), self._z(10)),
            smooth=True, fill=theme.PANEL_BG_ALT,
            outline=theme.NODE_BORDER_NORMAL, width=1)
        self.create_rectangle(self._z(12), self._z(15), self._z(26),
                              self._z(29), fill=self._accent, outline="")
        self.header = tk.Entry(
            self, bg=theme.PANEL_BG_ALT, fg=theme.TEXT,
            readonlybackground=theme.PANEL_BG_ALT,
            insertbackground=theme.TEXT, bd=0, highlightthickness=0,
            font=self._font(theme.FONT_UI_BOLD), relief="flat")
        self.header.insert(0, self._header_text)
        self._title_marquee = TitleMarquee(self.header)
        if self._read_only:
            self.header.configure(state="readonly")
            self.header.bind("<ButtonPress-1>", self._fwd_press)
        else:
            self.header.bind("<KeyRelease>", self._sync_node_data)
        self._header_window = self.create_window(
            self._z(34), self._z(12), anchor="nw", window=self.header,
            width=round(self._z(w - 38 - 48)), height=round(self._z(20)))
        self._del = self.create_text(
            self._z(w - 16), self._z(22), text="[x]", anchor="e",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED,
            state="hidden" if self._read_only else "normal")
        self.tag_bind(self._del, "<Enter>",
                      lambda _e: self.itemconfigure(self._del, fill=theme.TEXT))
        self.tag_bind(self._del, "<Leave>",
                      lambda _e: self.itemconfigure(
                          self._del, fill=theme.TEXT_MUTED))

        self._header_divider = self.create_line(
            self._z(12), self._z(36), self._z(w - 12), self._z(36),
            fill=theme.BORDER)

        self._dots = []
        self._port_dots = {}
        for port, side, y in self._pins:
            out = side == "r"
            dot = self.create_oval(
                (self._z(w - 19) if out else self._z(12)),
                self._z(y - 3),
                (self._z(w - 12) if out else self._z(19)),
                self._z(y + 4),
                fill="",
                outline=theme.SEMANTIC_COLORS[
                    theme.PORT_SEMANTICS[(self.node_type, port)]],
                width=1.5)
            label = self.create_text(
                (self._z(w - 26) if out else self._z(26)), self._z(y),
                text=theme.PIN_LABELS[(self.node_type, port)],
                anchor="e" if out else "w",
                font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
            self._dots.append((dot, label, port))
            self._port_dots[port] = dot
            hover_ring = self.create_oval(
                (self._z(w - 22) if out else self._z(9)),
                self._z(y - 6),
                (self._z(w - 9) if out else self._z(22)),
                self._z(y + 7), fill="", outline=theme.WIRE_HOVER,
                width=2, state="hidden")
            self.tag_lower(hover_ring, dot)
            if not self._read_only:
                self.tag_bind(dot, "<Enter>",
                              lambda _e, ring=hover_ring: (
                                  self.itemconfigure(ring, state="normal"),
                                  self.configure(cursor="hand2")))
                self.tag_bind(dot, "<Leave>",
                              lambda _e, ring=hover_ring: (
                                  self.itemconfigure(ring, state="hidden"),
                                  self.configure(cursor="")))

        self._divider = self.create_line(
            self._z(12), self._z(self._divider_y),
            self._z(w - 12), self._z(self._divider_y),
            fill=theme.BORDER)

        self._description_label = self.create_text(
            self._z(12), self._z(self._divider_y + 12),
            text="EXECUTION DATA",
            anchor="w", font=self._font(theme.FONT_SMALL),
            fill=theme.TEXT_MUTED)
        self._description_box = self.create_polygon(
            rounded_rect_points(self._z(12), self._z(self._box_top),
                                self._z(w - 24),
                                self._z(h - self._box_top - 12), self._z(6)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self.description = tk.Text(
            self, bg=theme.PANEL_BG, fg=theme.TEXT_MUTED,
            insertbackground=theme.TEXT, bd=0, highlightthickness=0,
            relief="flat", font=self._font(theme.FONT_SMALL), wrap="word",
            undo=True, spacing1=2, spacing3=2,
            padx=max(1, round(self._z(4))),
            pady=max(1, round(self._z(4))))
        self.description.insert("1.0", self._description_text)
        if self._description_text == self.PLACEHOLDER:
            self.description.configure(
                font=self._font(theme.FONT_SMALL, slant="italic"))
        else:
            self.description.configure(fg=theme.TEXT)
        self.description.bind("<FocusIn>", self._on_focus_in)
        self.description.bind("<FocusOut>", self._on_focus_out)
        self.description.bind("<<Modified>>", self._description_modified)
        self.description.edit_modified(False)
        if self._read_only:
            self.description.configure(state="disabled")
            self.description.bind("<ButtonPress-1>", self._fwd_press)
        self._description_window = self.create_window(
            self._z(14), self._z(self._box_top + 2), anchor="nw",
            window=self.description,
            width=round(self._z(w - 28)),
            height=round(self._z(h - self._box_top - 16)))
        self.set_selected(self.selected)

        # Canonical zoom-1.0 geometry snapshot; apply_zoom re-derives every
        # item's coords from this (never from a previous zoom state).
        self._base_coords = {item: self.coords(item)
                             for item in self.find_all()}

    def apply_zoom(self, zoom):
        """Recompute card item coords from the zoom-1.0 base geometry.

        Never scales the previous state (cumulative float scaling leaves
        fractional coords at fractional zooms, clipping the body outline);
        every item is re-derived from `_base_coords` and rounded to whole
        pixels, so the result is idempotent and zoom == 1.0 reproduces the
        original build geometry exactly.
        """
        zoom = float(zoom)
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self._font(theme.FONT_UI_BOLD)
        self._font(theme.FONT_SMALL)
        self._font(theme.FONT_SMALL, slant="italic")
        for item, coords in self._base_coords.items():
            self.coords(item, *(coords if zoom == 1.0
                                else [round(v * zoom) for v in coords]))
        self.itemconfigure(self._header_window,
                           width=round((self.card_w - 38 - 48) * zoom),
                           height=round(20 * zoom))
        self.itemconfigure(self._description_window,
                           width=round((self.card_w - 28) * zoom),
                           height=round((self.card_h - self._box_top - 16)
                                        * zoom))
        self.description.configure(padx=max(1, round(4 * zoom)),
                                   pady=max(1, round(4 * zoom)))
        self.set_selected(self.selected)

    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfigure(
            self._body,
            outline=(self._accent if self.selected
                     else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def _on_delete_click(self, _event=None):
        if self.on_delete:
            self.on_delete()

    def _on_focus_in(self, _event=None):
        if self.description.get("1.0", "end-1c") == self.PLACEHOLDER:
            self.description.delete("1.0", "end")
            self.description.configure(fg=theme.TEXT,
                                       font=self._font(theme.FONT_SMALL))

    def _on_focus_out(self, _event=None):
        if not self.description.get("1.0", "end-1c").strip():
            self.description.delete("1.0", "end")
            self.description.insert("1.0", self.PLACEHOLDER)
            self.description.configure(
                fg=theme.TEXT_MUTED,
                font=self._font(theme.FONT_SMALL, slant="italic"))
        self._sync_node_data()

    def _description_modified(self, _event=None):
        if self.description.edit_modified():
            self.description.edit_modified(False)
            self._sync_node_data()

    def _sync_node_data(self, _event=None):
        if self._read_only:
            return
        node = self._get_node() if self._get_node else None
        if node is None:
            return
        header = self.header.get()
        description = self.description.get("1.0", "end-1c")
        if description == self.PLACEHOLDER:
            description = ""
        if (node.header, node.description) != (header, description):
            if node.header != header:
                node.auto_header = False
            node.header, node.description = header, description
            if self.on_data_change:
                self.on_data_change()

    def set_header(self, header):
        header = str(header or "")
        if self.header.get() == header:
            return
        # Read-only execution headers still need to refresh when a trace is
        # replaced and reuses the same generated node IDs.
        if self._read_only:
            self.header.configure(state="normal")
        self.header.delete(0, "end")
        self.header.insert(0, header)
        if self._read_only:
            self.header.configure(state="readonly")

    def set_execution_summary(self, summary):
        summary = str(summary or self.PLACEHOLDER)
        if self.description.get("1.0", "end-1c") == summary:
            return
        self.description.configure(state="normal")
        self.description.delete("1.0", "end")
        self.description.insert("1.0", summary)
        self.description.edit_modified(False)
        self.description.configure(
            state="disabled" if self._read_only else "normal")
        self._description_text = summary

    def set_port_highlight(self, port, highlighted, color=theme.SELECT):
        dot = self._port_dots.get(port)
        if dot is None:
            return
        self._port_highlights[port] = bool(highlighted)
        self.itemconfigure(dot,
                           outline=color if highlighted else "",
                           width=2 if highlighted else 0)

    def set_port_color(self, port, color):
        dot = self._port_dots.get(port)
        if dot is None:
            return
        self.itemconfigure(dot, fill=color)

    def set_port_connected(self, port, connected):
        dot = self._port_dots.get(port)
        if dot is None:
            return
        semantic = theme.PORT_SEMANTICS[(self.node_type, port)]
        color = theme.SEMANTIC_COLORS[semantic]
        self.itemconfigure(dot, fill=color if connected else "", outline=color)

    def _fwd_press(self, event):
        if self._read_only:
            if self.on_press:
                self.on_press(event.x_root, event.y_root,
                              getattr(event, "state", 0))
            return "break"
        radius = max(10.0, 12.0 * self._zoom)
        if self.on_connect_press is not None:
            for port, side, y in self._pins:
                if side != "r":
                    continue
                center_x = (self.card_w - 15.5) * self._zoom
                center_y = y * self._zoom
                if ((event.x - center_x) ** 2 + (event.y - center_y) ** 2
                        <= radius ** 2):
                    self.on_connect_press(port, event.x_root, event.y_root)
                    return "break"
        bounds = self.bbox(self._del)
        if (bounds is not None and bounds[0] <= event.x <= bounds[2]
                and bounds[1] <= event.y <= bounds[3]):
            self._on_delete_click()
            return "break"
        if self.on_press:
            self.on_press(event.x_root, event.y_root,
                          getattr(event, "state", 0))

    def _fwd_motion(self, event):
        if self.on_motion:
            self.on_motion(event.x_root, event.y_root)

    def _fwd_release(self, event):
        if self.on_release:
            self.on_release(event.x_root, event.y_root)
