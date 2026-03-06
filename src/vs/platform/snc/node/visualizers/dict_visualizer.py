"""Dictionary visualizer for Sculpt-n-Code."""

from visualizer_utils import BLUE, STRING, VALUE, GRAY, safe_repr, span


def truncate_container(items, limit, show_first=3):
    if len(items) <= limit:
        return list(items), 0
    remaining = len(items) - show_first
    return list(items)[:show_first], remaining

def get_fields(value):
    return [f"^[{repr(k)}]" for k in value.keys()]


def can_visualize(value):
    return isinstance(value, dict)

def visualize(value):
    if not value:
        return span("{}", BLUE)

    items, remaining = truncate_container(value.items(), 3, 2)
    pairs = [f'{span(safe_repr(k), STRING)}{span(":", BLUE)} {span(safe_repr(v), VALUE)}'
             for k, v in items]

    if remaining:
        pairs.append(span(f"... +{remaining} more", GRAY))

    content = ", ".join(pairs)
    return f'{span("{", BLUE)}{content}{span("}", BLUE)}'
