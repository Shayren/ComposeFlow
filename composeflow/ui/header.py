"""ComposeFlow top header strip: the brand only."""

import tkinter as tk

from composeflow import theme


class Header(tk.Frame):
    def __init__(self, master, **kw):
        kw.setdefault("height", theme.HEADER_H)
        kw.setdefault("bg", theme.PANEL_BG)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", theme.BORDER)
        super().__init__(master, **kw)
        self.pack_propagate(False)

        tk.Label(
            self, text="ComposeFlow", font=theme.FONT_BRAND,
            bg=theme.PANEL_BG, fg=theme.TEXT,
        ).pack(side="left", padx=14)