"""ComposeFlow design tokens.

Single source of truth for colors, fonts, and dimensions shared by all
UI modules. Theme-owning agent (Conductor) contract: do not hardcode
colors/dimensions in ui modules; import from here.
"""

# ---------------------------------------------------------------- colors
# The flow canvas is the LIGHTEST surface (it carries the graph) but stays
# comfortably darker than the old scheme; every chrome section (node list,
# header, JSON area, cards) is darker still. Tones are warm gray, not blue.
BG = "#0c0d0f"            # application background (darkest)
PANEL_BG = "#141518"      # node list / header / future-area background
PANEL_BG_ALT = "#191b1f"  # hover / active panel surface
BORDER = "#282a2e"        # panel border
TEXT = "#d9dadc"          # primary text
TEXT_MUTED = "#9ca0a6"    # secondary text
CANVAS_BG = "#1f2123"     # flow canvas background (lightest, still dark)
GRID = "#26292c"          # canvas grid dots
SELECT = "#4da3ff"        # selection highlight (generic)
WIRE_HOVER = "#ff5b5b"    # wire-tracing endpoint highlight
WIRE_DIM = "#55595e"      # unrelated wires while a wire is traced

# Canvas node resting surface (unselected). The node is a neutral box:
# border ~20% lighter than the canvas background, fill ~10% lighter.
# Accent color stays reserved for the selected node.
NODE_BORDER_NORMAL = "#4c4d4f"      # CANVAS_BG lightened 20%
NODE_FILL_NORMAL = "#353739"        # CANVAS_BG lightened 10%

# Library card interaction states. Cards are rounded canvas items:
# hover lights the surface (lighter) and border, press darkens the
# surface with the same border, dragging swaps the border to the node
# type's accent.
CARD_BORDER_HOVER = "#6e7076"  # hover / pressed: border line color
CARD_FILL_HOVER = "#21242a"    # library card hover surface (slightly lighter than PANEL_BG_ALT)
CARD_FILL_PRESSED = "#121317"  # library card pressed surface (slightly darker than PANEL_BG_ALT)
NODE_SHADOW = "#0b0c0e"        # canvas node drop shadow
NODE_RADIUS = 10               # canvas node corner radius @ zoom 1.0

WIRE_CARD_CLEARANCE = 16.0
AI_REGION_PADDING = 24.0
WIRE_REGION_CLEARANCE = 16.0
WIRE_LOCAL_MARGIN_BASE = 180.0
WIRE_LOCAL_MARGIN_MIN = 96.0
WIRE_LOCAL_MARGIN_MAX = 400.0

TITLE_HOVER_DELAY_MS = 500
TITLE_SCROLL_INTERVAL_MS = 100

# Flow JSON Viewer labels.
FUTURE_LABEL = "FLOW JSON"
FUTURE_SUBTEXT = "SEMANTIC WORKFLOW"

# ------------------------------------------------------------- node types
# Node types include user-authored nodes and report-only AI execution cards.
# type key -> display label + accent color. The flow canvas node and the
# library card for a type share the same accent; the library order is
# defined by NODE_SECTIONS / NODE_ORDER below.
AI_ACCENT = "#3db9ad"  # Shared accent for AI execution artifacts
PLAN_ACCENT = "#3db9ad"
ACTION_ACCENT = "#f28c4b"
EVALUATION_ACCENT = "#e278a1"
AI_REGION_FILL = "#151a1b"    # AI Execution backdrop fill (slightly bluer
                              # than the canvas so the stage reads as a zone)
AI_REGION_BORDER = "#1f3235"  # AI execution backdrop outline
# Pin colors identify artifacts. They do not encode node type or ownership.
SEMANTIC_COLORS = {
    "data": "#4d9fff",
    "context": "#a06bdc",
    "contract": "#e5a94f",
    "result": "#3fbc6f",
    "control": "#9ca0a6",
    "ai": AI_ACCENT,
}

CONTROL_COLOR = SEMANTIC_COLORS["control"]

NODE_TYPES = {
    "task":       {"label": "Task",       "accent": SEMANTIC_COLORS["result"]},
    "input":      {"label": "Input",      "accent": SEMANTIC_COLORS["data"]},
    "context":    {"label": "Context",    "accent": SEMANTIC_COLORS["context"]},
    "response":   {"label": "Response",   "accent": SEMANTIC_COLORS["contract"]},
    "plan":       {"label": "Plan",       "accent": PLAN_ACCENT},
    "action":     {"label": "Action",     "accent": ACTION_ACCENT},
    "evaluation": {"label": "Evaluation", "accent": EVALUATION_ACCENT},
}

# Library sections, in display order. NODE_ORDER is derived from these so a
# type can never be added to sections without appearing in the library.
NODE_SECTIONS = (
    ("USER INTENT", ("input", "context", "task")),
    ("AI EXECUTION", ("plan", "action", "evaluation")),
    ("OUTPUT", ("response",)),
)

NODE_ORDER = [t for _title, types in NODE_SECTIONS for t in types]  # library display order
USER_NODE_TYPES = frozenset(("input", "context", "task", "response"))
AI_NODE_TYPES = frozenset(("plan", "action", "evaluation"))

# Semantic key for every pin, keyed by (node type, port). Covers all of
# NODE_PINS; canvas pin fills look up SEMANTIC_COLORS[semantic].
PORT_SEMANTICS = {
    ("task", "data"): "data",
    ("task", "context"): "context",
    ("task", "after"): "control",
    ("task", "contract"): "contract",
    ("task", "next"): "control",
    ("task", "task"): "ai",
    ("input", "data"): "data",
    ("context", "context"): "context",
    ("response", "contract"): "contract",
    ("response", "result"): "result",
    ("plan", "task"): "ai",
    ("plan", "context"): "context",
    ("plan", "plan"): "ai",
    ("plan", "criteria"): "ai",
    ("action", "plan"): "ai",
    ("action", "data"): "data",
    ("action", "output"): "ai",
    ("action", "observation"): "ai",
    ("evaluation", "output"): "ai",
    ("evaluation", "observation"): "ai",
    ("evaluation", "criteria"): "ai",
    ("evaluation", "result"): "result",
}

# Visible pin labels on the node cards, keyed by (node type, semantic port).
# Display labels and connection pin ids share the semantic artifact names.
PIN_LABELS = {
    ("task", "data"): "Data",
    ("task", "context"): "Context",
    ("task", "after"): "After",
    ("task", "contract"): "Contract",
    ("task", "next"): "Next",
    ("task", "task"): "Task",
    ("input", "data"): "Data",
    ("context", "context"): "Context",
    ("response", "contract"): "Contract",
    ("response", "result"): "Result",
    ("plan", "task"): "Task",
    ("plan", "context"): "Context",
    ("plan", "plan"): "Plan",
    ("plan", "criteria"): "Criteria",
    ("action", "plan"): "Plan",
    ("action", "data"): "Data",
    ("action", "output"): "Output",
    ("action", "observation"): "Observation",
    ("evaluation", "result"): "Result",
    ("evaluation", "output"): "Output",
    ("evaluation", "observation"): "Observation",
    ("evaluation", "criteria"): "Criteria",
}

# Pin layout per node card type: (port, side, y) triples. side "l"
# = input/left-docked, "r" = output/right-docked (see ExecutionCard /
# TaskCard). The flow canvas derives its wire anchor points from these, so
# every card type's pins live in the same dict.
NODE_PINS = {
    "task": (("data", "l", 44), ("context", "l", 61), ("after", "l", 78),
             ("contract", "r", 44), ("next", "r", 61), ("task", "r", 78)),
    "input": (("data", "r", 48),),
    "context": (("context", "r", 48),),
    # The accepted runtime result enters above the user-authored Contract.
    # This order matches the upper execution and lower authored lanes, so
    # their incoming wires can reach separate pins without crossing.
    "response": (("result", "l", 44), ("contract", "l", 61)),
    "plan": (("task", "l", 44), ("context", "l", 61),
             ("plan", "r", 44), ("criteria", "r", 61)),
    "action": (("plan", "l", 44), ("data", "l", 61),
               ("output", "r", 44), ("observation", "r", 61)),
    "evaluation": (("output", "l", 44), ("observation", "l", 61),
                   ("criteria", "l", 78), ("result", "r", 44)),
}

# ----------------------------------------------------------- typography
FONT_UI = ("Helvetica", 10)
FONT_UI_BOLD = ("Helvetica", 10, "bold")
FONT_SMALL = ("Helvetica", 9)
FONT_BRAND = ("Helvetica", 13, "bold")
FONT_NODE = ("Helvetica", 12, "bold")

# ----------------------------------------------------------- dimensions
HEADER_H = 46                 # header strip height
# Column width ratio (node list : canvas : JSON structure).
# COLLAPSED: the node list shrinks to a narrow rail (~5% of its normal
# width, floored at NodeList.RAIL_MIN so the > handle fits on it and
# never overlaps the canvas).
COL_RATIO = (1.5, 5.5, 3.0)          # expanded node list
COL_RATIO_COLLAPSED = (0.075, 6.925, 3.0)  # minimized: narrow rail

# RIGHT-side mirror: the JSON/user-prompt panel shrinks to a narrow rail
# (~5% of its normal width, floored at FuturePanel.RAIL_MIN so the <
# handle fits on it and never overlaps the canvas; node list stays put).
COL_RATIO_RIGHT_COLLAPSED = (1.5, 8.425, 0.075)  # minimized: narrow rail

# Side-panel widths are NOT fixed: the app-grid owns them via the strict
# column ratio above, so the only width hints here are the card's height
# and vertical rhythm.
CARD_H = 48                   # library card height (both modes)
CARD_PAD = 10                 # vertical gap between library cards
CANVAS_NODE_W = 200           # canvas node width  (5:4 aspect)
CANVAS_NODE_H = 160           # canvas node height (5:4 aspect)
# Per-type canvas node dimensions. Task, Input, and Context share a 230px
# width; Response is wider to give its three format options clear spacing.
TASK_CARD_W = 230             # task card width
TASK_CARD_H = 196             # task card height
INPUT_CARD_W = 230            # input card width (design-system width, = task)
INPUT_CARD_H = 232            # input card height
INPUT_FILE_LABEL_Y = 72
INPUT_FILE_ROW_Y = 80
INPUT_FILE_ROW_H = 20
INPUT_FILE_MARGIN_X = 12
INPUT_FILE_BUTTON_W = 52
INPUT_FILE_GAP = 8
INPUT_FILE_FIELD_W = (INPUT_CARD_W - 2 * INPUT_FILE_MARGIN_X
                      - INPUT_FILE_BUTTON_W - INPUT_FILE_GAP)
CONTEXT_CARD_H = 244
CONTEXT_DESCRIPTION_BOX_Y = 82
CONTEXT_DESCRIPTION_BOX_H = 88
CONTEXT_DESCRIPTION_TEXT_Y = 84
CONTEXT_DESCRIPTION_TEXT_H = 84
CONTEXT_FILES_LABEL_Y = 188
CONTEXT_FILES_ROW_Y = 207
CONTEXT_FILES_ROW_H = 22
CONTEXT_FILES_MARGIN_X = 12
CONTEXT_FILES_BUTTON_W = 52
CONTEXT_FILES_GAP = 8
RESPONSE_CARD_H = 234         # Response pin plus spaced format/style controls
RESPONSE_CARD_W = 280        # Give the three format options room to breathe
RESPONSE_RESULT_CARD_H = 386
AI_CARD_W = 280               # shared width for readable execution details
AI_CARD_H = 240               # shared height for pins and report content
AI_CARD_GAP = 72
NODE_DIMS = {"task": (TASK_CARD_W, TASK_CARD_H),
             "input": (INPUT_CARD_W, INPUT_CARD_H),
             "context": (TASK_CARD_W, CONTEXT_CARD_H),
             "response": (RESPONSE_CARD_W, RESPONSE_CARD_H),
             "plan": (AI_CARD_W, AI_CARD_H),
             "action": (AI_CARD_W, AI_CARD_H),
             "evaluation": (AI_CARD_W, AI_CARD_H)}
# Creation/drop snap grid (top-left corner snaps to these multiples).
# Each coarse cell (280x240, one task-card-plus-gap) is split 4x4 into
# 70x60 sub-cells. Sub-cells are smaller than a node, so grid-adjacent
# nodes may overlap by design. The visual background dot/squares grid
# (GRID_STEP spacing) is untouched — this is a separate logical grid.
# ------------------------------------------------------- unknown node type
# Nodes whose `type` is not one of the four known content types are kept as
# Unknown Nodes: an unmistakeable card that preserves the original type
# string, all extra properties, and its connections so documents survive
# round trips. Deliberately NOT entries in NODE_TYPES/NODE_DIMS/NODE_ORDER.
UNKNOWN_W = 230
UNKNOWN_H = 170
UNKNOWN_DIMS = (UNKNOWN_W, UNKNOWN_H)
UNKNOWN_LABEL = "Unknown Node"
UNKNOWN_ACCENT = "#9a8a5d"  # desaturated umber: clearly not a known accent

# ----------------------------------------------------------- dimensions
CREATE_GRID_X = 70.0
CREATE_GRID_Y = 60.0
GRID_STEP = 20                # grid cell size at zoom 1.0 (screen px)
GRID_MARK = 6.0               # grid mark half-size: solid 12x12 px squares (screen-space)
