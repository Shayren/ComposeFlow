"""ComposeFlow task-node card.

A canvas-drawn rounded card for TASK nodes on the flow canvas. Decoration
(body, header icon, connection dots, divider, labels, the rounded
description container, the [x] control) is canvas items; only the editable
header Entry and the description Text are embedded via create_window. The
four colored dots are two input rows left-docked (Data @44, Context @61)
and two output rows right-docked (Result @44, Request @61). Inputs accept
connections as targets; the Result/Request output dots start a connection
(Result -> Task/Response, Request -> Plan). Pointer events that land on
the free card surface (not the embedded widgets) are forwarded to the flow
canvas through the on_press/on_motion/on_release callbacks; on_delete
removes the node.

Zoom: `_build()` draws everything from the 100% theme constants through
`_z()` (value * zoom) and scaled fonts; `apply_zoom(z)` recomputes item
coords from a zoom-1.0 base snapshot (rounded to device pixels) and resizes
embedded widgets in place, without rebuilding them.
"""

import tkinter as tk

from .title_marquee import TitleMarquee

from .. import theme
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class TaskCard(tk.Canvas):
    """Rounded task-node card (230x196) embedded in the flow canvas."""

    PLACEHOLDER = "Enter the text...."

    def __init__(self, master, header="Task Header", get_node=None, **kw):
        # The card window fills a rectangle; matching the canvas background
        # makes the area outside the rounded body look transparent.
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=theme.TASK_CARD_W,
                         height=theme.TASK_CARD_H, **kw)

        self.selected = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_connect_press = None
        self.on_data_change = None
        self._get_node = get_node
        self._port_highlights = {
            port: False for port, _side, _y in theme.NODE_PINS["task"]}
        self._input_highlighted = False  # retained for existing UI probes
        self._zoom = 1.0
        self._zoom_windows = []
        self._zoom_text_padding = []
        # Seed editable controls from flow state, including when a node is
        # rendered again after a type change.
        node = get_node() if get_node is not None else None
        self._entry_text = node.header if node is not None else header
        self._desc_text = (node.description if node and node.description
                           else self.PLACEHOLDER)

        # Free-surface drag forwarding (embedded widgets swallow events).
        self.bind("<ButtonPress-1>", self._fwd_press)
        self.bind("<B1-Motion>", self._fwd_motion)
        self.bind("<ButtonRelease-1>", self._fwd_release)

        self._build()
        self._zoom_windows = [
            (self._entry_window, theme.TASK_CARD_W - 38 - 48, 20),
            (self._description_window, theme.TASK_CARD_W - 28,
             theme.TASK_CARD_H - 132),
        ]
        self._zoom_text_padding = [(self.description, 4, 4)]

    # ----------------------------------------------------------- zoom scale
    def _z(self, v):
        return v * self._zoom

    def _scaled_font(self, spec, slant=None):
        """Return a shared font sized for this card's current zoom."""
        return scaled_font(self, spec, self._zoom, slant)

    def apply_zoom(self, z):
        """Recompute card item coords from the zoom-1.0 base geometry.

        Never scales the previous state (cumulative float scaling leaves
        fractional coords at fractional zooms, clipping the body outline);
        every item is re-derived from `_base_coords` and rounded to whole
        pixels, so the result is idempotent and z == 1.0 reproduces the
        original build geometry exactly.
        """
        z = float(z)
        if z == self._zoom:
            return
        self._zoom = z
        self._scaled_font(theme.FONT_UI_BOLD)
        self._scaled_font(theme.FONT_SMALL)
        self._scaled_font(theme.FONT_SMALL, slant="italic")
        for item, coords in self._base_coords.items():
            self.coords(item, *(coords if z == 1.0
                                else [round(v * z) for v in coords]))
        for item, width, height in self._zoom_windows:
            self.itemconfigure(item, width=round(width * z),
                               height=round(height * z))
        for widget, padx, pady in self._zoom_text_padding:
            widget.configure(padx=max(1, round(padx * z)),
                             pady=max(1, round(pady * z)))
        self.set_selected(self.selected)

    # -------------------------------------------------------------- build
    def _build(self):
        # capture user content before tearing down a previous build
        if getattr(self, "entry", None) is not None and self.entry.winfo_exists():
            self._entry_text = self.entry.get()
        if (getattr(self, "description", None) is not None
                and self.description.winfo_exists()):
            self._desc_text = self.description.get("1.0", "end-1c")
        for name in ("entry", "description"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
                setattr(self, name, None)
        self.delete("all")

        w, h = theme.TASK_CARD_W, theme.TASK_CARD_H
        accent = theme.NODE_TYPES["task"]["accent"]

        # Body: one smoothed rounded-rect polygon with a 1px gray border
        # (input accent at 2px when selected; scaled in set_selected).
        self._body = self.create_polygon(
            rounded_rect_points(self._z(1), self._z(1),
                                self._z(w - 2), self._z(h - 2), self._z(10)),
            smooth=True, fill=theme.PANEL_BG_ALT,
            outline=theme.NODE_BORDER_NORMAL, width=1)

        # Header row: green square icon, editable title Entry, [x] delete.
        # The 14x14 square is centered on the entry's vertical center (y 22).
        self.create_rectangle(self._z(12), self._z(15),
                              self._z(26), self._z(29),
                              fill=accent, outline="")
        self.entry = tk.Entry(self, bg=theme.PANEL_BG_ALT, fg=theme.TEXT,
                              insertbackground=theme.TEXT, bd=0,
                              highlightthickness=0,
                              font=self._scaled_font(theme.FONT_UI_BOLD),
                              relief="flat")
        self.entry.insert(0, self._entry_text)
        self._title_marquee = TitleMarquee(self.entry)
        self.entry.bind("<KeyRelease>", self._sync_node_data)
        self._entry_window = self.create_window(
            self._z(34), self._z(12), anchor="nw",
            width=round(self._z(w - 38 - 48)),
            height=round(self._z(20)), window=self.entry)

        self._del = self.create_text(self._z(w - 16), self._z(22),
                                     text="[x]", anchor="e",
                                     font=self._scaled_font(theme.FONT_SMALL),
                                     fill=theme.TEXT_MUTED)
        # Tk 8.6 canvas items have no `cursor` option: swap the widget
        # cursor while the pointer is over the [x] item instead.
        self.tag_bind(self._del, "<Button-1>", self._on_delete_click)
        self.tag_bind(self._del, "<Enter>",
                      lambda e: (self.itemconfig(self._del, fill=theme.TEXT),
                                 self.configure(cursor="hand2")))
        self.tag_bind(self._del, "<Leave>",
                      lambda e: (self.itemconfig(self._del,
                                                 fill=theme.TEXT_MUTED),
                                 self.configure(cursor="")))

        self._header_divider = self.create_line(
            self._z(12), self._z(36), self._z(w - 12), self._z(36),
            fill=theme.BORDER)

        # User pins describe task intent. After/Next are neutral square
        # CONTROL pins; every other pin's color follows its artifact type.
        self._dots = []
        self._port_dots = {}
        for port, side, y in theme.NODE_PINS["task"]:
            out = side == "r"
            semantic = theme.PORT_SEMANTICS[("task", port)]
            x0, y0 = ((w - 19, y - 3) if out else (12, y - 3))
            x1, y1 = ((w - 12, y + 4) if out else (19, y + 4))
            shape = self.create_rectangle if semantic == "control" else self.create_oval
            dot = shape(
                self._z(x0), self._z(y0), self._z(x1), self._z(y1),
                fill="", outline=theme.SEMANTIC_COLORS[semantic], width=1.5)
            lbl = self.create_text(
                self._z(w - 26) if out else self._z(26), self._z(y),
                text=theme.PIN_LABELS[("task", port)],
                anchor="e" if out else "w",
                font=self._scaled_font(theme.FONT_SMALL),
                fill=theme.TEXT_MUTED)
            self._dots.append((dot, lbl, port))
            self._port_dots[port] = dot
            hover_ring = self.create_oval(
                (self._z(w - 22) if out else self._z(9)),
                self._z(y - 6),
                (self._z(w - 9) if out else self._z(22)),
                self._z(y + 7), fill="", outline=theme.WIRE_HOVER,
                width=2, state="hidden")
            self.tag_lower(hover_ring, dot)
            self.tag_bind(dot, "<Enter>",
                          lambda _e, ring=hover_ring: (
                              self.itemconfigure(ring, state="normal"),
                              self.configure(cursor="hand2")))
            self.tag_bind(dot, "<Leave>",
                          lambda _e, ring=hover_ring: (
                              self.itemconfigure(ring, state="hidden"),
                              self.configure(cursor="")))
            if port == "data":
                self._input_dot = dot
            elif port == "context":
                self._context_dot = dot
            elif port == "contract":
                self._task_output_dot = dot

        # Divider between the connection rows and the description area.
        self._divider = self.create_line(self._z(12), self._z(94),
                                         self._z(w - 12), self._z(94),
                                         fill=theme.BORDER)

        # Description area: muted caption above a rounded "recessed"
        # container (PANEL_BG, darker than the body's PANEL_BG_ALT) drawn
        # on the canvas. The Text embeds inside it with no native border,
        # so the rounded polygon reads as the editable field's border.
        self._desc_label = self.create_text(
            self._z(12), self._z(106), text="Task description:", anchor="w",
            font=self._scaled_font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._desc_box = self.create_polygon(
            rounded_rect_points(self._z(12), self._z(116),
                                self._z(w - 24), self._z(h - 128), self._z(6)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self.description = tk.Text(self, bg=theme.PANEL_BG, fg=theme.TEXT,
                                   insertbackground=theme.TEXT, bd=0,
                                   highlightthickness=0, relief="flat",
                                   font=self._scaled_font(theme.FONT_SMALL),
                                   wrap="word",
                                   undo=True,
                                   spacing1=2, spacing3=2,
                                   padx=max(1, round(self._z(4))),
                                   pady=max(1, round(self._z(4))))
        # tkinter Font drops **options when font= is given, so derive the
        # placeholder from the scaled base font and italicize it separately.
        self._placeholder_font = self._scaled_font(theme.FONT_SMALL,
                                                   slant="italic")
        self.description.bind("<FocusIn>", self._on_focus_in)
        self.description.bind("<FocusOut>", self._on_focus_out)
        text = self._desc_text if self._desc_text else self.PLACEHOLDER
        self.description.insert("1.0", text)
        if text == self.PLACEHOLDER:
            self.description.configure(fg=theme.TEXT_MUTED,
                                       font=self._placeholder_font)
        else:
            self.description.configure(fg=theme.TEXT,
                                       font=self._scaled_font(theme.FONT_SMALL))
        self.description.bind("<<Modified>>", self._description_modified)
        self.description.edit_modified(False)
        self._description_window = self.create_window(
            self._z(14), self._z(118), anchor="nw",
            width=round(self._z(w - 28)),
            height=round(self._z(h - 132)), window=self.description)

        self.set_selected(self.selected)

        # Canonical zoom-1.0 geometry snapshot; apply_zoom re-derives every
        # item's coords from this (never from a previous zoom state).
        self._base_coords = {item: self.coords(item)
                             for item in self.find_all()}

    # -------------------------------------------------------------- events
    def _fwd_press(self, event):
        # Contract and Next are the user-authored output pins.
        radius = max(10.0, 12.0 * self._zoom)
        if self.on_connect_press is not None:
            context_x = 15.5 * self._zoom
            context_y = 61.0 * self._zoom
            if ((event.x - context_x) ** 2 + (event.y - context_y) ** 2
                    <= radius ** 2):
                self.on_connect_press("context", event.x_root, event.y_root)
                return "break"
            for port, y in (("contract", 44.0), ("next", 61.0),
                            ("task", 78.0)):
                center_x = (theme.TASK_CARD_W - 15.5) * self._zoom
                center_y = y * self._zoom
                if ((event.x - center_x) ** 2 + (event.y - center_y) ** 2
                        <= radius ** 2):
                    self.on_connect_press(port, event.x_root, event.y_root)
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

    def _description_modified(self, _event=None):
        if self.description.edit_modified():
            self.description.edit_modified(False)
            self._sync_node_data()

    def _sync_node_data(self, _event=None):
        node = self._get_node() if self._get_node is not None else None
        if node is None:
            return
        header = self.entry.get()
        description = self.description.get("1.0", "end-1c")
        if description == self.PLACEHOLDER:
            description = ""
        if (node.header, node.description) == (header, description):
            return
        if node.header != header:
            node.auto_header = False
        node.header, node.description = header, description
        if self.on_data_change:
            self.on_data_change()

    def set_header(self, header):
        if self.entry.get() == header:
            return
        self.entry.delete(0, "end")
        self.entry.insert(0, header)

    def _on_delete_click(self, event=None):
        if self.on_delete:
            self.on_delete()

    # ------------------------------------------------------------ selection
    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfig(
            self._body,
            outline=(theme.NODE_TYPES["task"]["accent"] if self.selected
                     else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def set_port_highlight(self, port, highlighted, color=theme.SELECT):
        dot = self._port_dots.get(port)
        if dot is None:
            return
        self._port_highlights[port] = bool(highlighted)
        if port == "data":
            self._input_highlighted = bool(highlighted)
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
        semantic = theme.PORT_SEMANTICS[("task", port)]
        color = theme.SEMANTIC_COLORS[semantic]
        self.itemconfigure(dot, fill=color if connected else "", outline=color)

    def set_input_highlight(self, highlighted, color=theme.SELECT):
        self.set_port_highlight("data", highlighted, color)

    # ---------------------------------------------------------- placeholder
    def _on_focus_in(self, event):
        if self.description.get("1.0", "end-1c") == self.PLACEHOLDER:
            self.description.delete("1.0", "end")
            self.description.configure(
                fg=theme.TEXT,
                font=self._scaled_font(theme.FONT_SMALL))

    def _on_focus_out(self, event):
        if not self.description.get("1.0", "end-1c"):
            self.description.insert("1.0", self.PLACEHOLDER)
            self.description.configure(fg=theme.TEXT_MUTED,
                                       font=self._placeholder_font)
        self._sync_node_data()
