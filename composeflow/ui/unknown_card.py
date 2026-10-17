"""Unknown node card: preserves unrecognized workflow node types.

Workflow JSON may contain nodes whose type is not one of the four known
content types. They are loaded into an UnknownCard so the document stays
visible and round-trippable: the title is editable, the original type
string is shown as a prominent badge ("Type: <type>"), and every preserved
extra property is listed as JSON text. Edges touching an unknown-type node
are dropped entirely, so the card has no connection affordances.
"""

import json
import tkinter as tk

from .. import theme
from .title_marquee import TitleMarquee
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class UnknownCard(tk.Canvas):
    """Read-mostly rounded card (230x170) for an unknown-type node."""

    def __init__(self, master, header="", get_node=None, node_type="unknown",
                 extra_props=None, **kw):
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=theme.UNKNOWN_W,
                         height=theme.UNKNOWN_H, **kw)
        self.selected = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_data_change = None
        self._get_node = get_node
        self._node_type = node_type
        node = get_node() if get_node else None
        self._props = dict(node.extra_props if node is not None
                           else (extra_props or {}))
        self._header_text = node.header if node is not None else header
        self._header_text = self._header_text or theme.UNKNOWN_LABEL
        self._zoom = 1.0
        self.bind("<ButtonPress-1>", self._fwd_press)
        self.bind("<B1-Motion>", self._fwd_motion)
        self.bind("<ButtonRelease-1>", self._fwd_release)
        self._build()

    def _z(self, value):
        return value * self._zoom

    def _scaled_font(self, spec, slant=None):
        return scaled_font(self, spec, self._zoom, slant)

    def _build(self):
        if getattr(self, "header", None) is not None:
            self._header_text = self.header.get()
            self.header.destroy()
        self.delete("all")
        w, h = theme.UNKNOWN_W, theme.UNKNOWN_H
        accent = theme.UNKNOWN_ACCENT
        self._body = self.create_polygon(
            rounded_rect_points(self._z(1), self._z(1), self._z(w - 2),
                                self._z(h - 2), self._z(10)),
            smooth=True, fill=theme.PANEL_BG_ALT,
            outline=theme.NODE_BORDER_NORMAL, width=1)
        self.create_rectangle(self._z(12), self._z(15), self._z(26),
                              self._z(29), fill=accent, outline="")
        self.header = tk.Entry(
            self, bg=theme.PANEL_BG_ALT, fg=theme.TEXT,
            insertbackground=theme.TEXT, bd=0, highlightthickness=0,
            font=self._scaled_font(theme.FONT_UI_BOLD), relief="flat")
        self.header.insert(0, self._header_text)
        self._title_marquee = TitleMarquee(self.header)
        self.header.bind("<KeyRelease>", self._sync_node_data)
        self._header_window = self.create_window(
            self._z(34), self._z(12), anchor="nw", window=self.header,
            width=round(self._z(w - 38 - 48)), height=round(self._z(20)))
        self._del = self.create_text(
            self._z(w - 16), self._z(22), text="[x]", anchor="e",
            font=self._scaled_font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self.tag_bind(self._del, "<Enter>",
                      lambda _e: self.itemconfigure(self._del, fill=theme.TEXT))
        self.tag_bind(self._del, "<Leave>",
                      lambda _e: self.itemconfigure(
                          self._del, fill=theme.TEXT_MUTED))
        self._header_divider = self.create_line(
            self._z(12), self._z(36), self._z(w - 12), self._z(36),
            fill=theme.BORDER)

        self._divider = self.create_line(
            self._z(12), self._z(64), self._z(w - 12), self._z(64),
            fill=theme.BORDER)

        # Prominent badge naming the unrecognized type.
        self._badge = self.create_text(
            self._z(12), self._z(80), text=f"Type: {self._node_type}",
            anchor="w", font=self._scaled_font(theme.FONT_UI_BOLD),
            fill=accent)
        if self._props:
            self._props_text = self.create_text(
                self._z(12), self._z(102), anchor="nw",
                text=json.dumps(self._props, indent=1),
                width=round(self._z(w - 24)),
                font=self._scaled_font(theme.FONT_SMALL),
                fill=theme.TEXT_MUTED)
        else:
            self._props_text = None
        self.set_selected(self.selected)

        # Canonical zoom-1.0 geometry snapshot; apply_zoom re-derives every
        # item's coords from this (never from a previous zoom state).
        self._base_coords = {item: self.coords(item)
                             for item in self.find_all()}

    def apply_zoom(self, zoom):
        """Recompute card item coords from the zoom-1.0 base geometry,
        following the same idempotent, integer-rounded pattern as the other
        cards (never scales the previous state)."""
        zoom = float(zoom)
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self._scaled_font(theme.FONT_UI_BOLD)
        self._scaled_font(theme.FONT_SMALL)
        for item, coords in self._base_coords.items():
            self.coords(item, *(coords if zoom == 1.0
                                else [round(v * zoom) for v in coords]))
        self.itemconfigure(self._header_window,
                           width=round((theme.UNKNOWN_W - 38 - 48) * zoom),
                           height=round(20 * zoom))
        if self._props_text is not None:
            self.itemconfigure(self._props_text,
                               width=round((theme.UNKNOWN_W - 24) * zoom))
        self.set_selected(self.selected)

    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfigure(
            self._body,
            outline=(theme.UNKNOWN_ACCENT if self.selected
                     else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def set_header(self, header):
        if not header or self.header.get() == header:
            return
        self.header.delete(0, "end")
        self.header.insert(0, header)

    def _sync_node_data(self, _event=None):
        node = self._get_node() if self._get_node else None
        if node is None:
            return
        header = self.header.get()
        if node.header != header:
            node.auto_header = False
            node.header = header
            if self.on_data_change:
                self.on_data_change()

    def _on_delete_click(self, _event=None):
        if self.on_delete:
            self.on_delete()

    def _fwd_press(self, event):
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
