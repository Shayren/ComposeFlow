"""Semantic connection rules for authored and runtime graph relationships.

Pin type and connection ownership are separate: a Result pin remains a
Result regardless of whether a USER or SYSTEM connection reaches it.
"""

from . import theme


# (source type, source pin, target type, target pin) -> (edge type, owner)
USER_CONNECTIONS = {
    ("input", "data", "task", "data"): ("DATA", "USER"),
    ("context", "context", "task", "context"): ("DATA", "USER"),
    ("task", "next", "task", "after"): ("CONTROL", "USER"),
    ("task", "contract", "response", "contract"): ("DATA", "USER"),
    # Debug-authored execution-stage nodes can be connected manually. These
    # links share runtime pin semantics but are owned by the workflow.
    ("task", "task", "plan", "task"): ("DATA", "USER"),
    ("context", "context", "plan", "context"): ("DATA", "USER"),
    ("plan", "plan", "action", "plan"): ("DATA", "USER"),
    ("input", "data", "action", "data"): ("DATA", "USER"),
    ("action", "output", "evaluation", "output"): ("DATA", "USER"),
    ("action", "observation", "evaluation", "observation"): ("DATA", "USER"),
    ("plan", "criteria", "evaluation", "criteria"): ("DATA", "USER"),
}

SYSTEM_CONNECTIONS = {
    ("task", "task", "plan", "task"): ("DATA", "SYSTEM"),
    ("context", "context", "plan", "context"): ("DATA", "SYSTEM"),
    ("plan", "plan", "action", "plan"): ("DATA", "SYSTEM"),
    ("input", "data", "action", "data"): ("DATA", "SYSTEM"),
    ("action", "output", "evaluation", "output"): ("DATA", "SYSTEM"),
    ("action", "observation", "evaluation", "observation"): ("DATA", "SYSTEM"),
    ("plan", "criteria", "evaluation", "criteria"): ("DATA", "SYSTEM"),
    ("evaluation", "result", "response", "result"): ("DATA", "SYSTEM"),
}

EDGES = frozenset(USER_CONNECTIONS)
SYSTEM_EDGES = frozenset(SYSTEM_CONNECTIONS)
ALL_EDGES = EDGES | SYSTEM_EDGES
SOURCE_PORTS = frozenset((s, p) for s, p, _t, _tp in EDGES)
TARGET_PORTS = frozenset((t, tp) for _s, _p, t, tp in EDGES)
SYSTEM_SOURCE_PORTS = frozenset((s, p) for s, p, _t, _tp in SYSTEM_EDGES)
SYSTEM_TARGET_PORTS = frozenset((t, tp) for _s, _p, t, tp in SYSTEM_EDGES)


def _label(node_type):
    if node_type is None:
        return "Node"
    return theme.NODE_TYPES.get(node_type, {}).get("label", node_type)


def is_legal(source_type, source_port, target_type, target_port):
    """Whether a user may create the typed connection."""
    return (source_type, source_port, target_type, target_port) in EDGES


def canonical_user_edge(first_type, first_port, second_type, second_port):
    """Return the semantic USER edge for either endpoint selection order.

    Pin roles determine the stored direction. The order in which a user
    starts and ends a drag is only a gesture detail.
    """
    key = (first_type, first_port, second_type, second_port)
    if key in EDGES:
        return key
    reverse = (second_type, second_port, first_type, first_port)
    return reverse if reverse in EDGES else None


def is_user_endpoint(node_type, port):
    """Whether a pin belongs to at least one user-authored relationship."""
    return ((node_type, port) in SOURCE_PORTS
            or (node_type, port) in TARGET_PORTS)


def endpoints_for(node_type, port):
    """Return USER-connected pin counterparts in either gesture direction."""
    endpoints = set()
    for source_type, source_port, target_type, target_port in EDGES:
        if (source_type, source_port) == (node_type, port):
            endpoints.add((target_type, target_port))
        if (target_type, target_port) == (node_type, port):
            endpoints.add((source_type, source_port))
    return frozenset(endpoints)


def is_system(source_type, source_port, target_type, target_port):
    return (source_type, source_port, target_type, target_port) in SYSTEM_EDGES


def connection_properties(source_type, source_port, target_type, target_port):
    key = (source_type, source_port, target_type, target_port)
    return USER_CONNECTIONS.get(key) or SYSTEM_CONNECTIONS.get(key)


def kind_of(source_type, source_port, target_type, target_port):
    """Return DATA/CONTROL, or None for a pairing with no graph meaning."""
    properties = connection_properties(source_type, source_port,
                                       target_type, target_port)
    return properties[0] if properties else None


def ownership_of(source_type, source_port, target_type, target_port):
    properties = connection_properties(source_type, source_port,
                                       target_type, target_port)
    return properties[1] if properties else None


def is_source(source_type, source_port):
    return (source_type, source_port) in SOURCE_PORTS


def targets_for(source_type, source_port):
    return frozenset((target_type, target_port)
                     for source_t, source_p, target_type, target_port in EDGES
                     if (source_t, source_p) == (source_type, source_port))


def is_system_source(source_type, source_port):
    return (source_type, source_port) in SYSTEM_SOURCE_PORTS


def is_system_target(node_type, port):
    return (node_type, port) in SYSTEM_TARGET_PORTS


def reason(source_type, source_port, target_type, target_port):
    if (source_type, source_port) not in SOURCE_PORTS:
        return f"{_label(source_type)} has no user-connectable source pin '{source_port}'"
    if (target_type, target_port) not in TARGET_PORTS:
        return f"{_label(target_type)} has no user-connectable target pin '{target_port}'"
    if (source_type, source_port, target_type, target_port) in EDGES:
        return None
    return (f"{_label(source_type)}.{source_port} cannot connect to "
            f"{_label(target_type)}.{target_port}")
