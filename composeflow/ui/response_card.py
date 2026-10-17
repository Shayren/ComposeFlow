"""Response node card with visual format and style controls."""

import tkinter as tk

from .title_marquee import TitleMarquee

from .. import theme
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class ResponseCard(tk.Canvas):
    """Rounded Response card; controls are visual state only."""

    FORMATS = ("Markdown", "Table", "JSON")
    STYLES = ("Concise", "Structure", "Technical")
    FORMAT_X = (14, 112, 210)
    STYLE_X = (14, 14, 14)
    STYLE_Y = (164, 188, 212)

    def __init__(self, master, header="Response 1", get_node=None, **kw):
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=theme.RESPONSE_CARD_W,
                         height=theme.RESPONSE_CARD_H, **kw)
        self.selected = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_connect_press = None
        self.on_data_change = None
        self._get_node = get_node
        self._zoom = 1.0
        node = get_node() if get_node else None
        self.format = node.response_format if node else "Markdown"
        self.styles = set(node.response_styles if node else ())
        self._header_text = node.header if node else header
        self._input_highlighted = False
        self._result_summary = None
        self.bind("<ButtonPress-1>", self._fwd_press)
        self.bind("<B1-Motion>", self._fwd_motion)
        self.bind("<ButtonRelease-1>", self._fwd_release)
        self._build()

    def _z(self, value):
        return value * self._zoom

    def _font(self, spec):
        return scaled_font(self, spec, self._zoom)

    def _build(self):
        w, h = theme.RESPONSE_CARD_W, theme.RESPONSE_CARD_H
        accent = theme.NODE_TYPES["response"]["accent"]
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
            font=self._font(theme.FONT_UI_BOLD), relief="flat")
        self.header.insert(0, self._header_text)
        self._title_marquee = TitleMarquee(self.header)
        self.header.bind("<KeyRelease>", self._sync_node_data)
        self._header_window = self.create_window(
            self._z(34), self._z(12), anchor="nw", window=self.header,
            width=round(self._z(w - 38 - 48)), height=round(self._z(20)))
        self._del = self.create_text(
            self._z(w - 16), self._z(22), text="[x]", anchor="e",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self.tag_bind(self._del, "<Enter>",
                      lambda _e: self.itemconfigure(self._del, fill=theme.TEXT))
        self.tag_bind(self._del, "<Leave>",
                      lambda _e: self.itemconfigure(
                          self._del, fill=theme.TEXT_MUTED))

        self._header_divider = self.create_line(
            self._z(12), self._z(36), self._z(w - 12), self._z(36),
            fill=theme.BORDER)

        self._port_dots = {}
        for port, _side, y in theme.NODE_PINS["response"]:
            semantic = theme.PORT_SEMANTICS[("response", port)]
            color = theme.SEMANTIC_COLORS[semantic]
            self._port_dots[port] = self.create_oval(
                self._z(12), self._z(y - 3.5), self._z(19), self._z(y + 3.5),
                fill="", outline=color, width=1.5)
        self._pin_dot = self._port_dots["contract"]
        self._pin_hover_ring = self.create_oval(
            self._z(9), self._z(54.5),
            self._z(22), self._z(67.5), fill="",
            outline=theme.WIRE_HOVER, width=2, state="hidden")
        self.tag_lower(self._pin_hover_ring, self._pin_dot)
        self.tag_bind(self._pin_dot, "<Enter>",
                      lambda _e: (self.itemconfigure(
                          self._pin_hover_ring, state="normal"),
                          self.configure(cursor="hand2")))
        self.tag_bind(self._pin_dot, "<Leave>",
                      lambda _e: (self.itemconfigure(
                          self._pin_hover_ring, state="hidden"),
                          self.configure(cursor="")))
        self._pin_label = self.create_text(
            self._z(26), self._z(61),
            text=theme.PIN_LABELS[("response", "contract")], anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._result_label = self.create_text(
            self._z(26), self._z(44),
            text=theme.PIN_LABELS[("response", "result")], anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._divider = self.create_line(
            self._z(12), self._z(80), self._z(w - 12), self._z(80),
            fill=theme.BORDER)
        self._format_label = self.create_text(
            self._z(12), self._z(94), text="FORMAT", anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._style_label = self.create_text(
            self._z(12), self._z(140), text="STYLE", anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._radio_items = []
        for option, x in zip(self.FORMATS, self.FORMAT_X):
            outer = self.create_oval(
                self._z(x), self._z(108), self._z(x + 11), self._z(119),
                fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
            inner = self.create_oval(
                self._z(x + 3), self._z(111), self._z(x + 8), self._z(116),
                fill="", outline="")
            label = self.create_text(
                self._z(x + 15), self._z(113.5), text=option, anchor="w",
                font=self._font(theme.FONT_SMALL), fill=theme.TEXT)
            self._radio_items.append((option, x, outer, inner, label))
        self._check_items = []
        for option, x, y in zip(self.STYLES, self.STYLE_X, self.STYLE_Y):
            box = self.create_rectangle(
                self._z(x), self._z(y - 5), self._z(x + 11), self._z(y + 6),
                fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
            tick = self.create_line(
                self._z(x + 2), self._z(y), self._z(x + 5), self._z(y + 3),
                self._z(x + 9), self._z(y - 3), fill="", width=2,
                capstyle=tk.ROUND, joinstyle=tk.ROUND)
            label = self.create_text(
                self._z(x + 15), self._z(y + 0.5), text=option, anchor="w",
                font=self._font(theme.FONT_SMALL), fill=theme.TEXT)
            self._check_items.append((option, x, box, tick, label))
        self._refresh_controls()
        self._summary_divider = self.create_line(
            12, 234, w - 12, 234, fill=theme.BORDER, state="hidden")
        self._summary_label = self.create_text(
            12, 250, text="SUMMARY RESULT", anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED,
            state="hidden")
        summary_frame = tk.Frame(self, bg=theme.PANEL_BG,
                                 highlightbackground=theme.BORDER,
                                 highlightthickness=1)
        self._summary_text = tk.Text(
            summary_frame, wrap="word", bg=theme.PANEL_BG, fg=theme.TEXT,
            font=self._font(theme.FONT_UI), relief="flat", bd=0,
            padx=6, pady=6, highlightthickness=0, state="disabled")
        self._summary_text.pack(fill="both", expand=True)
        self._summary_window = self.create_window(
            12, 266, anchor="nw", window=summary_frame,
            width=w - 24, height=108, state="hidden")
        self.header.bind("<KeyRelease>", self._sync_node_data)
        self.set_selected(self.selected)

        # Canonical zoom-1.0 geometry snapshot; apply_zoom re-derives every
        # item's coords from this (never from a previous zoom state).
        self._base_coords = {item: self.coords(item)
                             for item in self.find_all()}

    def _sync_node_data(self, _event=None):
        node = self._get_node() if self._get_node else None
        if node is None:
            return
        styles = [value for value in self.STYLES if value in self.styles]
        header = self.header.get()
        if (node.header, node.response_format, node.response_styles) != (
                header, self.format, styles):
            if node.header != header:
                node.auto_header = False
            node.header = header
            node.response_format = self.format
            node.response_styles = styles
            if self.on_data_change:
                self.on_data_change()

    def set_result_summary(self, summary):
        if summary == self._result_summary:
            return
        self._result_summary = summary
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        self._summary_text.insert("1.0", summary or "")
        self._summary_text.configure(state="disabled")
        self._summary_text.yview_moveto(0)
        state = "normal" if summary is not None else "hidden"
        for item in (self._summary_divider, self._summary_label,
                     self._summary_window):
            self.itemconfigure(item, state=state)
        height = (theme.RESPONSE_RESULT_CARD_H if summary is not None
                  else theme.RESPONSE_CARD_H)
        coords = rounded_rect_points(1, 1, theme.RESPONSE_CARD_W - 2,
                                     height - 2, 10)
        self._base_coords[self._body] = coords
        self.coords(self._body, *(coords if self._zoom == 1.0 else
                                 [round(v * self._zoom) for v in coords]))
        self.configure(height=round(height * self._zoom))

    def set_header(self, header):
        if self.header.get() == header:
            return
        self.header.delete(0, "end")
        self.header.insert(0, header)

    def set_input_highlight(self, highlighted, color=theme.SELECT):
        self._input_highlighted = bool(highlighted)
        self.itemconfigure(self._pin_dot,
                           outline=color if highlighted else "",
                           width=2 if highlighted else 0)

    def set_port_highlight(self, port, highlighted, color=theme.SELECT):
        dot = self._port_dots.get(port)
        if dot is not None:
            semantic = theme.PORT_SEMANTICS[("response", port)]
            default = theme.SEMANTIC_COLORS[semantic]
            self.itemconfigure(dot, outline=color if highlighted else default,
                               width=2 if highlighted else 1.5)

    def set_port_color(self, port, color):
        dot = self._port_dots.get(port)
        if dot is not None:
            self.itemconfigure(dot, fill=color)

    def set_port_connected(self, port, connected):
        dot = self._port_dots.get(port)
        if dot is None:
            return
        semantic = theme.PORT_SEMANTICS[("response", port)]
        color = theme.SEMANTIC_COLORS[semantic]
        self.itemconfigure(dot, fill=color if connected else "", outline=color)

    def _refresh_controls(self):
        accent = theme.NODE_TYPES["response"]["accent"]
        for option, _x, outer, inner, _label in self._radio_items:
            selected = option == self.format
            self.itemconfigure(outer, outline=accent if selected else theme.BORDER,
                               width=1)
            self.itemconfigure(inner, fill=accent if selected else "")
        for option, _x, box, tick, _label in self._check_items:
            checked = option in self.styles
            self.itemconfigure(box, fill=accent if checked else theme.PANEL_BG,
                               outline=accent if checked else theme.BORDER)
            self.itemconfigure(tick, fill=theme.PANEL_BG if checked else "")

    def _control_at(self, x, y):
        if 102 <= y <= 127:
            for option, _left, outer, _inner, label in self._radio_items:
                left = self.coords(outer)[0] / self._zoom
                bbox = self.bbox(label)
                right = bbox[2] / self._zoom if bbox else left
                if left - 3 <= x <= right + 4:
                    return "format", option
        if 145 <= y <= theme.RESPONSE_CARD_H - 7:
            for option, _left, box, _tick, label in self._check_items:
                left = self.coords(box)[0] / self._zoom
                center_y = (self.coords(box)[1] + self.coords(box)[3]) \
                    / (2 * self._zoom)
                bbox = self.bbox(label)
                right = bbox[2] / self._zoom if bbox else left
                if (left - 3 <= x <= right + 4
                        and abs(y - center_y) <= 10):
                    return "style", option
        return None

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
        self._font(theme.FONT_UI)
        for item, coords in self._base_coords.items():
            self.coords(item, *(coords if zoom == 1.0
                                else [round(v * zoom) for v in coords]))
        self.itemconfigure(self._header_window,
                           width=round((theme.RESPONSE_CARD_W - 38 - 48) * zoom),
                           height=round(20 * zoom))
        self.itemconfigure(self._summary_window,
                           width=round((theme.RESPONSE_CARD_W - 24) * zoom),
                           height=round(108 * zoom))
        self.set_selected(self.selected)

    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfigure(
            self._body,
            outline=(theme.NODE_TYPES["response"]["accent"]
                     if self.selected else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def _on_delete_click(self, _event=None):
        if self.on_delete:
            self.on_delete()

    def _fwd_press(self, event):
        bounds = self.bbox(self._del)
        if (bounds is not None and bounds[0] <= event.x <= bounds[2]
                and bounds[1] <= event.y <= bounds[3]):
            self._on_delete_click()
            return "break"
        control = self._control_at(event.x / self._zoom,
                                   event.y / self._zoom)
        if control is not None:
            kind, option = control
            if kind == "format":
                self.format = option
            elif option in self.styles:
                self.styles.remove(option)
            else:
                self.styles.add(option)
            self._refresh_controls()
            self._sync_node_data()
            return "break"
        cx, cy = 15.5 * self._zoom, 44.0 * self._zoom
        radius = max(10.0, 12.0 * self._zoom)
        if (self.on_connect_press is not None
                and (event.x - cx) ** 2 + (event.y - cy) ** 2 <= radius ** 2):
            self.on_connect_press("contract", event.x_root, event.y_root)
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
