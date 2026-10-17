"""Live semantic Flow JSON editor and clipboard update panel."""

import json
import tkinter as tk
from tkinter import filedialog

from composeflow import theme
from composeflow.flow_json import parse_flow_json
from .rounded_button import RoundedButton, rounded_rect_points


class FuturePanel(tk.Frame):
    """Collapsible JSON editor synchronized with the current flow."""

    BTN_SIZE = 26    # px: rounded < expand button (rail handle) size
    NOTICE_HEIGHT = 40
    RAIL_MIN = BTN_SIZE + 4

    def destroy(self):
        if self._validation_job is not None:
            self.after_cancel(self._validation_job)
            self._validation_job = None
        self._cancel_notice_animation()
        super().destroy()

    def _make_btn(self, parent, glyph):
        """One rounded trigger button, used for BOTH the > collapse toggle
        and the < expand handle so the two controls always share size,
        border, font, and colors (canvas-drawn, true rounded corners)."""
        return RoundedButton(
            parent, text=glyph, command=self.toggle_compact,
            width=self.BTN_SIZE, height=self.BTN_SIZE, radius=8,
            font=theme.FONT_SMALL, fill=theme.PANEL_BG_ALT,
            fg=theme.TEXT_MUTED, outline=theme.BORDER, outlinewidth=1,
            page_bg=theme.PANEL_BG, cursor="hand2")

    def __init__(self, master, **kw):
        # The column width is owned by the app grid's column ratio, so this
        # panel requests no width of its own; it fills whatever it gets.
        kw.setdefault("width", 0)
        kw.setdefault("bg", theme.PANEL_BG)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", theme.BORDER)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self.collapsed = False
        self._animating = False
        self.on_launch = None

        # Match the Node Library's header row: title on the left and the
        # collapse control aligned to the right with the same padding.
        self._top = tk.Frame(self, bg=theme.PANEL_BG)
        self._heading = tk.Label(
            self._top, text=theme.FUTURE_LABEL, font=theme.FONT_SMALL,
            bg=theme.PANEL_BG, fg=theme.TEXT_MUTED,
        )
        self._toggle = self._make_btn(self._top, ">")
        self._toggle.pack(side="right", padx=(0, 8), pady=(10, 6))
        accent = theme.NODE_TYPES["task"]["accent"]
        self._launch_button = RoundedButton(
            self._top, text="▶", command=self._request_launch,
            width=self.BTN_SIZE, height=self.BTN_SIZE, radius=8,
            font=theme.FONT_UI_BOLD, fill=theme.PANEL_BG_ALT,
            fg=accent, outline=accent, page_bg=theme.PANEL_BG)
        self._launch_button.pack(side="right", padx=(0, 4), pady=(10, 6))
        self._export_button = self._make_btn(self._top, "↑")
        self._export_button.configure(command=self._export_json)
        self._export_button.pack(side="right", padx=(0, 4), pady=(10, 6))
        self._import_button = self._make_btn(self._top, "↓")
        self._import_button.configure(command=self._import_json)
        self._import_button.pack(side="right", padx=(0, 4), pady=(10, 6))
        self._copy_button = self._make_btn(self._top, "⧉")
        self._copy_button.configure(command=self._copy_json)
        self._copy_button.pack(side="right", padx=(0, 4), pady=(10, 6))
        self._update_button = self._make_btn(self._top, "↻")
        self._update_button.configure(command=self._paste_clipboard)
        self._update_button.pack(side="right", padx=(0, 4), pady=(10, 6))
        self._subtext = tk.Label(self, text=theme.FUTURE_SUBTEXT,
                                 font=theme.FONT_SMALL, bg=theme.PANEL_BG,
                                 fg=theme.TEXT_MUTED)
        self._viewer_frame = tk.Canvas(
            self, bg=theme.PANEL_BG, bd=0, highlightthickness=0)
        self._viewer_surface = self._viewer_frame.create_polygon(
            rounded_rect_points(1, 1, 10, 10, 10), smooth=True,
            fill=theme.PANEL_BG_ALT, outline=theme.BORDER, width=1)
        self.viewer = tk.Text(
            self._viewer_frame, state="normal", wrap="none",
            font=("TkFixedFont", 9), bg=theme.PANEL_BG_ALT,
            fg=theme.TEXT, insertbackground=theme.TEXT,
            selectbackground=theme.SELECT, relief="flat", bd=0,
            highlightthickness=0,
            padx=8, pady=8)
        scrollbar_style = {"bg": theme.TEXT_MUTED,
                           "activebackground": theme.TEXT,
                           "troughcolor": theme.PANEL_BG,
                           "highlightthickness": 0,
                           "bd": 0,
                           "width": 12}
        self._scroll_y = tk.Scrollbar(
            self._viewer_frame, orient="vertical", command=self.viewer.yview,
            **scrollbar_style)
        self._scroll_x = tk.Scrollbar(
            self._viewer_frame, orient="horizontal", command=self.viewer.xview,
            **scrollbar_style)
        self.viewer.configure(yscrollcommand=self._scroll_y.set,
                              xscrollcommand=self._scroll_x.set)
        self.viewer.bind("<<Modified>>", self._on_json_modified)
        self.viewer.bind("<Control-a>", self._select_all)
        self.viewer.bind("<Control-A>", self._select_all)
        self.viewer.bind("<Control-v>", self._paste_selection)
        self.viewer.bind("<Control-V>", self._paste_selection)
        self.viewer.bind("<<Paste>>", self._paste_selection)
        self._viewer_window = self._viewer_frame.create_window(
            8, 8, anchor="nw", window=self.viewer)
        self._scroll_y_window = self._viewer_frame.create_window(
            0, 8, anchor="ne", window=self._scroll_y)
        self._scroll_x_window = self._viewer_frame.create_window(
            8, 0, anchor="sw", window=self._scroll_x)
        self._viewer_frame.bind("<Configure>", self._layout_viewer)
        self._json = None
        self.on_json_change = None
        self._layout_on_apply = False
        self._loading_json = False
        self._validation_job = None
        self._notice_area = tk.Frame(self, bg=theme.PANEL_BG, height=0)
        self._notice_area.pack_propagate(False)
        self._notice_text = None
        self._status = tk.Label(
            self._notice_area, font=theme.FONT_SMALL, bg=theme.PANEL_BG_ALT,
            fg=theme.TEXT_MUTED, anchor="w", justify="left",
            padx=8, pady=6)
        self._notice_animation_job = None

        # Collapsed-state handle follows the Node Library's right-aligned
        # rail placement and shared size.
        # place()-based, so it keeps its natural size no matter how narrow
        # the rail is; the rail is floored at RAIL_MIN so the handle never
        # overlaps the canvas.
        self._expand = self._make_btn(self, "<")
        self._launch_compact = RoundedButton(
            self, text="▶", command=self._request_launch,
            width=self.BTN_SIZE, height=self.BTN_SIZE, radius=8,
            font=theme.FONT_UI_BOLD, fill=theme.PANEL_BG_ALT,
            fg=accent, outline=accent, page_bg=theme.PANEL_BG)
        self._compact_buttons = [self._expand, self._launch_compact]
        for expanded in (self._export_button, self._import_button,
                         self._copy_button, self._update_button):
            button = self._make_btn(self, expanded.cget("text"))
            button.configure(command=expanded.cget("command"))
            self._compact_buttons.append(button)

        self._set_content_visible(True)

    def _import_json(self):
        path = filedialog.askopenfilename(
            title="Import Flow JSON",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as json_file:
                content = json_file.read()
        except (OSError, UnicodeError) as exc:
            self.set_validation_status(f"Could not import JSON: {exc}")
            return
        self._replace_draft(content, auto_layout=True)
        self.viewer.focus_set()

    def _copy_json(self):
        """Copy the JSON currently shown in the editor to the clipboard."""
        text = self.viewer.get("1.0", "end-1c")
        if not text:
            text = self._json or ""
        if not text:
            self.set_validation_status("Nothing to copy")
            return
        self.viewer.clipboard_clear()
        self.viewer.clipboard_append(text)
        self._show_notice("Flow JSON copied",
                          theme.NODE_TYPES["task"]["accent"])

    def _export_json(self):
        draft = self.viewer.get("1.0", "end-1c")
        try:
            parse_flow_json(draft)
        except ValueError as exc:
            self.set_validation_status(f"Export blocked: {exc}")
            return
        if self._validation_job is not None:
            self.after_cancel(self._validation_job)
            self._validation_job = None
        if self.on_json_change is not None:
            result = self.on_json_change(draft)
            if result is not True:
                self.set_validation_status(f"Export blocked: {result}")
                return
            if "schemaVersion" not in json.loads(draft):
                draft = self.viewer.get("1.0", "end-1c")
            else:
                self.set_json(draft)
        path = filedialog.asksaveasfilename(
            title="Export Flow JSON", defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as json_file:
                json_file.write(draft)
        except (OSError, UnicodeError) as exc:
            self.set_validation_status(f"Could not export JSON: {exc}")
            return
        self._show_notice(f"Flow JSON exported: {path}",
                          theme.NODE_TYPES["task"]["accent"])

    def _layout_viewer(self, event):
        width, height = event.width, event.height
        self._viewer_frame.coords(
            self._viewer_surface,
            *rounded_rect_points(1, 1, max(2, width - 2),
                                 max(2, height - 2), 10))
        text_width = max(1, width - 28)
        text_height = max(1, height - 28)
        self._viewer_frame.coords(self._viewer_window, 8, 8)
        self._viewer_frame.itemconfigure(
            self._viewer_window, width=text_width, height=text_height)
        self._viewer_frame.coords(self._scroll_y_window, width - 7, 8)
        self._viewer_frame.itemconfigure(
            self._scroll_y_window, height=max(1, height - 22))
        self._viewer_frame.coords(self._scroll_x_window, 8, height - 7)
        self._viewer_frame.itemconfigure(
            self._scroll_x_window, width=max(1, width - 22))

    def _set_content_visible(self, visible):
        """Pack / unpack the layout for the current state.

        Expanded: matching header row, section label and JSON viewer. Collapsed:
        everything hidden except the controls stacked below the < handle,
        aligned to the rail's right edge (inside it). All sibling packing
        happens HERE, so the pack order can never be violated.
        """
        if visible:
            self._top.pack(fill="x")
            self._heading.pack(side="left", padx=12, pady=(12, 8))
            self._subtext.pack(anchor="w", padx=14, pady=(4, 6))
            self._viewer_frame.pack(fill="both", expand=True,
                                    padx=14, pady=(0, 14))
            if self._notice_text is not None:
                self._status.pack(fill="x")
                self._notice_area.configure(height=0)
                self._notice_area.pack(
                    fill="x", padx=14, pady=(0, 6),
                    before=self._viewer_frame)
                self._status.configure(wraplength=max(120, self.winfo_width() - 48))
                self._animate_notice_in()
            for button in self._compact_buttons:
                button.place_forget()
        else:
            self._cancel_notice_animation()
            self._top.pack_forget()
            self._heading.pack_forget()
            self._subtext.pack_forget()
            self._notice_area.pack_forget()
            self._viewer_frame.pack_forget()
            for index, button in enumerate(self._compact_buttons):
                button.place(relx=1.0, x=-(self.BTN_SIZE + 2),
                             y=14 + index * (self.BTN_SIZE + 6))

    def _request_launch(self):
        if self.on_launch is not None:
            self.on_launch()

    def set_launch_busy(self, busy):
        state = "disabled" if busy else "normal"
        self._launch_button.configure(state=state)
        self._launch_compact.configure(state=state)

    def set_json(self, content):
        """Replace the editor contents with the current model projection."""
        if (content == self._json
                and self.viewer.get("1.0", "end-1c") == content):
            return
        if self._validation_job is not None:
            self.after_cancel(self._validation_job)
            self._validation_job = None
        self._json = content
        self._loading_json = True
        self.viewer.configure(state="normal")
        self.viewer.delete("1.0", "end")
        self.viewer.insert("1.0", content)
        self.viewer.edit_modified(False)
        self._loading_json = False
        self.set_validation_status(None)

    def _paste_clipboard(self):
        """Replace the JSON draft with the complete clipboard contents."""
        try:
            content = self._read_clipboard()
        except tk.TclError:
            if not self._paste_native_document():
                self.set_validation_status(
                    "Clipboard is empty or unavailable")
                return
            self.viewer.focus_set()
            return
        if not content:
            self.set_validation_status("Clipboard is empty")
            return
        self._replace_draft(content)
        self.viewer.focus_set()

    def _select_all(self, _event=None):
        self.viewer.tag_add("sel", "1.0", "end-1c")
        self.viewer.mark_set("insert", "end-1c")
        self.viewer.see("insert")
        return "break"

    def _paste_selection(self, _event=None):
        try:
            content = self._read_clipboard()
        except tk.TclError:
            if not self._paste_native_document():
                self.set_validation_status(
                    "Clipboard is empty or unavailable")
            return "break"
        # A whole workflow document replaces the editor even if deleting the
        # current selection already caused the empty draft to be restored.
        whole_document = (content.lstrip().startswith("{")
                          and '"workflow"' in content)
        if whole_document:
            self._replace_draft(content)
            return "break"
        self.viewer.edit_modified(False)
        try:
            self.viewer.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self.viewer.insert("insert", content)
        self.viewer.mark_set("insert", "insert + %d chars" % len(content))
        self.viewer.edit_modified(True)
        return "break"

    def _read_clipboard(self):
        """Read text from the clipboard, with X11 primary-selection fallback."""
        for selection in ("CLIPBOARD", "PRIMARY"):
            for data_type in (
                    "UTF8_STRING", "STRING", "TEXT", "COMPOUND_TEXT",
                    "text/plain;charset=utf-8",
                    "text/plain;charset=UTF-8", "text/plain",
                    "application/json"):
                try:
                    value = self.viewer.selection_get(
                        selection=selection, type=data_type)
                except tk.TclError:
                    continue
                if value:
                    return value
        for data_type in ("UTF8_STRING", "STRING", "TEXT", "COMPOUND_TEXT"):
            try:
                value = self.viewer.clipboard_get(type=data_type)
            except tk.TclError:
                continue
            if value:
                return value
        try:
            value = self.viewer.clipboard_get()
        except tk.TclError:
            value = ""
        if value:
            return value
        raise tk.TclError("No text clipboard selection")

    def _paste_native_document(self):
        """Fallback to Tk's native Text paste binding for system clipboards."""
        original = self.viewer.get("1.0", "end-1c")
        self.viewer.edit_modified(False)
        self.viewer.delete("1.0", "end")
        self.viewer.mark_set("insert", "1.0")
        try:
            self.viewer.tk.call("tk_textPaste", self.viewer._w)
        except tk.TclError:
            self._restore_draft(original)
            return False
        if not self.viewer.get("1.0", "end-1c"):
            self._restore_draft(original)
            return False
        self._layout_on_apply = True
        self.viewer.edit_modified(True)
        return True

    def _restore_draft(self, content):
        self.viewer.edit_modified(False)
        self.viewer.delete("1.0", "end")
        if content:
            self.viewer.insert("1.0", content)
        self.viewer.mark_set("insert", "end-1c")
        self.viewer.edit_modified(False)

    def _on_json_modified(self, _event=None):
        if self._loading_json or not self.viewer.edit_modified():
            return
        self.viewer.edit_modified(False)
        if self._validation_job is not None:
            self.after_cancel(self._validation_job)
        self._validation_job = self.after(250, self._validate_json_draft)

    def _validate_json_draft(self):
        self._validation_job = None
        if self.on_json_change is None:
            return
        draft = self.viewer.get("1.0", "end-1c")
        if draft == "":
            result = self.on_json_change(
                "", auto_layout=self._layout_on_apply)
            if result is True:
                self._layout_on_apply = False
            self.set_validation_status(result)
            return
        result = self.on_json_change(
            draft, auto_layout=self._layout_on_apply)
        if result is True:
            self._layout_on_apply = False
        self.set_validation_status(result)

    def _replace_draft(self, content, auto_layout=False):
        self._layout_on_apply = auto_layout
        self.viewer.edit_modified(False)
        self.viewer.delete("1.0", "end")
        if content:
            self.viewer.insert("1.0", content)
        self.viewer.mark_set("insert", "end-1c")
        self.viewer.edit_modified(True)

    def set_validation_status(self, error=None):
        if error is True:
            self._show_notice("Canvas updated from JSON",
                              theme.NODE_TYPES["task"]["accent"])
        elif error:
            self._show_notice(f"JSON warning (canvas unchanged): {error}",
                              theme.NODE_TYPES["response"]["accent"])
        else:
            self._hide_notice()

    def show_ai_execution_notice(self):
        self._show_notice(
            "AI-only: no manual create, move, or edit.",
            theme.NODE_TYPES["plan"]["accent"])

    def _show_notice(self, text, color):
        self._cancel_notice_animation()
        self._notice_text = text
        self._status.configure(text=text, fg=color)
        self._status.configure(wraplength=max(120, self.winfo_width() - 48))
        if self.collapsed or self._animating:
            return
        self._status.pack(fill="x")
        if not self._notice_area.winfo_manager():
            self._notice_area.configure(height=0)
            self._notice_area.pack(
                fill="x", padx=14, pady=(0, 6), before=self._viewer_frame)
        self._animate_notice_in()

    def _animate_notice_in(self):
        height = int(self._notice_area.cget("height"))
        height = min(self.NOTICE_HEIGHT, height + 4)
        self._notice_area.configure(height=height)
        if height < self.NOTICE_HEIGHT:
            self._notice_animation_job = self.after(12,
                                                    self._animate_notice_in)
        else:
            self._notice_animation_job = None

    def _hide_notice(self):
        self._notice_text = None
        if not self._notice_area.winfo_manager():
            return
        self._cancel_notice_animation()
        self._animate_notice_out()

    def _animate_notice_out(self):
        height = max(0, int(self._notice_area.cget("height")) - 4)
        self._notice_area.configure(height=height)
        if height:
            self._notice_animation_job = self.after(12,
                                                    self._animate_notice_out)
        else:
            self._notice_animation_job = None
            self._status.pack_forget()
            self._notice_area.pack_forget()

    def _cancel_notice_animation(self):
        if self._notice_animation_job is not None:
            self.after_cancel(self._notice_animation_job)
            self._notice_animation_job = None

    def set_animating(self, animating: bool) -> None:
        if self._animating == animating:
            return
        self._animating = animating
        if animating:
            self._cancel_notice_animation()
            for child in self.pack_slaves():
                child.pack_forget()
            for child in self.place_slaves():
                child.place_forget()
        else:
            self._set_content_visible(not self.collapsed)

    def toggle_compact(self):
        """Minimize the panel to a narrow rail (~5% of its normal width;
        the < handle on the rail expands it back) or restore it. The app
        owns the column geometry."""
        self.collapsed = not self.collapsed
        self.set_animating(True)
        if self.collapsed:
            self.master.collapse_future()
        else:
            self.master.expand_future()
