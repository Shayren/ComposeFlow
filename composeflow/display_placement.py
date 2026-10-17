"""Choose a visible display for the ComposeFlow window.

Place the window on the connected output under the pointer. If the pointer
is outside all outputs, prefer the laptop panel, then the first connected
output. This also handles XWayland displays without a laptop identifier.
"""

import re
import subprocess

# LAPTOP_MM_MAX: physical panel widths below this are assumed built-in
# laptop panels (laptop screens are typically <= ~17" ~ 380mm wide;
# external monitors >= ~21.5" ~ 476mm). This heuristic exists because Tk
# 8.6 has no multi-monitor API and WSLg names outputs XWAYLANDn with no
# internal/external name hint.
LAPTOP_MM_MAX = 420

_OUTPUT_RE = re.compile(
    r"^(\S+)\s+connected(\s+primary)?\s+(\d+)x(\d+)([+-]\d+)([+-]\d+)"
    r"(?:.*?(\d+)mm\s*x\s+(\d+)mm)?$"
)


def query_outputs(runner=None):
    """Run `xrandr --query` and parse connected output geometries.

    Returns a list of dicts {"name", "x", "y", "w", "h", "primary",
    "mm_w", "mm_h"}; on any failure (missing binary, nonzero rc, raise,
    parse problem from runner) returns []. Physical size is only recorded
    when present and nonzero.
    """
    try:
        if runner is None:
            cp = subprocess.run(["xrandr", "--query"],
                                capture_output=True, text=True)
        else:
            cp = runner()
        if getattr(cp, "returncode", 0) != 0:
            return []
        lines = (cp.stdout or "").splitlines()
    except Exception:
        return []

    outputs = []
    for line in lines:
        m = _OUTPUT_RE.match(line.strip())
        if not m:
            continue
        name, primary, w, h, x, y, mmw, mmh = m.groups()
        mm_w = int(mmw) if mmw else None
        mm_h = int(mmh) if mmh else None
        outputs.append({
            "name": name,
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "primary": bool(primary),
            "mm_w": mm_w if mm_w else None,
            "mm_h": mm_h if mm_h else None,
        })
    return outputs


def select_display(outputs):
    """Pick the output most likely to be the built-in laptop panel."""
    for out in outputs:
        if out["name"].lower().startswith(("edp-", "lvds-", "dsi-", "idp-")):
            return out
    for out in outputs:
        if out["mm_w"] is not None and 0 < out["mm_w"] < LAPTOP_MM_MAX:
            return out
    for out in outputs:
        if out["primary"]:
            return out
    if len(outputs) == 1:
        return outputs[0]
    return None


def place_app_on_laptop_display(root):
    """Resize root to 2/3 of a connected output and center it there.

    The requested size (2/3 of the panel) always fits the output, so no
    clamping is needed; Tk still enforces the app's own minsize if an
    unusually small output were selected. Returns the chosen output dict,
    or None (the WM decides) when no output can be identified.
    """
    outputs = query_outputs()
    pointer_x, pointer_y = root.winfo_pointerxy()
    out = next((candidate for candidate in outputs
                if pointer_x is not None and pointer_y is not None
                and candidate["x"] <= pointer_x < candidate["x"] + candidate["w"]
                and candidate["y"] <= pointer_y < candidate["y"] + candidate["h"]),
               None)
    if out is None:
        out = select_display(outputs)
    if out is None and outputs:
        out = outputs[0]
    if out is None:
        return None
    w = out["w"] * 2 // 3
    h = out["h"] * 2 // 3
    x = out["x"] + (out["w"] - w) // 2
    y = out["y"] + (out["h"] - h) // 2
    root.geometry(f"{w}x{h}{x:+d}{y:+d}")
    return out
