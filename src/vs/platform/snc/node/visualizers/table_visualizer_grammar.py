import re
import ast
from bidirectional_dsl import BiTemplate, Alt, BASE_RULES, make_grammar, generate, parse
from visualizer_utils import without_pass_body


TABLE_VIZ_GRAMMAR = make_grammar(BASE_RULES + [
    BiTemplate("SliceComponent", re.compile(r"[^:\]]*"), {}),
    BiTemplate("IndexExpr", re.compile(r"[^\]]+"), {}),
    BiTemplate("IndicesExpr", ast.parse, {}),

    # --- Filter ---

    # The plain forms come first: `next((item for item in xs if p), None)` also
    # matches the pick template with pick_expr='item', and parsing should read
    # it as an ordinary first-match filter rather than a degenerate pick.
    #
    # Every predicate form has an indexed twin, for a search that named the row's
    # number ($i). The two differ only in what the comprehension binds, and
    # 'names_index' is the difference: it is what the search box's $i became on
    # the way out, and what tells a bound row number from a name the user's
    # program happens to spell `i` on the way back.
    Alt("FilterAction", [
        Alt("FilterPlainAction", [
            # Dict forms come first: they are conditioned on is_dict, so a list
            # ctx never reaches them, while a dict ctx must not fall through to
            # the list templates below and write a comprehension that silently
            # yields keys.
            BiTemplate("FilterPredicateFirstDict",
                       "next(((k, v) for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}), None)",
                       {'is_predicate': True, 'is_first': True,
                        'names_index': False, 'is_dict': True}),
            BiTemplate("FilterPredicateFirstDictIndexed",
                       "next(((k, v) for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}), None)",
                       {'is_predicate': True, 'is_first': True,
                        'names_index': True, 'is_dict': True}),
            BiTemplate("FilterPredicateAllDict",
                       "{k: v for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}}",
                       {'is_predicate': True, 'is_first': False,
                        'names_index': False, 'is_dict': True}),
            BiTemplate("FilterPredicateAllDictIndexed",
                       "{k: v for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}}",
                       {'is_predicate': True, 'is_first': False,
                        'names_index': True, 'is_dict': True}),
            BiTemplate("FilterPredicateFirst",
                       "next((item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}), None)",
                       {'is_predicate': True, 'is_first': True, 'names_index': False}),
            BiTemplate("FilterPredicateFirstIndexed",
                       "next((item for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}), None)",
                       {'is_predicate': True, 'is_first': True, 'names_index': True}),
            BiTemplate("FilterPredicateAll",
                       "[item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}]",
                       {'is_predicate': True, 'is_first': False, 'names_index': False}),
            BiTemplate("FilterPredicateAllIndexed",
                       "[item for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}]",
                       {'is_predicate': True, 'is_first': False, 'names_index': True}),
            BiTemplate("FilterIndexDict",
                       "list({source_expr:VarOrExpr}.items())[{index_expr:IndexExpr}]",
                       {'is_index': True, 'is_dict': True}),
            BiTemplate("FilterSliceDict",
                       "dict(list({source_expr:VarOrExpr}.items())[{slice_start:SliceComponent}:{slice_stop:SliceComponent}])",
                       {'is_slice': True, 'is_dict': True}),
            BiTemplate("FilterSlice",
                       "{source_expr:VarOrExpr}[{slice_start:SliceComponent}:{slice_stop:SliceComponent}]",
                       {'is_slice': True}),
            BiTemplate("FilterIndex",
                       "{source_expr:VarOrExpr}[{index_expr:IndexExpr}]",
                       {'is_index': True}),
            BiTemplate("FilterMultiIndex",
                       "[{source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}]",
                       {'is_multi_index': True}),
        ], {'has_pick': False}),

        # Pick tool: the picked expression replaces the bare `item`. Pick is
        # first-match-only, so there is no all-matches counterpart.
        Alt("FilterPickAction", ["PickFirstMatch"], {'has_pick': True}),
    ], {}),

    # --- Pick wrapper ---
    #
    # One next(...) binds the matched row -- and its index, when the picked
    # regions need one -- for the picked expression to evaluate against. Shared
    # by Filter and by the Loop forms that run over an array pick.

    Alt("PickFirstMatch", [
        BiTemplate("PickFirstMatchPlain",
                   "next(({pick_expr:AnyPython} for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True, 'needs_index': False}),
        BiTemplate("PickFirstMatchIndexed",
                   "next(({pick_expr:AnyPython} for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True, 'needs_index': True}),
    ], {}),

    # --- Delete ---

    Alt("DeleteSliceLeftDict", [
        BiTemplate("DeleteSliceLeftDictPresent",
                   "list({source_expr:VarOrExpr}.items())[:{slice_start:SliceComponent}]",
                   {'has_slice_start': True}),
        BiTemplate("DeleteSliceLeftDictEmpty", "[]", {'has_slice_start': False}),
    ], {}),

    Alt("DeleteSliceRightDict", [
        BiTemplate("DeleteSliceRightDictPresent",
                   "list({source_expr:VarOrExpr}.items())[{slice_stop:SliceComponent}:]",
                   {'has_slice_stop': True}),
        BiTemplate("DeleteSliceRightDictEmpty", "[]", {'has_slice_stop': False}),
    ], {}),

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
        BiTemplate("DeleteIndexDict",
                   "{k: v for j, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if j != {index_expr:IndexExpr}}",
                   {'is_index': True, 'is_dict': True}),
        BiTemplate("DeleteSliceDict",
                   "dict({:DeleteSliceLeftDict} + {:DeleteSliceRightDict})",
                   {'is_slice': True, 'is_dict': True}),
        BiTemplate("DeletePredicateFirstDict",
                   "next(({k2: v2 for k2, v2 in {source_expr:VarOrExpr}.items() if k2 != k} for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}), {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'is_first': True,
                    'names_index': False, 'is_dict': True}),
        BiTemplate("DeletePredicateFirstDictIndexed",
                   "next(({k2: v2 for k2, v2 in {source_expr:VarOrExpr}.items() if k2 != k} for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}), {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'is_first': True,
                    'names_index': True, 'is_dict': True}),
        BiTemplate("DeletePredicateAllDict",
                   "{k: v for k, v in {source_expr:VarOrExpr}.items() if not ({predicate_expr:AnyPython})}",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True, 'is_first': False}),
        BiTemplate("DeletePredicateAllDictIndexed",
                   "{k: v for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if not ({predicate_expr:AnyPython})}",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True, 'is_first': False}),
        # The first-match form counts the rows off whatever the search asked,
        # since it needs the number to cut the list at.
        BiTemplate("DeletePredicateFirst",
                   "next(({source_expr:VarOrExpr}[:i] + {source_expr:VarOrExpr}[i+1:] for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}), {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'is_first': True}),
        BiTemplate("DeletePredicateAll",
                   "[item for item in {source_expr:VarOrExpr} if not ({predicate_expr:AnyPython})]",
                   {'is_predicate': True, 'is_first': False, 'names_index': False}),
        BiTemplate("DeletePredicateAllIndexed",
                   "[item for i, item in enumerate({source_expr:VarOrExpr}) if not ({predicate_expr:AnyPython})]",
                   {'is_predicate': True, 'is_first': False, 'names_index': True}),
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
        BiTemplate("FindIndicesIndexDict",
                   "list({source_expr:VarOrExpr})[{index_expr:IndexExpr}]",
                   {'is_index': True, 'is_dict': True}),
        BiTemplate("FindIndicesSliceDict",
                   "list({source_expr:VarOrExpr})[{slice_start:SliceComponent}:{slice_stop:SliceComponent}]",
                   {'is_slice': True, 'is_dict': True}),
        BiTemplate("FindIndicesPredicateFirstDict",
                   "next((k for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True,
                    'names_index': False, 'is_dict': True}),
        BiTemplate("FindIndicesPredicateFirstDictIndexed",
                   "next((k for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}), None)",
                   {'is_predicate': True, 'is_first': True,
                    'names_index': True, 'is_dict': True}),
        BiTemplate("FindIndicesPredicateDict",
                   "[k for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}]",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True, 'is_first': False}),
        BiTemplate("FindIndicesPredicateDictIndexed",
                   "[k for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}]",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True, 'is_first': False}),
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
        BiTemplate("CountPredicateDict",
                   "sum(1 for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython})",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("CountPredicateDictIndexed",
                   "sum(1 for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython})",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("CountPredicate",
                   "sum(1 for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython})",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("CountPredicateIndexed",
                   "sum(1 for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython})",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("CountMultiIndex",
                   "len({indices_expr:AnyPython})",
                   {'is_multi_index': True}),
    ], {}),

    # --- Any ---

    # Each action's whole-list form (what the visualizer generates before the
    # user types a search) comes last: the predicate and index forms are more
    # specific, and a whole-list source_expr would otherwise swallow them.

    Alt("AnyAction", [
        BiTemplate("AnyPredicateDict",
                   "any({predicate_expr:AnyPython} for k, v in {source_expr:VarOrExpr}.items())",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("AnyPredicateDictIndexed",
                   "any({predicate_expr:AnyPython} for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()))",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("AnyWholeListDict",
                   "any({source_expr:VarOrExpr}.values())",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("AnyPredicate",
                   "any({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("AnyPredicateIndexed",
                   "any({predicate_expr:AnyPython} for i, item in enumerate({source_expr:VarOrExpr}))",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("AnyMultiIndex",
                   "len({indices_expr:AnyPython}) > 0",
                   {'is_multi_index': True}),
        BiTemplate("AnyWholeList",
                   "any({source_expr:VarOrExpr})",
                   {'is_whole_list': True}),
    ], {}),

    # --- All ---

    Alt("AllAction", [
        BiTemplate("AllPredicateDict",
                   "all({predicate_expr:AnyPython} for k, v in {source_expr:VarOrExpr}.items())",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("AllPredicateDictIndexed",
                   "all({predicate_expr:AnyPython} for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()))",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("AllWholeListDict",
                   "all({source_expr:VarOrExpr}.values())",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("AllPredicate",
                   "all({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr})",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("AllPredicateIndexed",
                   "all({predicate_expr:AnyPython} for i, item in enumerate({source_expr:VarOrExpr}))",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("AllMultiIndex",
                   "len({indices_expr:AnyPython}) == len({source_expr:VarOrExpr})",
                   {'is_multi_index': True}),
        BiTemplate("AllWholeList",
                   "all({source_expr:VarOrExpr})",
                   {'is_whole_list': True}),
    ], {}),

    # --- If Any / If All ---

    Alt("IfAnyAction", [
        BiTemplate("IfAnyPredicateDict",
                   "if any({predicate_expr:AnyPython} for k, v in {source_expr:VarOrExpr}.items()):",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("IfAnyPredicateDictIndexed",
                   "if any({predicate_expr:AnyPython} for i, (k, v) in enumerate({source_expr:VarOrExpr}.items())):",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("IfAnyWholeListDict",
                   "if any({source_expr:VarOrExpr}.values()):",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("IfAnyPredicate",
                   "if any({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr}):",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("IfAnyPredicateIndexed",
                   "if any({predicate_expr:AnyPython} for i, item in enumerate({source_expr:VarOrExpr})):",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("IfAnyWholeList",
                   "if any({source_expr:VarOrExpr}):",
                   {'is_whole_list': True}),
    ], {}),

    Alt("IfAllAction", [
        BiTemplate("IfAllPredicateDict",
                   "if all({predicate_expr:AnyPython} for k, v in {source_expr:VarOrExpr}.items()):",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("IfAllPredicateDictIndexed",
                   "if all({predicate_expr:AnyPython} for i, (k, v) in enumerate({source_expr:VarOrExpr}.items())):",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("IfAllWholeListDict",
                   "if all({source_expr:VarOrExpr}.values()):",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("IfAllPredicate",
                   "if all({predicate_expr:AnyPython} for item in {source_expr:VarOrExpr}):",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("IfAllPredicateIndexed",
                   "if all({predicate_expr:AnyPython} for i, item in enumerate({source_expr:VarOrExpr})):",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("IfAllWholeList",
                   "if all({source_expr:VarOrExpr}):",
                   {'is_whole_list': True}),
    ], {}),

    # --- Loop ---

    Alt("LoopNoIdxAction", [
        BiTemplate("LoopNoIdxPredicateDict",
                   "for k, v in {k: v for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}}.items():",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("LoopNoIdxPredicateDictIndexed",
                   "for k, v in {k: v for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}}.items():",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("LoopNoIdxWholeListDict",
                   "for k, v in {source_expr:VarOrExpr}.items():",
                   {'is_whole_list': True, 'is_dict': True}),
        # An array pick is already a list, so the loop runs straight over it.
        BiTemplate("LoopNoIdxPick",
                   "for item in {:PickFirstMatch}:",
                   {'has_pick': True, 'pick_is_array': True}),
        BiTemplate("LoopNoIdxPredicate",
                   "for item in (item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}):",
                   {'is_predicate': True, 'names_index': False}),
        BiTemplate("LoopNoIdxPredicateIndexed",
                   "for item in (item for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}):",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("LoopNoIdxMultiIndex",
                   "for item in [{source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}]:",
                   {'is_multi_index': True}),
        BiTemplate("LoopNoIdxWholeList",
                   "for item in {source_expr:VarOrExpr}:",
                   {'is_whole_list': True}),
    ], {}),

    Alt("LoopOrigIdxAction", [
        BiTemplate("LoopOrigIdxPredicateDict",
                   "for k, v in {source_expr:VarOrExpr}.items():\n    if {predicate_expr:AnyPython}:",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("LoopOrigIdxPredicateDictIndexed",
                   "for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()):\n    if {predicate_expr:AnyPython}:",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("LoopOrigIdxWholeListDict",
                   "for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()):",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("LoopOrigIdxPredicate",
                   "for i, item in enumerate({source_expr:VarOrExpr}):\n    if {predicate_expr:AnyPython}:",
                   {'is_predicate': True}),
        BiTemplate("LoopOrigIdxMultiIndex",
                   "for i in {indices_expr:AnyPython}:",
                   {'is_multi_index': True}),
        BiTemplate("LoopOrigIdxWholeList",
                   "for i, item in enumerate({source_expr:VarOrExpr}):",
                   {'is_whole_list': True}),
    ], {}),

    Alt("LoopNewIdxAction", [
        BiTemplate("LoopNewIdxPredicateDict",
                   "for i, (k, v) in enumerate({k: v for k, v in {source_expr:VarOrExpr}.items() if {predicate_expr:AnyPython}}.items()):",
                   {'is_predicate': True, 'names_index': False, 'is_dict': True}),
        BiTemplate("LoopNewIdxPredicateDictIndexed",
                   "for i, (k, v) in enumerate({k: v for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()) if {predicate_expr:AnyPython}}.items()):",
                   {'is_predicate': True, 'names_index': True, 'is_dict': True}),
        BiTemplate("LoopNewIdxWholeListDict",
                   "for i, (k, v) in enumerate({source_expr:VarOrExpr}.items()):",
                   {'is_whole_list': True, 'is_dict': True}),
        BiTemplate("LoopNewIdxPick",
                   "for i, item in enumerate({:PickFirstMatch}):",
                   {'has_pick': True, 'pick_is_array': True}),
        BiTemplate("LoopNewIdxPredicate",
                   "for i, item in enumerate(item for item in {source_expr:VarOrExpr} if {predicate_expr:AnyPython}):",
                   {'is_predicate': True, 'names_index': False}),
        # The inner `i` is the row's number in the list and the outer one its
        # place among the matches; the predicate is written inside, so it reads
        # the inner one.
        BiTemplate("LoopNewIdxPredicateIndexed",
                   "for i, item in enumerate(item for i, item in enumerate({source_expr:VarOrExpr}) if {predicate_expr:AnyPython}):",
                   {'is_predicate': True, 'names_index': True}),
        BiTemplate("LoopNewIdxMultiIndex",
                   "for i, item in enumerate({source_expr:VarOrExpr}[i] for i in {indices_expr:AnyPython}):",
                   {'is_multi_index': True}),
        # Identical to the loop_orig_idx whole-list form; parse resolves the
        # ambiguity in favour of loop_orig_idx, which is listed first.
        BiTemplate("LoopNewIdxWholeList",
                   "for i, item in enumerate({source_expr:VarOrExpr}):",
                   {'is_whole_list': True}),
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
        # Find Indices before Filter: the pick templates below FilterAction take
        # an arbitrary picked expression, so they also match find_indices' own
        # `next((i for i, item in enumerate(xs) if p), None)`. Both readings
        # evaluate identically; find_indices is the canonical one for that line,
        # so it gets first refusal. (Consequence: picking only the index column
        # relinks as Find Indices rather than as a pick. Same value either way.)
        Alt("ActionFindIndices", ["FindIndicesAction"], {'action': 'find_indices'}),
        Alt("ActionFilter", ["FilterAction"], {'action': 'filter'}),
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
    has_var = bool(ctx.get('has_var'))
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
    # The same cut as the live generator: the positional families have no dict
    # templates, so without this a dict ctx would fall through to the list ones
    # and write a comprehension that silently yields keys.
    if ctx.get('is_dict') and (ctx.get('is_multi_index')
                               or ctx.get('is_broadcast_slice')
                               or ctx.get('pick_expr')):
        return None
    # Delete-one has no dict form: see the live generator for why.
    if ctx.get('is_dict') and ctx.get('is_first') and action not in (
            'filter', 'find_indices', 'delete'):
        return None
    gen_ctx = {k: v for k, v in ctx.items() if v is not None}
    gen_ctx['action'] = action
    gen_ctx['has_pick'] = bool(ctx.get('pick_expr'))
    gen_ctx['pick_is_array'] = bool(ctx.get('pick_expr')) and bool(ctx.get('pick_is_array'))
    if ctx.get('is_slice'):
        gen_ctx['has_slice_start'] = bool(ctx.get('slice_start'))
        gen_ctx['has_slice_stop'] = bool(ctx.get('slice_stop'))
    result = generate(TABLE_VIZ_GRAMMAR, TABLE_VIZ_GRAMMAR['Action'], gen_ctx)
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
            # A join over an array pick iterates the pick's next(...) wrapper,
            # not a plain list. Reading that as a whole-list source would make
            # the wrapper the "source expression" and quietly strip the pick, so
            # leave it unparsed and let relink fall back.
            if isinstance(comp.iter, ast.Call):
                return None
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
    # Statements are generated as bare headers, but text coming back from the
    # editor may still carry the placeholder body that was inserted with it.
    code_line = without_pass_body(code_line)
    ctx = parse(TABLE_VIZ_GRAMMAR, TABLE_VIZ_GRAMMAR['Action'], code_line)
    if ctx is not None:
        return ctx
    return _parse_generated_join(code_line)


def parse_generated_code_or_assignment(code_line: str) -> tuple[dict | None, str]:
    code_line = without_pass_body(code_line)
    ctx = parse(TABLE_VIZ_GRAMMAR, TABLE_VIZ_GRAMMAR['Assignment'], code_line)
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
