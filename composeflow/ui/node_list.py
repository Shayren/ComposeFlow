"""ComposeFlow node library: draggable cards, one per node type.

The cards are the drag SOURCE side of a tkinter.dnd handshake. Card
instances expose `.node_type` (read by the canvas on drop) and a `dnd_end`
hook that tkinter.dnd always calls after a drag. No flow-canvas knowledge here.
"""

import tkinter as tk
from tkinter import dnd

from composeflow import theme
from .rounded_button import (
    RoundedButton, point_in_rounded_rect, rounded_rect_points,
)


class NodeCard(tk.Canvas):
    """A single draggable library card drawn as a rounded rectangle on a
    Canvas. `node_type` identifies the node.

    The canvas IS the card: a rounded body polygon plus an accent bar and
    a text label, with no child widgets underneath. The whole canvas is
    the drag handle (canvas items receive no events), so the trigger is
    the visible rounded shape itself. Identity = accent bar + label.
    States: hover => lighter surface, pressed => darker surface, drag =>
    accent outline; normal => flat, invisible-bordered card.
    """

    CARD_RADIUS = 10   # px: restrained but clearly rounded at CARD_H=48
    node_type = ""
    _dragging = False

    def __init__(self, master, node_type, **kw):
        kw.setdefault("bg", theme.PANEL_BG)
        super().__init__(
            master, bd=0, highlightthickness=0,
            cursor=("arrow" if node_type in theme.AI_NODE_TYPES else "hand2"),
            width=0, height=theme.CARD_H, **kw)
        self.node_type = node_type
        info = theme.NODE_TYPES[node_type]
        self._accent = info["accent"]
        self._label_text = info["label"]

        self._dnd = None    # active tkinter.dnd DndHandler, if any
        self._state = "normal"
        self._compact = False
        self._body = None
        self._accent_bar = None
        self._label = None
        self._tooltip = None
        self._tooltip_job = None
        # The canvas itself is always the drag handle: no child widgets,
        # so no child bindings, so no hidden rectangular widget underneath.
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", lambda e: self._draw())

    # ------------------------------------------------------- geometry
    def _shape(self):
        """Canvas-local rect the card body occupies (1px inset so the
        outline stroke is not clipped at the canvas edge)."""
        w, h = self.winfo_width(), self.winfo_height()
        return 1, 1, max(2, w - 1), max(2, h - 1)

    def _radius(self):
        # clamp: corner radius <= min(width/2, height/2), per the shape
        x0, y0, x1, y1 = self._shape()
        return min(self.CARD_RADIUS, (x1 - x0) / 2, (y1 - y0) / 2)

    def _inside(self, x, y):
        """Point-in-rounded-rect test: the trigger follows the shape, so
        corner slivers are outside the card."""
        return point_in_rounded_rect(x, y, *self._shape(), self._radius())

    # ------------------------------------------------------- visual states
    def _set_state(self, state):
        """Recolor the body for the current state; geometry stays put.
        The outline width stays 2 for every state (no 1px jump on hover).
        """
        self._state = state
        if self._body is None:
            return
        if state == "drag":
            fill, outline = theme.PANEL_BG_ALT, self._accent
        elif state == "hover":
            fill, outline = theme.CARD_FILL_HOVER, theme.CARD_BORDER_HOVER
        elif state == "pressed":
            fill, outline = theme.CARD_FILL_PRESSED, theme.CARD_BORDER_HOVER
        else:
            fill = outline = theme.PANEL_BG_ALT
        self.itemconfig(self._body, fill=fill, outline=outline)

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 8 or h < 8:
            return
        x0, y0, x1, y1 = self._shape()
        self.delete("all")
        self._body = self.create_polygon(
            rounded_rect_points(x0, y0, x1 - x0, y1 - y0, self._radius()),
            smooth=True, fill=theme.PANEL_BG_ALT,
            outline=theme.PANEL_BG_ALT, width=2)
        if self._compact:
            bar_w = 6
            self._accent_bar = self.create_rectangle(
                max(2, (w - bar_w) / 2), 5,
                max(2, (w + bar_w) / 2), h - 5,
                fill=self._accent, outline="")
            self._label = None
            self._set_state(self._state)
            return
        # Accent bar: 4px wide, inset from the corner arcs so it never
        # breaks through the rounded corners.
        self._accent_bar = self.create_rectangle(
            10, 12, 14, h - 12, fill=self._accent, outline="")
        if self.node_type in theme.AI_NODE_TYPES:
            self._label = self.create_text(
                22, h / 2 - 7, text=self._label_text,
                font=theme.FONT_UI_BOLD, fill=theme.TEXT, anchor="w")
            self.create_text(
                22, h / 2 + 11, text="AI ONLY",
                font=theme.FONT_SMALL, fill=theme.TEXT_MUTED, anchor="w")
        else:
            self._label = self.create_text(
                22, h / 2, text=self._label_text,
                font=theme.FONT_UI_BOLD, fill=theme.TEXT, anchor="w")
        self._set_state(self._state)

    def _on_enter(self, event):
        if not self._dragging and self.node_type not in theme.AI_NODE_TYPES:
            self._set_state("hover")
        if self._compact and self._tooltip_job is None:
            self._tooltip_job = self.after(300, self._show_tooltip)

    def _on_leave(self, event):
        self._cancel_tooltip()
        if not self._dragging:
            self._set_state("normal")

    def _cancel_tooltip(self):
        if self._tooltip_job is not None:
            self.after_cancel(self._tooltip_job)
            self._tooltip_job = None
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def _show_tooltip(self):
        self._tooltip_job = None
        if not self._compact or not self.winfo_exists():
            return
        self._tooltip = tk.Toplevel(self)
        self._tooltip.overrideredirect(True)
        text = theme.NODE_TYPES[self.node_type]["label"]
        if self.node_type in theme.AI_NODE_TYPES:
            text += " · AI ONLY · READ ONLY"
        label = tk.Label(
            self._tooltip, text=text,
            font=theme.FONT_SMALL, bg=theme.PANEL_BG_ALT, fg=theme.TEXT,
            padx=8, pady=4, highlightthickness=1,
            highlightbackground=theme.BORDER)
        label.pack()
        self._tooltip.geometry(
            f"+{self.winfo_rootx() + self.winfo_width() + 6}"
            f"+{self.winfo_rooty() + (self.winfo_height() - 24) // 2}")

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._cancel_tooltip()
        self._compact = compact
        self.configure(height=26 if compact else theme.CARD_H)
        self._draw()

    def _on_press(self, event):
        # Corner slivers are outside the rounded shape: do not start the
        # press/drag from them.
        if not self._inside(event.x, event.y):
            return
        if self.node_type in theme.AI_NODE_TYPES:
            notify = getattr(self.master, "on_ai_node_interaction", None)
            if notify is not None:
                notify()
            return "break"
        self._cancel_tooltip()
        self._set_state("pressed")
        # DndHandler replaces the widget-level <Motion> binding (Tk bind()
        # overwrites), so listen at the "all" bindtag instead. The accent
        # "drag" state then turns on the instant the first drag motion lands
        # anywhere in the app.
        self.bind_all("<Motion>", self._on_motion)
        self._dnd = dnd.dnd_start(self, event)

    def _on_motion(self, event):
        # tkinter.dnd's DndHandler never calls source.dnd_start(), so the
        # accent "drag" state fires from the first motion while a drag from
        # this card is active.
        if self._dnd is not None and not self._dragging:
            self.dnd_start(self, event)

    def _on_release(self, event):
        self.unbind_all("<Motion>")
        if not self._dragging:
            self._set_state("normal")

    # --------------------------------------- tkinter.dnd drag-source hooks
    def dnd_start(self, source, event):
        """tkinter.dnd calls this on the first real motion of a drag."""
        self._dragging = True
        self._set_state("drag")

    def dnd_end(self, target, event):
        self._dnd = None
        self._dragging = False
        self.unbind_all("<Motion>")
        self._set_state("normal")


class NodeList(tk.Frame):
    """Left library panel holding one NodeCard per node type.

    Collapsed, the panel shrinks to a narrow vertical rail: heading, section
    header, cards, and the header row hide, and a small rounded handle near
    the rail's top holds the ">" button that expands the panel back. The
    rail is wide enough to host the handle INSIDE it (no canvas overlap).
    Panel content is only packed/unpacked -- card state is never rebuilt.
    """

    BTN_SIZE = 26    # px: rounded > expand button (rail handle) size
    RAIL_MIN = BTN_SIZE + 4

    def _make_btn(self, parent, glyph):
        """One rounded trigger button, used for BOTH the < collapse toggle
        and the > expand handle so the two controls always share size,
        border, font, and colors (canvas-drawn, true rounded corners)."""
        return RoundedButton(
            parent, text=glyph, command=self.toggle_compact,
            width=self.BTN_SIZE, height=self.BTN_SIZE, radius=8,
            font=theme.FONT_SMALL, fill=theme.PANEL_BG_ALT,
            fg=theme.TEXT_MUTED, outline=theme.BORDER, outlinewidth=1,
            page_bg=theme.PANEL_BG)

    def __init__(self, master, **kw):
        # The column width is owned by the app grid's column ratio, so this
        # panel requests no width of its own; cards fill whatever it gets.
        kw.setdefault("width", 0)
        kw.setdefault("bg", theme.PANEL_BG)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", theme.BORDER)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self.collapsed = False
        self._animating = False
        self.on_ai_node_interaction = None
        self._cards = []
        self._sections = []   # [(section Label, [NodeCard, ...]), ...]

        # Header row: brand heading + the "<" collapse button (the same
        # square format as the rail's > button). Hidden when collapsed
        # (the rail handle replaces it).
        self._top = tk.Frame(self, bg=theme.PANEL_BG)
        self._heading = tk.Label(
            self._top, text="NODE LIBRARY", font=theme.FONT_SMALL,
            bg=theme.PANEL_BG, fg=theme.TEXT_MUTED,
        )
        self._toggle = self._make_btn(self._top, "<")
        self._toggle.pack(side="right", padx=(0, 8), pady=(10, 6))

        # Section headers above the card lists, same style as the panel
        # heading (small muted capitals), aligned with the card edges.
        # `self._section` stays the FIRST section's label (USER INTENT) so
        # existing probes/tests keep working.
        self._section = None

        # Collapsed-state expand handle: the same rounded button, placed at
        # the rail's top. place()-based, so it keeps its natural size no
        # matter how narrow the rail is; the rail is floored at RAIL_MIN so
        # the handle never overlaps the canvas.
        self._expand = self._make_btn(self, ">")

        self._add_cards()
        self._set_content_visible(True)

    def _set_content_visible(self, visible):
        """Pack / unpack the layout for the current state.

        Expanded: header row first, then heading, then the cards. Collapsed:
        everything hidden except the > handle, placed at the rail's top,
        flushed with the rail's right edge (inside it). All sibling packing
        happens HERE, so the pack order (header above cards) can never be
        violated.
        """
        if visible:
            # before=self._cards[0]: pack order must be preserved on
            # re-expand; Tk appends re-packed widgets at the pack-order end,
            # which would drop the header below the cards. Only valid once
            # the cards are packed (initial construction packs them after).
            order = {"before": self._cards[0]} \
                if self._cards[0].winfo_manager() else {}
            self._top.pack(fill="x", **order)
            self._toggle.configure(text="<")
            self._heading.pack(side="left", padx=12, pady=(12, 8))
            # USER INTENT section label first, then every card (so re-packed
            # cards land after the label), then each later section's label
            # anchored before its own first card.
            self._section.pack(anchor="w", padx=14, pady=(4, 6), **order)
            for card in self._cards:
                card.set_compact(False)
                card.pack(fill="x", padx=14, pady=(0, theme.CARD_PAD))
            offset = len(self._sections[0][1])
            for label, _section_cards in self._sections[1:]:
                anchor = {"before": self._cards[offset]} \
                    if self._cards[offset].winfo_manager() else {}
                label.pack(anchor="w", padx=14, pady=(4, 6), **anchor)
                offset += len(_section_cards)
            self._expand.place_forget()
        else:
            self._top.pack_forget()
            self._heading.pack_forget()
            for label, _section_cards in self._sections:
                label.pack_forget()
            for index, card in enumerate(self._cards):
                card.set_compact(True)
                top_gap = self.BTN_SIZE + 18 if index == 0 else 5
                card.pack(fill="x", padx=3, pady=(top_gap, 5))
            self._expand.place(relx=1.0, x=-(self.BTN_SIZE + 2), y=14)

    def _add_cards(self):
        for title, node_types in theme.NODE_SECTIONS:
            label = tk.Label(
                self, text=title, font=theme.FONT_SMALL,
                bg=theme.PANEL_BG, fg=theme.TEXT_MUTED)
            cards = [NodeCard(self, node_type) for node_type in node_types]
            self._cards.extend(cards)
            self._sections.append((label, cards))
            if self._section is None:
                self._section = label

    def set_animating(self, animating: bool) -> None:
        if self._animating == animating:
            return
        self._animating = animating
        if animating:
            for child in self.pack_slaves():
                child.pack_forget()
            for child in self.place_slaves():
                child.place_forget()
        else:
            self._set_content_visible(not self.collapsed)

    def toggle_compact(self):
        """Minimize the panel to a narrow rail (~5% of its normal width;
        the > handle on the rail expands it back) or restore it. The app
        owns the column geometry."""
        self.collapsed = not self.collapsed
        self.set_animating(True)
        if self.collapsed:
            self.master.collapse_library()
        else:
            self.master.expand_library()
