"""ComposeFlow rounded trigger button.

A small reusable Canvas-based button with true rounded corners and
button-like interaction (hover / pressed / armed-release / disabled).
The canvas IS the button: the rounded polygon is drawn on it and the
clickable region follows the rounded geometry — no transparent
rectangle stacked over a shape, no tk.Button anywhere.

Shared geometry contract: `rounded_rect_points` and
`point_in_rounded_rect` (module level) are the single source of truth
for the rounded-rect shape and its hit test; RoundedButton and NodeCard
both use them so their triggers always agree on the shape.
"""

import tkinter as tk

from .. import theme


def rounded_rect_points(x, y, w, h, r):
    """12-point smooth polygon approximating a rounded rectangle (same
    shape language as the flow-canvas nodes and the library cards). One
    item = no seams or border artifacts between arcs and rectangles.

    Shared geometry contract: NodeCard and RoundedButton render their
    rounded bodies with this exact polygon and hit-test with
    point_in_rounded_rect, so the two triggers always agree on shape.
    """
    r = max(0.0, min(r, w / 2, h / 2))
    return [
        x + r, y, x + w - r, y, x + w, y, x + w, y + r,
        x + w, y + h - r, x + w, y + h, x + w - r, y + h,
        x + r, y + h, x, y + h, x, y + h - r, x, y + r, x, y,
    ]


def point_in_rounded_rect(px, py, x0, y0, x1, y1, r):
    """Point-in-rounded-rect test over the bbox (x0, y0)-(x1, y1): the
    trigger follows the shape, not the bounding box (corner slivers are
    outside the shape)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r <= 0:
        return x0 <= px < x1 and y0 <= py < y1
    if (x0 + r <= px < x1 - r) or (y0 + r <= py < y1 - r):
        return True
    cx = x0 + r if px < x0 + r else x1 - r
    cy = y0 + r if py < y0 + r else y1 - r
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy <= r * r


class RoundedButton(tk.Canvas):
    """Rounded-rectangle button rendered entirely on a Canvas.

    Config: text, command, width/height/radius (px), fill (button body),
    fg (label), outline (border), outlinewidth, font, page_bg (the
    background the corners blend into), state ("normal" | "disabled").

    The callback fires only when the pointer is released INSIDE the
    rounded geometry after the press started inside it; pressing in and
    releasing out (or leaving the widget while pressed) never triggers.
    """

    _KEYS = ("text", "width", "height", "radius", "fill", "fg",
             "outline", "outlinewidth", "font", "page_bg", "state")

    def __init__(self, master, text="", command=None, width=96, height=36,
                 radius=10, fill=theme.PANEL_BG_ALT, fg=theme.TEXT,
                 outline=theme.BORDER, outlinewidth=1,
                 font=theme.FONT_UI_BOLD, page_bg=theme.PANEL_BG,
                 state="normal", **kw):
        kw.setdefault("bg", page_bg)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, width=width, height=height, **kw)
        self._o = {"text": text, "command": command, "width": width,
                   "height": height, "radius": radius, "fill": fill,
                   "fg": fg, "outline": outline,
                   "outlinewidth": outlinewidth, "font": font,
                   "page_bg": page_bg, "state": state}
        self._pressed = False
        self._hover = False
        self._armed = False
        self._body = None
        self._label = None
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    # -------------------------------------------------------------- geometry
    def _shape(self):
        """Canvas-local rect the button body occupies (1px inset so the
        outline stroke is not clipped at the canvas edge)."""
        w, h = self.winfo_width(), self.winfo_height()
        return 1, 1, max(2, w - 1), max(2, h - 1)

    def _radius(self):
        # clamp: radius <= min(width/2, height/2), per the shape
        x0, y0, x1, y1 = self._shape()
        return min(self._o["radius"], (x1 - x0) / 2, (y1 - y0) / 2)

    def _inside(self, x, y):
        """Point-in-rounded-rect test: the trigger follows the shape, not
        the canvas bounding box (corner slivers are outside the button)."""
        return point_in_rounded_rect(x, y, *self._shape(), self._radius())

    # --------------------------------------------------------------- drawing
    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        x0, y0, x1, y1 = self._shape()
        self.delete("all")
        self._body = self.create_polygon(
            rounded_rect_points(x0, y0, x1 - x0, y1 - y0, self._radius()),
            smooth=True, fill=self._o["fill"],
            outline=self._o["outline"], width=self._o["outlinewidth"])
        if self._o["text"] == "▶":
            half = min(w, h) * 0.2
            center_x = w / 2 + half / 3
            self._label = self.create_polygon(
                center_x - half, h / 2 - half,
                center_x + half, h / 2,
                center_x - half, h / 2 + half,
                fill=self._o["fg"], outline="")
        else:
            self._label = self.create_text(
                w / 2, h / 2, text=self._o["text"],
                font=self._o["font"], fill=self._o["fg"], anchor="center")
        self._visual()

    def _visual(self):
        """Recolor for the current state; geometry stays put."""
        if self._body is None:
            return
        if self._o["state"] == "disabled":
            fill, outline = theme.PANEL_BG, theme.PANEL_BG_ALT
            fg = theme.TEXT_MUTED
        elif self._pressed and self._armed:
            fill, outline = theme.PANEL_BG, theme.CARD_BORDER_HOVER
            fg = self._o["fg"]
        elif self._hover:
            fill, outline = self._o["fill"], theme.CARD_BORDER_HOVER
            fg = self._o["fg"]
        else:
            fill, outline = self._o["fill"], self._o["outline"]
            fg = self._o["fg"]
        self.itemconfig(self._body, fill=fill, outline=outline)
        self.itemconfig(self._label, fill=fg)

    # -------------------------------------------------------------- events
    def _on_enter(self, event):
        if self._o["state"] != "disabled":
            self._hover = True
            self._visual()

    def _on_leave(self, event):
        self._hover = False
        if self._pressed:
            self._armed = False   # releasing outside must not fire
        self._visual()

    def _on_press(self, event):
        if self._o["state"] == "disabled":
            return
        self._pressed = True
        self._armed = self._inside(event.x, event.y)
        self._visual()

    def _on_motion(self, event):
        if not self._pressed:
            return
        self._armed = self._inside(event.x, event.y)
        self._visual()

    def _on_release(self, event):
        if not self._pressed:
            return
        fired = self._armed and self._inside(event.x, event.y)
        self._pressed = False
        self._armed = False
        self._visual()
        if fired:
            cmd = self._o["command"]
            if cmd is not None:
                cmd()

    # ------------------------------------------------------------- configure
    def cget(self, key):
        return self._o[key]

    def __getitem__(self, key):
        return self.cget(key)

    def configure(self, **kw):
        redraw = False
        for key, value in kw.items():
            if key == "command":
                self._o["command"] = value
                continue
            if key not in self._o:
                raise tk.TclError(f"unknown option \"-{key}\"")
            if key in ("width", "height"):
                super().configure(**{key: value})
            elif key == "page_bg":
                super().configure(bg=value)
            self._o[key] = value
            if key in ("text", "font", "radius"):
                redraw = True
        if redraw:
            self._draw()
        else:
            self._visual()
