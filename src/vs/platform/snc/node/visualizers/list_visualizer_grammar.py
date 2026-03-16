"""Bidirectional grammar for the list visualizer.

Defines rules for parsing and generating list comprehension expressions
so users can select generated code in the editor and have the visualizer
link to it for live editing.
"""

import ast
import re
from bidirectional_dsl import BiTemplate, Alt, BASE_RULES, make_grammar, generate, parse


LIST_VIZ_GRAMMAR = make_grammar(BASE_RULES + [
    BiTemplate("GetColumn",
               "[{col_expr:AnyPython} for item in {source_expr:VarOrExpr}]",
               {'action': 'get'}),

    Alt("Action", [
        "GetColumn",
    ], {}),
])


def col_expr_to_column(col_expr: str) -> str:
    """Convert a column expression using 'item' to a column name using '^'.

    item         → ^
    item['name'] → ^['name']
    item.x       → ^.x
    item[0]      → ^[0]
    """
    col_expr = col_expr.strip()
    if col_expr == 'item':
        return '^'
    if col_expr.startswith('item') and len(col_expr) > 4:
        next_ch = col_expr[4]
        if not next_ch.isalnum() and next_ch != '_':
            return '^' + col_expr[4:]
    return col_expr


def generate_action(action: str, ctx: dict) -> str | None:
    """Generate code for a list action. Returns the generated string or None."""
    gen_ctx = {k: v for k, v in ctx.items() if v is not None}
    gen_ctx['action'] = action
    result = generate(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Action'], gen_ctx)
    if result is None:
        return None
    return result[0]


def parse_generated_code(code_line: str) -> dict | None:
    """Parse a line of list-visualizer-generated code back to context.

    Returns a dict including the 'action' key, or None.
    """
    return parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Action'], code_line)


def parse_generated_code_or_assignment(code_line: str) -> tuple[dict | None, str]:
    """Parse code as an action expression or ``var = expr`` assignment.

    Returns ``(ctx, prefix)`` where *prefix* is ``'var = '`` when the code
    was an assignment, or ``''`` for a bare expression.  Returns
    ``(None, '')`` when parsing fails.
    """
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Action'], code_line)
    if ctx is not None:
        return (ctx, '')
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Assignment'], code_line)
    if ctx is not None and 'assign_var_name' in ctx:
        return (ctx, f"{ctx['assign_var_name']} = ")
    return (None, '')
