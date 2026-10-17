"""Editable Context node card."""

import tkinter as tk

from .title_marquee import TitleMarquee

from .. import theme
from .file_import import build_file_import_menu
from .font_cache import scaled_font
from .rounded_button import rounded_rect_points


class ContextCard(tk.Canvas):
    """Rounded card with a visual Context pin and editable description."""

    PLACEHOLDER = "Enter the text...."

    def __init__(self, master, header="Context 1", get_node=None, **kw):
        kw.setdefault("bg", theme.CANVAS_BG)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=theme.TASK_CARD_W,
                         height=theme.CONTEXT_CARD_H, **kw)
        self.selected = False
        self.on_delete = None
        self.on_press = None
        self.on_motion = None
        self.on_release = None
        self.on_connect_press = None
        self.on_data_change = None
        self._file_menu = build_file_import_menu(
            self, "Select Context Files",
            (("Markdown files", "*.md"),),
            frozenset((".md",)), self._set_file_paths)
        self._get_node = get_node
        self._zoom = 1.0
        node = get_node() if get_node else None
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
        w, h = theme.TASK_CARD_W, theme.CONTEXT_CARD_H
        accent = theme.NODE_TYPES["context"]["accent"]
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

        self._pin_dot = self.create_oval(
            self._z(w - 19), self._z(44.5), self._z(w - 12), self._z(51.5),
            fill="", outline=theme.SEMANTIC_COLORS[
                theme.PORT_SEMANTICS[("context", "context")]], width=1.5)
        self._pin_hover_ring = self.create_oval(
            self._z(w - 22), self._z(41.5),
            self._z(w - 9), self._z(54.5), fill="",
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
            self._z(w - 26), self._z(48), text="Context", anchor="e",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT_MUTED)
        self._divider = self.create_line(
            self._z(12), self._z(60), self._z(w - 12), self._z(60),
            fill=theme.BORDER)
        self._description_label = self.create_text(
            self._z(12), self._z(72), text="Context description:",
            anchor="w", font=self._font(theme.FONT_SMALL),
            fill=theme.TEXT_MUTED)
        self._description_box = self.create_polygon(
            rounded_rect_points(
                self._z(12), self._z(theme.CONTEXT_DESCRIPTION_BOX_Y),
                self._z(w - 24), self._z(theme.CONTEXT_DESCRIPTION_BOX_H),
                self._z(6)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self.description = tk.Text(
            self, bg=theme.PANEL_BG, fg=theme.TEXT_MUTED,
            insertbackground=theme.TEXT, bd=0, highlightthickness=0,
            relief="flat", font=self._font(theme.FONT_SMALL), wrap="word",
            undo=True, spacing1=3, spacing3=3,
            padx=max(1, round(self._z(6))),
            pady=max(1, round(self._z(6))))
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
        self._description_window = self.create_window(
            self._z(14), self._z(theme.CONTEXT_DESCRIPTION_TEXT_Y),
            anchor="nw", window=self.description,
            width=round(self._z(w - 28)),
            height=round(self._z(theme.CONTEXT_DESCRIPTION_TEXT_H)))
        file_margin = theme.CONTEXT_FILES_MARGIN_X
        file_button_w = theme.CONTEXT_FILES_BUTTON_W
        file_button_x = w - file_margin - file_button_w
        file_field_w = file_button_x - file_margin - theme.CONTEXT_FILES_GAP
        file_row_y = theme.CONTEXT_FILES_ROW_Y
        file_row_h = theme.CONTEXT_FILES_ROW_H
        self._context_files_label = self.create_text(
            self._z(file_margin), self._z(theme.CONTEXT_FILES_LABEL_Y),
            text="Context files (.md):",
            anchor="w", font=self._font(theme.FONT_SMALL),
            fill=theme.TEXT_MUTED)
        self._context_files_box = self.create_polygon(
            rounded_rect_points(self._z(file_margin), self._z(file_row_y),
                                self._z(file_field_w), self._z(file_row_h),
                                self._z(4)),
            smooth=True, fill=theme.PANEL_BG, outline=theme.BORDER, width=1)
        self._context_files_text = self.create_text(
            self._z(file_margin + 6), self._z(file_row_y + file_row_h / 2),
            text="No files selected", anchor="w",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT)
        self._context_files_button = self.create_polygon(
            rounded_rect_points(self._z(file_button_x), self._z(file_row_y),
                                self._z(file_button_w), self._z(file_row_h),
                                self._z(4)),
            smooth=True, fill=theme.PANEL_BG_ALT, outline=theme.BORDER,
            width=1)
        self._context_files_button_label = self.create_text(
            self._z(file_button_x + file_button_w / 2),
            self._z(file_row_y + file_row_h / 2), text="Files",
            font=self._font(theme.FONT_SMALL), fill=theme.TEXT)
        self._context_file_import_items = (
            self._context_files_box, self._context_files_text,
            self._context_files_button, self._context_files_button_label)
        for item in self._context_file_import_items:
            self.tag_bind(item, "<Button-1>", self._on_browse)
        for item in (self._context_files_button,
                     self._context_files_button_label):
            self.tag_bind(item, "<Enter>",
                          lambda _event: self.configure(cursor="hand2"))
            self.tag_bind(item, "<Leave>",
                          lambda _event: self.configure(cursor=""))
        self._refresh_files()
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
                           width=round((theme.TASK_CARD_W - 38 - 48) * zoom),
                           height=round(20 * zoom))
        self.itemconfigure(self._description_window,
                           width=round((theme.TASK_CARD_W - 28) * zoom),
                           height=round(theme.CONTEXT_DESCRIPTION_TEXT_H * zoom))
        self.description.configure(padx=max(1, round(6 * zoom)),
                                   pady=max(1, round(6 * zoom)))
        self.set_selected(self.selected)

    def set_selected(self, selected):
        self.selected = bool(selected)
        self.itemconfigure(
            self._body,
            outline=(theme.NODE_TYPES["context"]["accent"] if self.selected
                     else theme.NODE_BORDER_NORMAL),
            width=max(1, round((2 if self.selected else 1) * self._zoom)))

    def set_output_highlight(self, highlighted, color=theme.SELECT):
        self.itemconfigure(
            self._pin_dot,
            outline=color if highlighted else "",
            width=max(1, round(2 * self._zoom)) if highlighted else 0)

    def set_port_color(self, port, color):
        if self._pin_dot is None:
            return
        self.itemconfigure(self._pin_dot, fill=color)

    def set_port_connected(self, port, connected):
        color = theme.SEMANTIC_COLORS[theme.PORT_SEMANTICS[("context", "context")]]
        self.itemconfigure(self._pin_dot,
                           fill=color if connected else "", outline=color)

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

    def _refresh_files(self):
        node = self._get_node() if self._get_node else None
        paths = node.file_paths if node is not None else []
        if node is not None and node.folder_path:
            summary = node.folder_path
        elif not paths:
            summary = "No files selected"
        elif len(paths) > 1:
            summary = f"{len(paths)} files · {paths[0]}"
        else:
            summary = paths[0]
        key = (self._context_files_text, summary, self._zoom)
        if getattr(self, "_path_display_key", None) == key:
            return
        font = self._font(theme.FONT_SMALL)
        max_width = self._z(theme.TASK_CARD_W
                            - 2 * theme.CONTEXT_FILES_MARGIN_X
                            - theme.CONTEXT_FILES_BUTTON_W
                            - theme.CONTEXT_FILES_GAP - 12)
        if font.measure(summary) > max_width:
            low, high = 0, len(summary)
            while low < high:
                middle = (low + high + 1) // 2
                if font.measure(summary[:middle] + "…") <= max_width:
                    low = middle
                else:
                    high = middle - 1
            if low < len(summary):
                summary = summary[:low] + "…"
        self.itemconfigure(self._context_files_text, text=summary)
        self._path_display_key = key

    def _set_file_paths(self, paths, folder_path=None):
        node = self._get_node() if self._get_node else None
        if node is None:
            return
        selected = list(paths)
        folder = folder_path or ""
        if node.file_paths == selected and node.folder_path == folder:
            return
        node.file_paths = selected
        node.folder_path = folder
        self._refresh_files()
        if self.on_data_change:
            self.on_data_change()

    def _on_browse(self, event=None):
        x_root = event.x_root if event is not None else self.winfo_rootx()
        y_root = event.y_root if event is not None else self.winfo_rooty()
        self._file_menu.tk_popup(x_root, y_root)
        return "break"

    def set_header(self, header):
        if self.header.get() == header:
            return
        self.header.delete(0, "end")
        self.header.insert(0, header)

    def _fwd_press(self, event):
        cx = (theme.TASK_CARD_W - 15.5) * self._zoom
        cy = 48.0 * self._zoom
        radius = max(10.0, 12.0 * self._zoom)
        if (self.on_connect_press is not None
                and (event.x - cx) ** 2 + (event.y - cy) ** 2 <= radius ** 2):
            self.on_connect_press("context", event.x_root, event.y_root)
            return "break"
        bounds = self.bbox(self._del)
        if (bounds is not None and bounds[0] <= event.x <= bounds[2]
                and bounds[1] <= event.y <= bounds[3]):
            self._on_delete_click()
            return "break"
        hit_items = self.find_overlapping(event.x, event.y, event.x, event.y)
        if any(item in hit_items for item in self._context_file_import_items):
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
