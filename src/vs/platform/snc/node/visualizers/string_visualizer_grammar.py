import re
from bidirectional_dsl import BiTemplate, Alt, BASE_RULES, make_grammar, generate, parse
from visualizer_utils import without_pass_body, imports_for_code


STRING_VIZ_GRAMMAR = make_grammar(BASE_RULES + [
    BiTemplate("RawContent", re.compile(r"[^']*"), {}),
    BiTemplate("SliceComponent", re.compile(r"[^:\]]*"), {}),
    BiTemplate("IndexExpr", re.compile(r"[^\]]+"), {}),

    Alt("RegexFlags", [
        BiTemplate("RegexFlagsMI", "re.M|re.I", {'is_ci': True}),
        BiTemplate("RegexFlagsM", "re.M", {'is_ci': False}),
    ], {}),

    Alt("ExprKwFlags", [
        BiTemplate("ExprFlagsI", ", flags=re.I", {'is_ci': True}),
        BiTemplate("ExprFlagsNone", "", {'is_ci': False}),
    ], {}),

    Alt("PerhapsCount", [
        BiTemplate("CountOne", ", count=1", {'is_first': True}),
        BiTemplate("CountNone", "", {'is_first': False}),
    ], {}),

    Alt("PerhapsMaxsplit", [
        BiTemplate("MaxsplitOne", ", maxsplit=1", {'is_first': True}),
        BiTemplate("MaxsplitNone", "", {'is_first': False}),
    ], {}),

    Alt("FinditerExpr", [
        BiTemplate("RegexFinditer",
                   "re.finditer(r'{regex_pattern:RawContent}', {source_expr:VarOrExpr}, flags={:RegexFlags})",
                   {'is_expr': False}),
        BiTemplate("ExprFinditer",
                   "re.finditer(re.escape({expr:Something}), {source_expr:VarOrExpr}{:ExprKwFlags})",
                   {'is_expr': True}),
    ], {}),

    Alt("SearchExpr", [
        BiTemplate("RegexSearch",
                   "re.search(r'{regex_pattern:RawContent}', {source_expr:VarOrExpr}, flags={:RegexFlags})",
                   {'is_expr': False}),
        BiTemplate("ExprSearch",
                   "re.search(re.escape({expr:Something}), {source_expr:VarOrExpr}{:ExprKwFlags})",
                   {'is_expr': True}),
    ], {}),

    Alt("FindallExpr", [
        BiTemplate("RegexFindall",
                   "re.findall(r'{regex_pattern:RawContent}', {source_expr:VarOrExpr}, flags={:RegexFlags})",
                   {'is_expr': False}),
        BiTemplate("ExprFindall",
                   "re.findall(re.escape({expr:Something}), {source_expr:VarOrExpr}{:ExprKwFlags})",
                   {'is_expr': True}),
    ], {}),

    # --- Slice edge sub-rules (conditional '' vs v[:start]) ---

    Alt("SliceLeft", [
        BiTemplate("SliceLeftPresent",
                   "{source_expr:VarOrExpr}[:{slice_start:SliceComponent}]",
                   {'has_slice_start': True}),
        BiTemplate("SliceLeftEmpty", "''", {'has_slice_start': False}),
    ], {}),

    Alt("SliceRight", [
        BiTemplate("SliceRightPresent",
                   "{source_expr:VarOrExpr}[{slice_stop:SliceComponent}:]",
                   {'has_slice_stop': True}),
        BiTemplate("SliceRightEmpty", "''", {'has_slice_stop': False}),
    ], {}),

    # --- Per-action rules ---

    # Slice before Index so x[5:10] parses as slice, not index with expr "5:10"
    Alt("GetAction", [
        BiTemplate("GetSlice",
                   "{source_expr:VarOrExpr}[{slice_start:SliceComponent}:{slice_stop:SliceComponent}]",
                   {'is_slice': True}),
        BiTemplate("GetIndex",
                   "{source_expr:VarOrExpr}[{index_expr:IndexExpr}]",
                   {'is_index': True}),
        BiTemplate("GetFirst",
                   "{:SearchExpr}",
                   {'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("GetList",
                   "list({:FinditerExpr})",
                   {'is_first': False, 'is_index': False, 'is_slice': False}),
    ], {'has_replace': False}),

    Alt("TransformAction", [
        BiTemplate("TransformSlice",
                   "(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[{slice_start:SliceComponent}:{slice_stop:SliceComponent}])",
                   {'is_slice': True}),
        BiTemplate("TransformIndex",
                   "(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[{index_expr:IndexExpr}])",
                   {'is_index': True}),
        BiTemplate("TransformFirst",
                   "next(({replace_expr:AnyPython} for mtch in {:FinditerExpr}), None)",
                   {'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("TransformList",
                   "[{replace_expr:AnyPython} for mtch in {:FinditerExpr}]",
                   {'is_first': False, 'is_index': False, 'is_slice': False}),
    ], {'has_replace': True}),

    Alt("LoopAction", [
        BiTemplate("LoopReplace",
                   "for i, val in enumerate({replace_expr:AnyPython} for mtch in {:FinditerExpr}):",
                   {'has_replace': True}),
        BiTemplate("LoopNonReplace",
                   "for i, mtch in enumerate({:FinditerExpr}):",
                   {'has_replace': False}),
    ], {}),

    Alt("MatchStringsAction", [
        BiTemplate("MatchStringsFirst",
                   "next(iter({:FindallExpr}), None)",
                   {'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("MatchStringsList",
                   "{:FindallExpr}",
                   {'is_first': False, 'is_index': False, 'is_slice': False}),
    ], {'has_replace': False}),

    BiTemplate("LoopMatchStringsAction",
               "for i, s in enumerate({:FindallExpr}):",
               {}),

    Alt("AnyAction", [
        BiTemplate("AnyReplace",
                   "any({replace_expr:AnyPython} for mtch in {:FinditerExpr})",
                   {'has_replace': True}),
        BiTemplate("AnyNonReplace",
                   "bool({:SearchExpr})",
                   {'has_replace': False}),
    ], {}),

    BiTemplate("AllAction",
               "all({replace_expr:AnyPython} for mtch in {:FinditerExpr})",
               {}),

    Alt("IfAnyAction", [
        BiTemplate("IfAnyReplace",
                   "if any({replace_expr:AnyPython} for mtch in {:FinditerExpr}):",
                   {'has_replace': True}),
        BiTemplate("IfAnyNonReplace",
                   "if {:SearchExpr}:",
                   {'has_replace': False}),
    ], {}),

    BiTemplate("IfAllAction",
               "if all({replace_expr:AnyPython} for mtch in {:FinditerExpr}):",
               {}),

    Alt("CountAction", [
        BiTemplate("CountReplace",
                   "sum(1 for mtch in {:FinditerExpr} if {replace_expr:AnyPython})",
                   {'has_replace': True}),
        BiTemplate("CountNonReplace",
                   "sum(1 for _ in {:FinditerExpr})",
                   {'has_replace': False}),
    ], {}),

    Alt("FilterAction", [
        BiTemplate("FilterFirst",
                   "next((mtch for mtch in {:FinditerExpr} if {replace_expr:AnyPython}), None)",
                   {'is_first': True}),
        BiTemplate("FilterList",
                   "[mtch for mtch in {:FinditerExpr} if {replace_expr:AnyPython}]",
                   {'is_first': False}),
    ], {}),

    Alt("FindIndicesAction", [
        BiTemplate("FindIndicesFilterFirst",
                   "next((mtch.start() for mtch in {:FinditerExpr} if {replace_expr:AnyPython}), None)",
                   {'is_first': True, 'has_replace': True}),
        BiTemplate("FindIndicesFilterList",
                   "[mtch.start() for mtch in {:FinditerExpr} if {replace_expr:AnyPython}]",
                   {'is_first': False, 'has_replace': True}),
        BiTemplate("FindIndicesFirst",
                   "next((mtch.start() for mtch in {:FinditerExpr}), None)",
                   {'is_first': True, 'has_replace': False}),
        BiTemplate("FindIndicesList",
                   "[mtch.start() for mtch in {:FinditerExpr}]",
                   {'is_first': False, 'has_replace': False}),
    ], {'is_index': False, 'is_slice': False}),

    # --- Multi-index / multi-pair / broadcast-slice sub-rules ---

    Alt("MultiIter", [
        BiTemplate("MultiIterIndex",
                   "{source_expr:VarOrExpr}[i] for i in {indices_expr:Something}",
                   {'is_multi_index': True}),
        BiTemplate("MultiIterBroadcastBoth",
                   "{source_expr:VarOrExpr}[i:j] for i, j in zip({start_list_expr:Something}, {stop_list_expr:Something})",
                   {'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': True}),
        BiTemplate("MultiIterPairSlice",
                   "{source_expr:VarOrExpr}[i:j] for i, j in {pairs_expr:Something}",
                   {'is_multi_pair_slice': True}),
        BiTemplate("MultiIterBroadcastLeft",
                   "{source_expr:VarOrExpr}[i:{slice_stop:SliceComponent}] for i in {start_list_expr:Something}",
                   {'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': False}),
        BiTemplate("MultiIterBroadcastRight",
                   "{source_expr:VarOrExpr}[{slice_start:SliceComponent}:i] for i in {stop_list_expr:Something}",
                   {'is_broadcast_slice': True, 'has_start_list': False, 'has_stop_list': True}),
    ], {'is_index': False, 'is_slice': False}),

    BiTemplate("MultiGetAction",
               "[{:MultiIter}]",
               {'has_replace': False}),

    Alt("MultiTransformAction", [
        BiTemplate("MultiTransformIndex",
                   "[(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[i]) for i in {indices_expr:Something}]",
                   {'is_multi_index': True}),
        BiTemplate("MultiTransformBroadcastBoth",
                   "[(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[i:j]) for i, j in zip({start_list_expr:Something}, {stop_list_expr:Something})]",
                   {'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': True}),
        BiTemplate("MultiTransformPairSlice",
                   "[(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[i:j]) for i, j in {pairs_expr:Something}]",
                   {'is_multi_pair_slice': True}),
        BiTemplate("MultiTransformBroadcastLeft",
                   "[(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[i:{slice_stop:SliceComponent}]) for i in {start_list_expr:Something}]",
                   {'is_broadcast_slice': True, 'has_start_list': True, 'has_stop_list': False}),
        BiTemplate("MultiTransformBroadcastRight",
                   "[(lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[{slice_start:SliceComponent}:i]) for i in {stop_list_expr:Something}]",
                   {'is_broadcast_slice': True, 'has_start_list': False, 'has_stop_list': True}),
    ], {'has_replace': True}),

    Alt("MultiCountAction", [
        BiTemplate("MultiCountNoReplace",
                   "len({indices_expr:Something})",
                   {'is_multi_index': True, 'has_replace': False}),
        BiTemplate("MultiCountNoReplacePair",
                   "len({pairs_expr:Something})",
                   {'is_multi_pair_slice': True, 'has_replace': False}),
        BiTemplate("MultiCountNoReplaceBroadcast",
                   "len({start_list_expr:Something})",
                   {'is_broadcast_slice': True, 'has_start_list': True, 'has_replace': False}),
        BiTemplate("MultiCountNoReplaceBroadcastRight",
                   "len({stop_list_expr:Something})",
                   {'is_broadcast_slice': True, 'has_start_list': False, 'has_stop_list': True, 'has_replace': False}),
        BiTemplate("MultiCountReplace",
                   "sum(1 for mtch in [{:MultiIter}] if {replace_expr:AnyPython})",
                   {'has_replace': True}),
    ], {}),

    Alt("MultiLoopAction", [
        BiTemplate("MultiLoopReplace",
                   "for i, val in enumerate((lambda mtch: {replace_expr:AnyPython})({:MultiIter})):",
                   {'has_replace': True}),
        BiTemplate("MultiLoopNonReplace",
                   "for i, mtch in enumerate([{:MultiIter}]):",
                   {'has_replace': False}),
    ], {}),

    BiTemplate("MultiFilterAction",
               "[mtch for mtch in [{:MultiIter}] if {replace_expr:AnyPython}]",
               {}),

    Alt("MultiFindIndicesAction", [
        BiTemplate("MultiFindIndicesIndex",
                   "{indices_expr:Something}",
                   {'is_multi_index': True}),
        BiTemplate("MultiFindIndicesPair",
                   "[i for i, j in {pairs_expr:Something}]",
                   {'is_multi_pair_slice': True}),
        BiTemplate("MultiFindIndicesBroadcastStart",
                   "{start_list_expr:Something}",
                   {'is_broadcast_slice': True, 'has_start_list': True}),
        BiTemplate("MultiFindIndicesBroadcastRight",
                   "[0] * len({stop_list_expr:Something})",
                   {'is_broadcast_slice': True, 'has_start_list': False, 'has_stop_list': True}),
    ], {'is_index': False, 'is_slice': False}),

    Alt("SplitAction", [
        BiTemplate("SplitRegex",
                   "re.split(r'{regex_pattern:RawContent}', {source_expr:VarOrExpr}{:PerhapsMaxsplit}, flags={:RegexFlags})",
                   {'is_expr': False, 'is_index': False, 'is_slice': False}),
        BiTemplate("SplitExprCI",
                   "re.split(re.escape({expr:Something}), {source_expr:VarOrExpr}{:PerhapsMaxsplit}{:ExprKwFlags})",
                   {'is_expr': True, 'is_ci': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("SplitExprFirst",
                   "{source_expr:VarOrExpr}.split({expr:Something}, 1)",
                   {'is_expr': True, 'is_ci': False, 'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("SplitExprAll",
                   "{source_expr:VarOrExpr}.split({expr:Something})",
                   {'is_expr': True, 'is_ci': False, 'is_first': False, 'is_index': False, 'is_slice': False}),
    ], {}),

    Alt("ReplaceAction", [
        BiTemplate("ReplaceIndex",
                   "{source_expr:VarOrExpr}[:{index_expr:IndexExpr}] + str((lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[{index_expr:IndexExpr}])) + {source_expr:VarOrExpr}[{index_expr:IndexExpr} + 1:]",
                   {'is_index': True}),
        BiTemplate("ReplaceSlice",
                   "{:SliceLeft} + str((lambda mtch: {replace_expr:AnyPython})({source_expr:VarOrExpr}[{slice_start:SliceComponent}:{slice_stop:SliceComponent}])) + {:SliceRight}",
                   {'is_slice': True}),
        BiTemplate("ReplaceRegex",
                   "re.sub(r'{regex_pattern:RawContent}', lambda mtch: {replace_expr:AnyPython}, {source_expr:VarOrExpr}{:PerhapsCount}, flags={:RegexFlags})",
                   {'is_expr': False, 'is_index': False, 'is_slice': False}),
        BiTemplate("ReplaceExpr",
                   "re.sub(re.escape({expr:Something}), lambda mtch: {replace_expr:AnyPython}, {source_expr:VarOrExpr}{:PerhapsCount}{:ExprKwFlags})",
                   {'is_expr': True, 'is_index': False, 'is_slice': False}),
    ], {}),

    Alt("DeleteAction", [
        BiTemplate("DeleteIndex",
                   "{source_expr:VarOrExpr}[:{index_expr:IndexExpr}] + {source_expr:VarOrExpr}[{index_expr:IndexExpr} + 1:]",
                   {'is_index': True}),
        BiTemplate("DeleteSlice",
                   "{:SliceLeft} + {:SliceRight}",
                   {'is_slice': True}),
        BiTemplate("DeletePredicateFirst",
                   "next(({source_expr:VarOrExpr}[:mtch.start()] + {source_expr:VarOrExpr}[mtch.end():] for mtch in {:FinditerExpr} if {replace_expr:AnyPython}), {source_expr:VarOrExpr})",
                   {'is_first': True, 'is_index': False, 'is_slice': False, 'has_replace': True}),
        BiTemplate("DeletePredicateRegexAll",
                   "re.sub(r'{regex_pattern:RawContent}', lambda mtch: '' if ({replace_expr:AnyPython}) else mtch[0], {source_expr:VarOrExpr}, flags={:RegexFlags})",
                   {'is_expr': False, 'is_first': False, 'is_index': False, 'is_slice': False, 'has_replace': True}),
        BiTemplate("DeletePredicateExprAll",
                   "re.sub(re.escape({expr:Something}), lambda mtch: '' if ({replace_expr:AnyPython}) else mtch[0], {source_expr:VarOrExpr}{:ExprKwFlags})",
                   {'is_expr': True, 'is_first': False, 'is_index': False, 'is_slice': False, 'has_replace': True}),
        BiTemplate("DeleteExprFirst",
                   "{source_expr:VarOrExpr}.replace({expr:Something}, '', 1)",
                   {'is_expr': True, 'is_ci': False, 'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("DeleteExprAll",
                   "{source_expr:VarOrExpr}.replace({expr:Something}, '')",
                   {'is_expr': True, 'is_ci': False, 'is_first': False, 'is_index': False, 'is_slice': False}),
        BiTemplate("DeleteExprCI",
                   "re.sub(re.escape({expr:Something}), '', {source_expr:VarOrExpr}{:PerhapsCount}{:ExprKwFlags})",
                   {'is_expr': True, 'is_ci': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("DeleteRegexFirst",
                   "re.sub(r'{regex_pattern:RawContent}', '', {source_expr:VarOrExpr}, count=1, flags={:RegexFlags})",
                   {'is_expr': False, 'is_first': True, 'is_index': False, 'is_slice': False}),
        BiTemplate("DeleteRegexAll",
                   "re.sub(r'{regex_pattern:RawContent}', '', {source_expr:VarOrExpr}, flags={:RegexFlags})",
                   {'is_expr': False, 'is_first': False, 'is_index': False, 'is_slice': False}),
    ], {}),

    # --- Top-level Action alt: gates on 'action' key ---

    # Order matters for parse: more specific patterns first, find_or_map last
    # (its GetSlice/TransformList are very general and can ambiguously match others)
    Alt("Action", [
        Alt("ActionReplace", ["ReplaceAction"], {'action': 'replace'}),
        Alt("ActionDelete", ["DeleteAction"], {'action': 'delete'}),
        Alt("ActionMultiLoop", ["MultiLoopAction"], {'action': 'loop'}),
        Alt("ActionLoop", ["LoopAction"], {'action': 'loop'}),
        Alt("ActionLoopMatchStrings", ["LoopMatchStringsAction"], {'action': 'loop_match_strings'}),
        Alt("ActionIfAny", ["IfAnyAction"], {'action': 'if_any'}),
        Alt("ActionIfAll", ["IfAllAction"], {'action': 'if_all'}),
        Alt("ActionMultiFilter", ["MultiFilterAction"], {'action': 'filter'}),
        Alt("ActionFilter", ["FilterAction"], {'action': 'filter'}),
        Alt("ActionMultiCount", ["MultiCountAction"], {'action': 'count'}),
        Alt("ActionCount", ["CountAction"], {'action': 'count'}),
        Alt("ActionAny", ["AnyAction"], {'action': 'any'}),
        Alt("ActionAll", ["AllAction"], {'action': 'all'}),
        Alt("ActionSplit", ["SplitAction"], {'action': 'split'}),
        Alt("ActionFindIndices", ["FindIndicesAction"], {'action': 'find_indices'}),
        Alt("ActionMatchStrings", ["MatchStringsAction"], {'action': 'match_strings'}),
        Alt("ActionMultiFindOrMap", ["MultiTransformAction", "MultiGetAction"], {'action': 'find_or_map'}),
        Alt("ActionFindOrMap", ["TransformAction", "GetAction"], {'action': 'find_or_map'}),
        # MultiFindIndices last: its patterns are greedy catch-alls
        Alt("ActionMultiFindIndices", ["MultiFindIndicesAction"], {'action': 'find_indices'}),
    ], {}),
])


# ---------------------------------------------------------------------------
# Suggest-name logic
# ---------------------------------------------------------------------------

_SUGGEST_SUFFIXES = {
    'any': 'any', 'all': 'all', 'count': 'count',
    'filter': 'filtered', 'split': 'parts', 'find_indices': 'indices',
}
_STATEMENT_ACTIONS = frozenset({'loop', 'loop_match_strings', 'if_any', 'if_all'})
_BARE_NAME_ACTIONS = frozenset({'replace', 'delete'})


def _suggest_name(ctx: dict, suffix: str) -> str:
    base = ctx.get('suggest_base') or 'result'
    return f"{base}_{suffix}" if ctx.get('has_var') else f"result_{suffix}"


def _suggest_name_bare(ctx: dict) -> str:
    return (ctx.get('suggest_base') or 'result') if ctx.get('has_var') else 'result'


def _suggest_name_for_get(ctx: dict) -> str:
    if ctx.get('is_index') or ctx.get('is_slice'):
        return _suggest_name_bare(ctx)
    if ctx.get('is_multi_index'):
        return _suggest_name(ctx, 'chars')
    if ctx.get('is_multi_pair_slice') or ctx.get('is_broadcast_slice'):
        return _suggest_name(ctx, 'slices')
    if ctx.get('is_first'):
        return _suggest_name(ctx, 'match')
    return _suggest_name(ctx, 'matches')


def _suggest_name_for_action(action: str, ctx: dict) -> str | None:
    if action in _STATEMENT_ACTIONS:
        return None
    if action == 'find_or_map':
        if ctx.get('has_replace'):
            return _suggest_name(ctx, 'transformed')
        return _suggest_name_for_get(ctx)
    if action == 'match_strings':
        if ctx.get('is_first'):
            return _suggest_name(ctx, 'substring')
        return _suggest_name(ctx, 'strings')
    if action in _BARE_NAME_ACTIONS:
        return _suggest_name_bare(ctx)
    suffix = _SUGGEST_SUFFIXES.get(action)
    if suffix:
        return _suggest_name(ctx, suffix)
    return None


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _has_replace(ctx: dict) -> bool:
    return bool(ctx.get('replace_visible') and ctx.get('replace_expr'))


def generate_action(action: str, ctx: dict) -> tuple[str | None, str] | None:
    """Generate code for any action.

    Returns (suggest_name, code_str) or (None, code_str) for statements,
    or None if the action cannot be generated from this context.
    """
    gen_ctx = {k: v for k, v in ctx.items() if v is not None}
    gen_ctx['action'] = action
    gen_ctx['has_replace'] = _has_replace(ctx)
    if ctx.get('is_slice'):
        gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
        gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
    result = generate(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['Action'], gen_ctx)
    if result is None:
        return None
    return (_suggest_name_for_action(action, gen_ctx), result[0])


def code_imports(code: str) -> tuple:
    """What code generated from this grammar can't run without.

    The templates that search, split and substitute are written with `re.`
    calls (see STRING_VIZ_GRAMMAR), and they are the only reason generated code
    reaches outside the builtins. The rest -- slices, `.upper()`, `.join(...)`
    -- needs nothing. Both answers come out of the one reader every visualizer
    asks, so a handle and the line the same action writes cannot disagree.
    """
    return imports_for_code(code)


def generate_copy_expr_for_if(action: str, ctx: dict) -> str | None:
    """Generate just the boolean expression for copy of if_any/if_all actions."""
    has_repl = _has_replace(ctx)
    gen_ctx = {**ctx, 'has_replace': has_repl}
    if action == 'if_any':
        if has_repl:
            result = generate(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['AnyAction'], gen_ctx)
        else:
            result = generate(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['SearchExpr'], ctx)
        return result[0] if result else None
    elif action == 'if_all':
        if not has_repl:
            return None
        result = generate(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['AllAction'], ctx)
        return result[0] if result else None
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_generated_code(code_line: str) -> dict | None:
    """Parse a line of visualizer-generated code back to DSL context.

    Returns a dict including the 'action' key, or None.
    """
    # Statements are generated as bare headers, but text coming back from the
    # editor may still carry the placeholder body that was inserted with it.
    return parse(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['Action'],
                 without_pass_body(code_line))


def parse_generated_code_or_assignment(code_line: str) -> tuple[dict | None, str]:
    """Parse code as an action expression or ``var = expr`` assignment.

    Returns ``(ctx, prefix)`` where *prefix* is ``'var = '`` when the code
    was an assignment, or ``''`` for a bare expression.  Returns
    ``(None, '')`` when parsing fails entirely.
    """
    # Try the assignment form first: the bare-expression Action grammar has a
    # catch-all (find_indices) that would otherwise greedily match a whole
    # ``var = expr`` line and hide the assignment.
    code_line = without_pass_body(code_line)
    ctx = parse(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['Assignment'], code_line)
    if ctx is not None and 'assign_var_name' in ctx:
        return (ctx, f"{ctx['assign_var_name']} = ")
    ctx = parse(STRING_VIZ_GRAMMAR, STRING_VIZ_GRAMMAR['Action'], code_line)
    if ctx is not None:
        return (ctx, '')
    return (None, '')
