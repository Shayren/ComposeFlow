"""Small per-window cache for card fonts used at canvas zoom levels."""

import tkinter.font as tkfont


def scaled_font(widget, spec, zoom, slant=None):
    root = widget.winfo_toplevel()
    cache = getattr(root, "_composeflow_font_cache", None)
    if cache is None:
        cache = {}
        root._composeflow_font_cache = cache

    spec_key = tuple(spec) if isinstance(spec, (tuple, list)) else str(spec)
    base = cache.get(("base", spec_key))
    if base is None:
        source = tkfont.Font(root=root, font=spec)
        base = (source.actual("family"), source.actual("size"),
                source.actual("weight"), source.actual("slant"))
        cache[("base", spec_key)] = base

    family, size, weight, base_slant = base
    size = max(1, round(size * zoom))
    slant = slant or base_slant
    key = ("scaled", spec_key, slant)
    entry = cache.get(key)
    if entry is None:
        font = tkfont.Font(root=root, family=family, size=size,
                           weight=weight, slant=slant)
        cache[key] = (font, size)
    else:
        font, current_size = entry
        if current_size != size:
            font.configure(size=size)
            cache[key] = (font, size)
    return font
