import re
import ast
from bidirectional_dsl import BiTemplate, Alt, BASE_RULES, make_grammar, generate, parse


LIST_VIZ_GRAMMAR = make_grammar(BASE_RULES + [
    BiTemplate("SliceComponent", re.compile(r"[^:\]]*"), {}),
    BiTemplate("IndexExpr", re.compile(r"[^\]]+"), {}),
    BiTemplate("IndicesExpr", ast.parse, {}),

    # --- Filter ---

    Alt("FilterAction", [
        BiTemplate("FilterPredicateFirst",
                   "next((item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True}),
        BiTemplate("FilterPredicateAll",
                   "[item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}]",
                   {'is_predicate': True, 'is_first': False}),
        BiTemplate("FilterSlice",
                   "{source_expr:VarOrExpr}[{slice_start:SliceComponent}:{slice_stop:SliceComponent}]",
                   {'is_slice': True}),
        BiTemplate("FilterIndex",
                   "{source_expr:VarOrExpr}[{index_expr:IndexExpr}]",
                   {'is_index': True}),
        BiTemplate("FilterMultiIndex",
                   "[{source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}]",
                   {'is_multi_index': True}),
    ], {}),

    # --- Delete ---

    Alt("DeleteSliceLeft", [
        BiTemplate("DeleteSliceLeftPresent",
                   "{source_expr:VarOrExpr}[:{slice_start:SliceComponent}]",
                   {'has_slice_start': True}),
        BiTemplate("DeleteSliceLeftEmpty", "[]", {'has_slice_start': False}),
    ], {}),

    Alt("DeleteSliceRight", [
        BiTemplate("DeleteSliceRightPresent",
                   "{source_expr:VarOrExpr}[{slice_stop:SliceComponent}:]",
                   {'has_slice_stop': True}),
        BiTemplate("DeleteSliceRightEmpty", "[]", {'has_slice_stop': False}),
    ], {}),

    Alt("DeleteAction", [
        BiTemplate("DeletePredicateFirst",
                   "next(({source_expr:VarOrExpr}[:i] + {source_expr:VarOrExpr}[i+1:] for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}), {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'is_first': True}),
        BiTemplate("DeletePredicateAll",
                   "[item for item in {source_expr:VarOrExpr} if not ({predicate_expr:AnyPython})]",
                   {'is_predicate': True, 'is_first': False}),
        BiTemplate("DeleteIndex",
                   "{source_expr:VarOrExpr}[:{index_expr:IndexExpr}] + {source_expr:VarOrExpr}[{index_expr:IndexExpr}+1:]",
                   {'is_index': True}),
        BiTemplate("DeleteSlice",
                   "{:DeleteSliceLeft} + {:DeleteSliceRight}",
                   {'is_slice': True}),
        BiTemplate("DeleteMultiIndex",
                   "[item for i, item in enumerate({source_expr:VarOrExpr}) if i not in set({indices_expr:AnyPython})]",
                   {'is_multi_index': True}),
    ], {}),

    # --- Find Indices ---

    Alt("FindIndicesSliceStop", [
        BiTemplate("FindIndicesSliceStopPresent",
                   "{slice_stop:SliceComponent}",
                   {'has_slice_stop': True}),
        BiTemplate("FindIndicesSliceStopLen",
                   "len({source_expr:VarOrExpr})",
                   {'has_slice_stop': False}),
    ], {}),

    Alt("FindIndicesSliceStart", [
        BiTemplate("FindIndicesSliceStartPresent",
                   "{slice_start:SliceComponent}",
                   {'has_slice_start': True}),
        BiTemplate("FindIndicesSliceStartZero",
                   "0",
                   {'has_slice_start': False}),
    ], {}),

    Alt("FindIndicesAction", [
        BiTemplate("FindIndicesPredicateFirst",
                   "next((i for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True}),
        BiTemplate("FindIndicesPredicateAll",
                   "[i for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}]",
                   {'is_predicate': True, 'is_first': False}),
        BiTemplate("FindIndicesSlice",
                   "list(range({:FindIndicesSliceStart}, {:FindIndicesSliceStop}))",
                   {'is_slice': True}),
    ], {}),

    # --- Count ---

    Alt("CountAction", [
        BiTemplate("CountPredicate",
                   "sum(1 for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython})",
                   {'is_predicate': True}),
        BiTemplate("CountMultiIndex",
                   "len({indices_expr:AnyPython})",
                   {'is_multi_index': True}),
    ], {}),

    # --- Any ---

    Alt("AnyAction", [
        BiTemplate("AnyPredicate",
                   "any({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr})",
                   {'is_predicate': True}),
        BiTemplate("AnyMultiIndex",
                   "len({indices_expr:AnyPython}) > 0",
                   {'is_multi_index': True}),
    ], {}),

    # --- All ---

    Alt("AllAction", [
        BiTemplate("AllPredicate",
                   "all({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr})",
                   {'is_predicate': True}),
        BiTemplate("AllMultiIndex",
                   "len({indices_expr:AnyPython}) == len({source_expr:VarOrExpr})",
                   {'is_multi_index': True}),
    ], {}),

    # --- If Any / If All ---

    BiTemplate("IfAnyAction",
               "if any({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr}):\n    pass",
               {'is_predicate': True}),

    BiTemplate("IfAllAction",
               "if all({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr}):\n    pass",
               {'is_predicate': True}),

    # --- Loop ---

    Alt("LoopNoIdxAction", [
        BiTemplate("LoopNoIdxPredicate",
                   "for item in (item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}):\n    pass",
                   {'is_predicate': True}),
        BiTemplate("LoopNoIdxMultiIndex",
                   "for item in [{source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}]:\n    pass",
                   {'is_multi_index': True}),
    ], {}),

    Alt("LoopOrigIdxAction", [
        BiTemplate("LoopOrigIdxPredicate",
                   "for i, item in enumerate({source_expr:VarOrExpr}):\n    if {predicate_expr:AnyPython}:\n        pass",
                   {'is_predicate': True}),
        BiTemplate("LoopOrigIdxMultiIndex",
                   "for i in {indices_expr:AnyPython}:\n    pass",
                   {'is_multi_index': True}),
    ], {}),

    Alt("LoopNewIdxAction", [
        BiTemplate("LoopNewIdxPredicate",
                   "for i, item in enumerate(item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}):\n    pass",
                   {'is_predicate': True}),
        BiTemplate("LoopNewIdxMultiIndex",
                   "for i, item in enumerate({source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}):\n    pass",
                   {'is_multi_index': True}),
    ], {}),

    # --- Top-level Action: gates on 'action' key ---
    # Order matters for parse: more specific/longer patterns first

    Alt("Action", [
        Alt("ActionDelete", ["DeleteAction"], {'action': 'delete'}),
        Alt("ActionLoopOrigIdx", ["LoopOrigIdxAction"], {'action': 'loop_orig_idx'}),
        Alt("ActionLoopNewIdx", ["LoopNewIdxAction"], {'action': 'loop_new_idx'}),
        Alt("ActionLoopNoIdx", ["LoopNoIdxAction"], {'action': 'loop_no_idx'}),
        Alt("ActionIfAny", ["IfAnyAction"], {'action': 'if_any'}),
        Alt("ActionIfAll", ["IfAllAction"], {'action': 'if_all'}),
        Alt("ActionAll", ["AllAction"], {'action': 'all'}),
        Alt("ActionAny", ["AnyAction"], {'action': 'any'}),
        Alt("ActionCount", ["CountAction"], {'action': 'count'}),
        Alt("ActionFilter", ["FilterAction"], {'action': 'filter'}),
        Alt("ActionFindIndices", ["FindIndicesAction"], {'action': 'find_indices'}),
    ], {}),
])


# ---------------------------------------------------------------------------
# Suggest-name logic (kept here alongside grammar for co-location)
# ---------------------------------------------------------------------------

_SUGGEST_SUFFIXES = {
    'any': 'any', 'all': 'all', 'count': 'count',
    'filter': 'filtered', 'find_indices': 'indices',
}
_STATEMENT_ACTIONS = frozenset({'loop_no_idx', 'loop_orig_idx', 'loop_new_idx', 'if_any', 'if_all'})


def _suggest_name_for_action(action: str, ctx: dict) -> str | None:
    if action in _STATEMENT_ACTIONS:
        return None
    base = ctx.get('suggest_base') or 'result'
    has_var = bool(ctx.get('var_name'))
    if action == 'filter':
        if ctx.get('is_first'):
            suffix = 'match'
        else:
            suffix = 'filtered'
        return f"{base}_{suffix}" if has_var else f"result_{suffix}"
    if action == 'delete':
        return base if has_var else 'result'
    suffix = _SUGGEST_SUFFIXES.get(action)
    if suffix:
        return f"{base}_{suffix}" if has_var else f"result_{suffix}"
    return base if has_var else 'result'


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_action(action: str, ctx: dict) -> tuple[str | None, str] | None:
    gen_ctx = {k: v for k, v in ctx.items() if v is not None}
    gen_ctx['action'] = action
    if ctx.get('is_slice'):
        gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
        gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
    result = generate(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Action'], gen_ctx)
    if result is not None:
        return (_suggest_name_for_action(action, gen_ctx), result[0])

    # Bare-expression fallbacks not in the grammar (too greedy for parsing)
    if action == 'find_indices':
        if ctx.get('is_index'):
            return (_suggest_name_for_action(action, ctx), ctx['index_expr'])
        if ctx.get('is_multi_index'):
            return (_suggest_name_for_action(action, ctx), ctx['indices_expr'])

    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _source_text(code_line: str, node: ast.AST | None) -> str:
    if node is None:
        return ''
    return ast.get_source_segment(code_line, node) or ast.unparse(node)


def _parse_generated_join(code_line: str) -> dict | None:
    try:
        expr = ast.parse(code_line, mode='eval').body
    except SyntaxError:
        return None

    if not isinstance(expr, ast.Call) or expr.keywords or len(expr.args) != 1:
        return None
    if not isinstance(expr.func, ast.Attribute) or expr.func.attr != 'join':
        return None

    try:
        sep_val = ast.literal_eval(expr.func.value)
    except Exception:
        return None
    if not isinstance(sep_val, str):
        return None

    gen = expr.args[0]
    if not isinstance(gen, ast.GeneratorExp) or len(gen.generators) != 1:
        return None
    comp = gen.generators[0]
    if comp.is_async:
        return None
    if not isinstance(gen.elt, ast.Call) or gen.elt.keywords:
        return None
    if not isinstance(gen.elt.func, ast.Name) or gen.elt.func.id != 'str' or len(gen.elt.args) != 1:
        return None

    item_expr = gen.elt.args[0]
    join_separator = _source_text(code_line, expr.func.value)

    if (
        isinstance(comp.target, ast.Name) and comp.target.id == 'item'
        and isinstance(item_expr, ast.Name) and item_expr.id == 'item'
    ):
        if isinstance(comp.iter, ast.Subscript) and isinstance(comp.iter.slice, ast.Slice) and comp.iter.slice.step is None and not comp.ifs:
            return {
                'action': 'join',
                'source_expr': _source_text(code_line, comp.iter.value),
                'join_separator': join_separator,
                'is_slice': True,
                'slice_start': _source_text(code_line, comp.iter.slice.lower),
                'slice_stop': _source_text(code_line, comp.iter.slice.upper),
                'is_index': False,
                'is_predicate': False,
                'is_multi_index': False,
                'is_first': False,
            }
        if len(comp.ifs) == 1:
            return {
                'action': 'join',
                'source_expr': _source_text(code_line, comp.iter),
                'join_separator': join_separator,
                'is_predicate': True,
                'predicate_expr': _source_text(code_line, comp.ifs[0]),
                'is_index': False,
                'is_slice': False,
                'is_multi_index': False,
                'is_first': False,
            }
        if not comp.ifs:
            return {
                'action': 'join',
                'source_expr': _source_text(code_line, comp.iter),
                'join_separator': join_separator,
                'is_whole_list': True,
                'is_predicate': False,
                'is_index': False,
                'is_slice': False,
                'is_multi_index': False,
                'is_first': False,
            }
        return None

    if (
        isinstance(comp.target, ast.Name) and comp.target.id == 'i'
        and not comp.ifs
        and isinstance(item_expr, ast.Subscript)
        and isinstance(item_expr.slice, ast.Name) and item_expr.slice.id == 'i'
    ):
        return {
            'action': 'join',
            'source_expr': _source_text(code_line, item_expr.value),
            'join_separator': join_separator,
            'is_multi_index': True,
            'indices_expr': _source_text(code_line, comp.iter),
            'is_index': False,
            'is_slice': False,
            'is_predicate': False,
            'is_first': False,
        }

    return None


def parse_generated_code(code_line: str) -> dict | None:
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Action'], code_line)
    if ctx is not None:
        return ctx
    return _parse_generated_join(code_line)


def parse_generated_code_or_assignment(code_line: str) -> tuple[dict | None, str]:
    ctx = parse(LIST_VIZ_GRAMMAR, LIST_VIZ_GRAMMAR['Assignment'], code_line)
    if ctx is not None and 'assign_var_name' in ctx:
        return (ctx, f"{ctx['assign_var_name']} = ")
    try:
        module = ast.parse(code_line, mode='exec')
        if (
            len(module.body) == 1
            and isinstance(module.body[0], ast.Assign)
            and len(module.body[0].targets) == 1
            and isinstance(module.body[0].targets[0], ast.Name)
        ):
            rhs_text = _source_text(code_line, module.body[0].value)
            rhs_ctx = parse_generated_code(rhs_text)
            if rhs_ctx is not None:
                return (rhs_ctx, f"{module.body[0].targets[0].id} = ")
    except SyntaxError:
        pass
    ctx = parse_generated_code(code_line)
    if ctx is not None:
        return (ctx, '')
    return (None, '')
