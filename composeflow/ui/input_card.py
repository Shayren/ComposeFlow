"""ComposeFlow input-node card.

A canvas-drawn rounded card for INPUT nodes on the flow canvas, styled after
the TaskCard design system (rounded body, accent selection border, gray
unselected border, subtle dividers). Structure, top to bottom:

  * header row: blue accent square + numbered input title + [x] delete
  * output section: right-docked blue dot + "Data" label; it starts
    Input.output -> Task.input connections
  * "Input files or folder:" label + a rounded file field with a Files
    button that opens a menu for selecting multiple files or a folder and
    stores selected files in node.file_paths or a folder in node.folder_path
  * "Input purpose:" label + a rounded container with an embedded tk.Text
    (placeholder logic mirrors TaskCard, but the field is seeded from and
    committed to node.purpose)
  * "Allow permission" row: a custom canvas checkbox toggling node.permission

The header Entry and the purpose Text are embedded native widgets (real
editing/selection); everything else is canvas items. Free-surface pointer
events forward to the flow canvas through on_press/on_motion/on_release
(same names as
TaskCard); on_delete removes the node. The card reads/writes node state
through the `get_node` callback, so it never touches the store directly.

Zoom: `_build()` draws everything from the 100% theme constants through
`_z()` (value * zoom) and scaled fonts; `apply_zoom(z)` recomputes item
coords from a zoom-1.0 base snapshot (rounded to device pixels) and
resizes the embedded editor in place, without rebuilding them.
Because every hit item (browse box/label included) is rebuilt at the same
scale as the drawn content, the browse-guard hit test stays consistent at
any zoom with no logic change.
"""

import tkinter as tk

from .title_marquee import TitleMarquee

from .. import theme
from .file_import import build_file_import_menu
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class InputCard(tk.Canvas):
    """Rounded input-node card (230x232) embedded in the flow canvas.

    get_node: () -> Node | None  callback returning the backing node.
    """

    PLACEHOLDER = "Enter the text...."
    def __init__(self, master, get_node=None, header="Input Header", **kw):
        # The card window fills a rectangle; matching the canvas background
        # makes the area outside the rounded body look transparent.
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=theme.INPUT_CARD_W,
                         height=theme.INPUT_CARD_H, **kw)

        self._get_node = get_node
        self._header = header
        self.selected = False
        self._output_highlighted = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_connect_press = None
        self.on_data_change = None
        self._file_menu = build_file_import_menu(
            self, "Select Input Files", (("All files", "*.*"),),
            frozenset(), self._set_file_paths)
        self._zoom = 1.0
        self._zoom_windows = []
        self._zoom_text_padding = []

        # Free-surface drag forwarding (embedded widgets swallow events).
        self.bind("<ButtonPress-1>", self._fwd_press)
        self.bind("<B1-Motion>", self._fwd_motion)
        self.bind("<ButtonRelease-1>", self._fwd_release)

        self._build()
        self._zoom_windows = [
            (self._header_window, theme.INPUT_CARD_W - 38 - 48, 20),
            (self._purpose_window, theme.INPUT_CARD_W - 28, 64),
        ]
        self._zoom_text_padding = [(self.purpose, 4, 4)]

    # ----------------------------------------------------------- zoom scale
    def _z(self, v):
        return v * self._zoom

    def _scaled_font(self, spec, slant=None):
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
        if self._perm_check is not None:
            self.itemconfigure(self._perm_check, width=max(1, round(2 * z)))
        self.set_selected(self.selected)

    # -------------------------------------------------------------- build
    def _build(self):
        # capture mid-edit purpose content before tearing down a rebuild
        old_purpose = None
        if (getattr(self, "purpose", None) is not None
                and self.purpose.winfo_exists()):
            old_purpose = self.purpose.get("1.0", "end-1c")
        if getattr(self, "purpose", None) is not None:
            try:
                self.purpose.destroy()
            except tk.TclError:
                pass
            self.purpose = None
        if getattr(self, "header", None) is not None:
            try:
                self._header = self.header.get()
                self.header.destroy()
            except tk.TclError:
                pass
            self.header = None
        self.delete("all")
        self._perm_check = None  # polyline drawn on demand when checked
        self._base_coords = {}   # zoom-1.0 snapshot, replaced at build end

        w, h = theme.INPUT_CARD_W, theme.INPUT_CARD_H
        accent = theme.NODE_TYPES["input"]["accent"]

        # Body: one smoothed rounded-rect polygon with a 1px gray border
        # (input accent at 2px when selected; scaled in set_selected).
        self._body = self.create_polygon(
            rounded_rect_points(self._z(1), self._z(1),
                                self._z(w - 2), self._z(h - 2), self._z(10)),
            smooth=True, fill=theme.PANEL_BG_ALT,
            outline=theme.NODE_BORDER_NORMAL, width=1)

        # Header row: blue square + editable title Entry + [x] delete. The
        # 14x14 square is centered on the entry's vertical center (y 22).
        self.create_rectangle(self._z(12), self._z(15),
                              self._z(26), self._z(29),
                              fill=accent, outline="")
        self.header = tk.Entry(self, bg=theme.PANEL_BG_ALT, fg=theme.TEXT,
                               insertbackground=theme.TEXT, bd=0,
                               highlightthickness=0,
                               font=self._scaled_font(theme.FONT_UI_BOLD),
                               relief="flat")
        self.header.insert(0, self._header)
        self._title_marquee = TitleMarquee(self.header)
        self.header.bind("<KeyRelease>", self._sync_node_data)
        self._header_window = self.create_window(
            self._z(34), self._z(12), anchor="nw",
            width=round(self._z(w - 38 - 48)),
            height=round(self._z(20)), window=self.header)
        self._del = self.create_text(self._z(w - 16), self._z(22),
                                     text="[x]", anchor="e",
                                     font=self._scaled_font(theme.FONT_SMALL),
                                     fill=theme.TEXT_MUTED)
        self.tag_bind(self._del, "<Button-1>", self._on_delete_click)
        self.tag_bind(self._del, "<Enter>",
                      lambda e: (self.itemconfig(self._del, fill=theme.TEXT),
                                 self.configure(cursor="hand2")))
        self.tag_bind(self._del, "<Leave>",
                      lambda e: (self.itemconfig(self._del,
                                                 fill=theme.TEXT_MUTED),
                                 self.configure(cursor="")))

        # Header divider, followed by a compact single-pin row.
        self._header_divider = self.create_line(
            self._z(12), self._z(36), self._z(w - 12), self._z(36),
            fill=theme.BORDER)

        # Output section: match the single-row port size, inset, and center
        # used by Context and Response cards.
        self._output_dot = self.create_oval(
            self._z(w - 19), self._z(44.5),
            self._z(w - 12), self._z(51.5),
            fill="", outline=theme.SEMANTIC_COLORS[
                theme.PORT_SEMANTICS[("input", "data")]], width=1.5)
        self._output_hover_ring = self.create_oval(
            self._z(w - 22), self._z(41.5),
            self._z(w - 9), self._z(54.5), fill="",
            outline=theme.WIRE_HOVER, width=2, state="hidden")
        self.tag_lower(self._output_hover_ring, self._output_dot)
        self.tag_bind(self._output_dot, "<Enter>",
                      lambda _e: (self.itemconfigure(
                          self._output_hover_ring, state="normal"),
                          self.configure(cursor="hand2")))
        self.tag_bind(self._output_dot, "<Leave>",
                      lambda _e: (self.itemconfigure(
                          self._output_hover_ring, state="hidden"),
                          self.configure(cursor="")))
        self.create_text(self._z(w - 26), self._z(48),
                         text=theme.PIN_LABELS[("input", "data")],
                         anchor="e", font=self._scaled_font(theme.FONT_SMALL),
                         fill=theme.TEXT_MUTED)

        # Divider 2 below the output section.
        self._divider = self.create_line(
            self._z(12), self._z(60), self._z(w - 12), self._z(60),
            fill=theme.BORDER)

        file_margin = theme.INPUT_FILE_MARGIN_X
        file_button_w = theme.INPUT_FILE_BUTTON_W
        file_button_x = w - file_margin - file_button_w
        file_row_y = theme.INPUT_FILE_ROW_Y
        file_row_h = theme.INPUT_FILE_ROW_H
        self.create_text(self._z(file_margin), self._z(theme.INPUT_FILE_LABEL_Y),
            text="Input files or folder:", anchor="w",
                         font=self._scaled_font(theme.FONT_SMALL),
                         fill=theme.TEXT)

        # File row: rounded main field (display-only path) + browse button.
        self._file_box = self.create_polygon(
            rounded_rect_points(self._z(file_margin), self._z(file_row_y),
                                self._z(theme.INPUT_FILE_FIELD_W), self._z(file_row_h),
                                self._z(4)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self._file_text = self.create_text(
            self._z(file_margin + 6), self._z(file_row_y + file_row_h / 2),
            text="", anchor="w",
            font=self._scaled_font(theme.FONT_SMALL), fill=theme.TEXT)
        self._file_font = self._scaled_font(theme.FONT_SMALL)

        self._browse_box = self.create_polygon(
            rounded_rect_points(self._z(file_button_x), self._z(file_row_y),
                                self._z(file_button_w), self._z(file_row_h),
                                self._z(4)),
            smooth=True, fill=theme.PANEL_BG_ALT, outline=theme.BORDER,
            width=1)
        self._browse_lbl = self.create_text(
            self._z(file_button_x + file_button_w / 2),
            self._z(file_row_y + file_row_h / 2), text="Files",
            font=self._scaled_font(theme.FONT_SMALL), fill=theme.TEXT)
        self.tag_bind(self._browse_box, "<Button-1>", self._on_browse)
        self.tag_bind(self._browse_lbl, "<Button-1>", self._on_browse)
        self.tag_bind(self._browse_box, "<Enter>",
                      lambda e: self.configure(cursor="hand2"))
        self.tag_bind(self._browse_lbl, "<Enter>",
                      lambda e: self.configure(cursor="hand2"))
        self.tag_bind(self._browse_box, "<Leave>",
                      lambda e: self.configure(cursor=""))
        self.tag_bind(self._browse_lbl, "<Leave>",
                      lambda e: self.configure(cursor=""))

        # "Input purpose:" label + rounded text-area container.
        self.create_text(self._z(12), self._z(112), text="Input purpose:",
                         anchor="w", font=self._scaled_font(theme.FONT_SMALL),
                         fill=theme.TEXT)
        self._purpose_box = self.create_polygon(
            rounded_rect_points(self._z(12), self._z(124),
                                self._z(w - 24), self._z(68), self._z(8)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self.purpose = tk.Text(self, bg=theme.PANEL_BG, fg=theme.TEXT,
                               insertbackground=theme.TEXT, bd=0,
                               highlightthickness=0, relief="flat",
                               font=self._scaled_font(theme.FONT_SMALL),
                               wrap="word",
                               undo=True,
                               spacing1=2, spacing3=2,
                               padx=max(1, round(self._z(4))),
                               pady=max(1, round(self._z(4))))
        self._placeholder_font = self._scaled_font(theme.FONT_SMALL,
                                                   slant="italic")
        self.purpose.bind("<FocusIn>", self._on_focus_in)
        self.purpose.bind("<FocusOut>", self._on_focus_out)
        self._purpose_window = self.create_window(
            self._z(14), self._z(126), anchor="nw",
            width=round(self._z(w - 28)), height=round(self._z(64)),
            window=self.purpose)

        # Permission row: custom canvas checkbox + label.
        self._perm_box = self.create_polygon(
            rounded_rect_points(self._z(12), self._z(200),
                                self._z(14), self._z(14), self._z(4)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self.create_text(self._z(32), self._z(207), text="Allow permission",
                         anchor="w", font=self._scaled_font(theme.FONT_SMALL),
                         fill=theme.TEXT_MUTED)
        self.tag_bind(self._perm_box, "<Button-1>", self._on_perm_click)
        self.tag_bind(self._perm_box, "<Enter>",
                      lambda e: self.configure(cursor="hand2"))
        self.tag_bind(self._perm_box, "<Leave>",
                      lambda e: self.configure(cursor=""))

        self.set_selected(self.selected)
        self._refresh()  # seed placeholders/path/checkbox from node state
        # keep uncommitted mid-edit purpose text across a zoom rebuild
        if old_purpose not in (None, "", self.PLACEHOLDER):
            self.purpose.delete("1.0", "end")
            self.purpose.insert("1.0", old_purpose)
            self.purpose.configure(fg=theme.TEXT,
                                   font=self._scaled_font(theme.FONT_SMALL))
        self.purpose.bind("<<Modified>>", self._purpose_modified)
        self.purpose.edit_modified(False)

        # Canonical zoom-1.0 geometry snapshot; apply_zoom re-derives every
        # item's coords from this (never from a previous zoom state).
        self._base_coords = {item: self.coords(item)
                             for item in self.find_all()}

    # -------------------------------------------------------------- drawing
    def _node(self):
        if self._get_node is None:
            return None
        return self._get_node()

    def _refresh(self):
        """Sync all node-backed content (file path, purpose, permission)."""
        node = self._node()
        purpose = node.purpose if node is not None else ""
        if purpose:
            self.purpose.delete("1.0", "end")
            self.purpose.insert("1.0", purpose)
            self.purpose.configure(
                fg=theme.TEXT,
                font=self._scaled_font(theme.FONT_SMALL))
        else:
            self.purpose.delete("1.0", "end")
            self.purpose.insert("1.0", self.PLACEHOLDER)
            self.purpose.configure(fg=theme.TEXT_MUTED,
                                   font=self._placeholder_font)
        self._refresh_path()
        self._draw_permission()

    def _refresh_path(self):
        node = self._node()
        paths = (node.file_paths or ([node.file_path] if node.file_path else [])
                 if node is not None else [])
        if node is not None and node.folder_path:
            summary = node.folder_path
        elif len(paths) == 1:
            summary = paths[0]
        elif paths:
            summary = f"{len(paths)} files · {paths[0]}"
        else:
            summary = ""
        key = (self._file_text, summary, self._zoom)
        if getattr(self, "_path_display_key", None) != key:
            self.itemconfig(self._file_text, text=self._fitted_path(summary))
            self._path_display_key = key

    def _set_file_paths(self, paths, folder_path=None):
        node = self._node()
        if node is None:
            return
        selected = list(paths)
        first_path = selected[0] if selected else ""
        folder = folder_path or ""
        if (node.file_paths == selected and node.file_path == first_path
                and node.folder_path == folder):
            return
        node.file_paths = selected
        node.file_path = first_path
        node.folder_path = folder
        self._refresh_path()
        if self.on_data_change:
            self.on_data_change()

    def set_header(self, header):
        self._header = header
        if self.header.get() == header:
            return
        self.header.delete(0, "end")
        self.header.insert(0, header)

    def _sync_node_data(self, _event=None):
        node = self._node()
        if node is None:
            return
        header = self.header.get()
        if node.header == header:
            return
        node.auto_header = False
        node.header = header
        if self.on_data_change:
            self.on_data_change()

    def _purpose_modified(self, _event=None):
        if self.purpose.edit_modified():
            self.purpose.edit_modified(False)
            self._sync_purpose()

    def _sync_purpose(self):
        node = self._node()
        if node is None:
            return
        content = self.purpose.get("1.0", "end-1c")
        purpose = "" if content == self.PLACEHOLDER else content
        if purpose != node.purpose:
            node.purpose = purpose
            if self.on_data_change:
                self.on_data_change()

    def _fitted_path(self, path):
        """Truncate a long path with a trailing '…' to fit the field."""
        if not path:
            return ""
        max_w = self._z(theme.INPUT_FILE_FIELD_W - 12)
        if self._file_font.measure(path) <= max_w:
            return path
        lo, hi = 0, len(path)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._file_font.measure(path[:mid] + "…") <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return path[:lo] + "…"

    def _draw_permission(self):
        node = self._node()
        checked = bool(node is not None and node.permission)
        if checked:
            self.itemconfig(self._perm_box,
                            fill=theme.NODE_TYPES["input"]["accent"],
                            outline=theme.NODE_TYPES["input"]["accent"])
            if self._perm_check is None:
                base = [15.0, 207.0, 18.0, 210.0, 24.0, 203.0]
                self._perm_check = self.create_line(
                    *[round(v * self._zoom) for v in base],
                    fill=theme.PANEL_BG, width=max(1, round(2 * self._zoom)),
                    capstyle=tk.ROUND, joinstyle=tk.ROUND)
                self._base_coords[self._perm_check] = base
        else:
            self.itemconfig(self._perm_box, fill=theme.PANEL_BG,
                            outline=theme.BORDER, width=1)
            if self._perm_check is not None:
                self._base_coords.pop(self._perm_check, None)
                self.delete(self._perm_check)
                self._perm_check = None

    # -------------------------------------------------------------- events
    def _fwd_press(self, event):
        center_x = (theme.INPUT_CARD_W - 15.5) * self._zoom
        center_y = 48.0 * self._zoom
        radius = max(10.0, 12.0 * self._zoom)
        if (self.on_connect_press is not None
                and (event.x - center_x) ** 2 + (event.y - center_y) ** 2
                <= radius ** 2):
            self.on_connect_press("data", event.x_root, event.y_root)
            return "break"
        # A press on the browse button must not arm card drag: the button
        # opens a modal file dialog whose grab swallows the matching
        # <ButtonRelease-1>, so a drag armed here would never see its
        # release and the card would track the pointer on plain mouse
        # motion. An item-tag "break" cannot stop this widget-level binding
        # on Tk 8.6 (item bindings run first, then the widget's own bindtag
        # still fires), so suppress the forward when the press lands on the
        # browse hit-zone. Card geometry scales with _z, so this local
        # coordinate check stays correct at every zoom.
        if self.find_overlapping(event.x, event.y, event.x, event.y):
            hit = set(self.find_overlapping(event.x, event.y, event.x, event.y))
            if self._browse_box in hit or self._browse_lbl in hit:
                return
            if self._del in hit or self._perm_box in hit:
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

    def _on_delete_click(self, event=None):
        if self.on_delete:
            self.on_delete()

    def _on_browse(self, event=None):
        x_root = event.x_root if event is not None else self.winfo_rootx()
        y_root = event.y_root if event is not None else self.winfo_rooty()
        self._file_menu.tk_popup(x_root, y_root)
        # Keep the popup's grab for outside-click dismissal. Stop the browse
        # press from arming a drag; _fwd_press guards the widget-level binding.
        return "break"

    def _on_perm_click(self, event=None):
        node = self._node()
        if node is None:
            return
        node.permission = not node.permission
        self._draw_permission()
        if self.on_data_change:
            self.on_data_change()

    # ------------------------------------------------------------ selection
    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfig(
            self._body,
            outline=(theme.NODE_TYPES["input"]["accent"] if self.selected
                     else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def set_output_highlight(self, highlighted, color=theme.SELECT):
        self._output_highlighted = bool(highlighted)
        self.itemconfigure(
            self._output_dot,
            outline=color if highlighted else "",
            width=max(1, round(2 * self._zoom)) if highlighted else 0)

    def set_port_color(self, port, color):
        if self._output_dot is None:
            return
        self.itemconfigure(self._output_dot, fill=color)

    def set_port_connected(self, port, connected):
        color = theme.SEMANTIC_COLORS[theme.PORT_SEMANTICS[("input", "data")]]
        self.itemconfigure(self._output_dot,
                           fill=color if connected else "", outline=color)

    # ---------------------------------------------------------- placeholder
    def _on_focus_in(self, event):
        if self.purpose.get("1.0", "end-1c") == self.PLACEHOLDER:
            self.purpose.delete("1.0", "end")
            self.purpose.configure(
                fg=theme.TEXT,
                font=self._scaled_font(theme.FONT_SMALL))

    def _on_focus_out(self, event=None):
        self._sync_purpose()
        content = self.purpose.get("1.0", "end-1c")
        if not content:
            self.purpose.insert("1.0", self.PLACEHOLDER)
            self.purpose.configure(fg=theme.TEXT_MUTED,
                                   font=self._placeholder_font)
