import tkinter as tk

from .. import theme


class TitleMarquee:
    def __init__(self, entry: tk.Entry) -> None:
        self.entry = entry
        self._after_id: str | None = None
        self._scrolling = False
        entry.bind("<Enter>", self._on_enter, add="+")
        entry.bind("<Leave>", self._on_leave, add="+")
        entry.bind("<FocusIn>", self._on_focus, add="+")
        entry.bind("<KeyPress>", self._on_focus, add="+")
        entry.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, _event: tk.Event) -> None:
        self._cancel()
        self._scrolling = False
        self._after_id = self.entry.after(
            theme.TITLE_HOVER_DELAY_MS, self._start_scrolling)

    def _start_scrolling(self) -> None:
        self._after_id = None
        try:
            if self.entry.winfo_exists() and self.entry.xview()[1] < 1.0:
                self._scrolling = True
                self._scroll()
        except tk.TclError:
            self._scrolling = False

    def _scroll(self) -> None:
        try:
            if not self._scrolling or not self.entry.winfo_exists():
                return
            previous_view = self.entry.xview()
            self.entry.xview_scroll(1, "units")
            if self.entry.xview() != previous_view:
                self._after_id = self.entry.after(
                    theme.TITLE_SCROLL_INTERVAL_MS, self._scroll)
            else:
                self._scrolling = False
        except tk.TclError:
            self._scrolling = False
            self._after_id = None

    def _on_leave(self, _event: tk.Event) -> None:
        self._reset()

    def _on_focus(self, _event: tk.Event) -> None:
        self._reset()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.entry:
            self._cancel()
            self._scrolling = False

    def _reset(self) -> None:
        self._cancel()
        self._scrolling = False
        try:
            if self.entry.winfo_exists():
                self.entry.xview_moveto(0.0)
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.entry.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
