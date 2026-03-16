"""Bidirectional grammar for list visualizer generated expressions.

Parses and generates:
- List comprehensions: [item.x for item in my_list]
- Cell access: my_list[0], my_list[0].x
"""

import re
from bidirectional_dsl import BiTemplate, Alt, BASE_RULES, make_grammar, generate, parse


LIST_VIZ_GRAMMAR = make_grammar(BASE_RULES + [
    BiTemplate("IndexExpr", re.compile(r'[0-9]+'), {}),
    # Attribute chain: .x, .x.y, .x.y.z (no brackets for now)
    BiTemplate("AttrChain", re.compile(r'(\.[A-Za-z_][A-Za-z0-9_]*)+'), {}),

    # List comprehension: [item_expr for item in source_expr]
    BiTemplate("ListComp",
               "[{item_expr:Something} for item in {source_expr:VarOrExpr}]",
               {'expr_type': 'column'}),

    # Cell access: source_expr[index] or source_expr[index].attr
    Alt("CellExpr", [
        BiTemplate("CellIndexAttr",
                   "{source_expr:VarOrExpr}[{index_expr:IndexExpr}]{attr_chain:AttrChain}",
                   {'expr_type': 'cell'}),
        BiTemplate("CellIndex",
                   "{source_expr:VarOrExpr}[{index_expr:IndexExpr}]",
                   {'expr_type': 'cell'}),
    ], {}),

    Alt("ListVizExpr", ["ListComp", "CellExpr"], {}),

    BiTemplate("ListVizAssignment",
               "{assign_var_name:Var} = {list_expr:ListVizExpr}",
               {}),
])


def _item_expr_to_column(item_expr: str) -> str:
    """Convert parsed item_expr back to column name (with ^ prefix)."""
    if not item_expr.startswith("item"):
        return "^"
    if item_expr == "item":
        return "^"
    if item_expr.startswith("item."):
        return "^" + item_expr[5:]
    return "^" + item_expr[4:]


def parse_generated_code(code: str) -> dict | None:
    """Parse list visualizer-generated code back to context dict.

    Returns dict with:
      - expr_type: 'column' | 'cell'
      - source_expr: the list variable/expression
      - For column: item_expr (e.g. 'item.x')
      - For cell: index_expr (e.g. '0'), attr_chain (e.g. '.x' or None)
      - assign_var_name: if assignment, the variable name
    """
    def _finish_column(ctx):
        ctx['linked_column'] = _item_expr_to_column(ctx.get('item_expr', 'item'))
        return ctx

    def _finish_cell(ctx):
        attr = ctx.get('attr_chain', '')
        if attr:
            ctx['linked_column'] = "^" + attr[1:]
        else:
            ctx['linked_column'] = "^"
        return ctx

    # Try assignment first: x = [item.x for item in my_list]
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['ListVizAssignment'], code)
    if ctx is not None:
        if ctx.get('expr_type') == 'column':
            return _finish_column(ctx)
        if ctx.get('expr_type') == 'cell':
            return _finish_cell(ctx)
        return ctx

    # Try list comprehension
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['ListComp'], code)
    if ctx is not None:
        return _finish_column(ctx)

    # Try cell access
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['CellExpr'], code)
    if ctx is not None:
        return _finish_cell(ctx)

    return None


def parse_generated_code_or_assignment(code: str) -> tuple[dict | None, str]:
    """Parse code as an expression or ``var = expr`` assignment.

    Returns ``(ctx, prefix)`` where *prefix* is ``'var = '`` when the code
    was an assignment, or ``''`` for a bare expression.  Returns
    ``(None, '')`` when parsing fails entirely.
    """
    ctx = parse_generated_code(code)
    if ctx is not None:
        if ctx.get('assign_var_name'):
            return (ctx, f"{ctx['assign_var_name']} = ")
        return (ctx, '')
    return (None, '')


def _column_to_item_expr(column: str) -> str:
    """Convert column (^, ^x, ^x.y, ^[0]) to item_expr for list comp."""
    if not column or column == "^":
        return "item"
    if column.startswith("^"):
        rest = column[1:]
        if rest.startswith("["):
            return "item" + rest
        return "item." + rest
    return "item"


def generate_column_expr(source_expr: str, column: str) -> str:
    """Generate list comprehension for a column.

    column is the caret-prefixed name, e.g. '^', '^x', '^x.y'.
    """
    item_expr = _column_to_item_expr(column)
    ctx = {
        'source_expr': source_expr,
        'item_expr': item_expr,
        'expr_type': 'column',
    }
    result = generate(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['ListComp'], ctx)
    return result[0] if result else ""


def generate_cell_expr(source_expr: str, index: int, column: str) -> str:
    """Generate cell access expression.

    column is the caret-prefixed name, e.g. '^', '^x'.
    """
    ctx = {
        'source_expr': source_expr,
        'index_expr': str(index),
        'expr_type': 'cell',
    }
    if column and column != "^":
        ctx['attr_chain'] = "." + column[1:]
    result = generate(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['CellExpr'], ctx)
    return result[0] if result else ""
