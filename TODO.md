- [x] clean up a bit
- [x] fix up tooltips
- [x] fix up dropdowns
- [x] restore clickable match obj helpers (just show match obj between find/replace?)
- [x] fix string visualizer selection undo history
- [x] show string segment regex on hover and while drawing
- [x] ability to resize segments leftward
- [x] segment repetition and kind dropdowns: current value should be preselected/prefilled in the items
- [x] literal and fuzzy selection as tool buttons
- [x] remove \A \Z
- [x] misaligned single-line generic visualizer
- [x] only turn it on  for Python files
- [x] find the correct python interpreter using the official Python extension's machinery
- [x] cleaner handling of many visualizers (b)
    - [x] small mode for less relevant visualizers. current/next/previous line of code, unused variables (b)
    - [x] don't show string tools menu in small mode (b)
    - [x] exit small mode on click instead of on hover (b)
    - [x] make sure lists of string look nice (b)
    - [x] don't crash when visualizing adding a list of $T$ to each row of a list of $T$, this creates a recursion because the column config says "when I have a list of $T$, for each row show a list of $T$ (and the for each of those subrows, show a list of $T$, etc)" (b)
- [x] visual cleanups
	- [x] override gutter color to be same color as background
	- [x] strings: always show ^ $ \n in focused mode
	- [x] string: show "" in non-focused mode
	- [x] nested visualizers: don't show border
	- [x] tables: use cell borders, not visualizer borders
	- [x] grab only small visualizers
- [x] as soon as there is an interaction on a visualizer, auto-generate a linked next line of code (string + list visualizers; first interaction inserts and self-links, later interactions update it in place; handles the import-shift case where an auto-added `import re` shifts the visualizer's line)
    - [ ] what is a way for a user to quickly back out and delete that LOC, in case they just wanted to use the *copy* or *drag-n-drop* features?
- [x] first new object after a for loop needs correct indentation (j)
- [x] list join should work on a slice
- [x] Restore true/false preview to any/all (like in the string visualizer)
- [x] add new var action in tooltip:
    - [x] better var names
    - [x] shouldn't assign a for-loop expression (or similar) to a var
- [x] nicer move/remove/add buttons for table columns (at one point they were just like braille six dots for move and an X and a plus)
- [ ] errors shouldn't use string visualizer
- [x] tooltips (and maybe dropdowns too) shouldn't disappear before the mouse enters them
- [x] expression tooltips: add + button that makes a new var with the expression
- [x] make a pick segment mode for lists: can pick indices, whole rows, or just selected columns
- [x] figure out what table widgets should be per column
- [x] column tally
- [x] aggregations
- [x] x button for group by aggregations
- [x] snc-py-exp for per-group aggregations
- [x] reify as...list of dict etc, to persist transient columns
- [ ] make it clearer what kind of object you are looking at. *jacob says: representing everything as a table is a little funky because it's hard to realize that what you're looking at isn't a table. it is structurally something else?*
- [x] drag to reorder subcolumns
- [ ] when there's subcolumns, double-click to edit is causing a diff column to appear
- [ ] need to show list length somewhere
- [ ] need to show string length somewhere
- [ ] extract row by grabbing index cell
- [ ] add column left/right in col menu
- [ ] need to be able to pick or select columns without a filter predicate first
- [ ] need to able to select/delete rows (e.g. delete header row)
- [ ] column search box on a splat (or anything under one) is dead UI: it accepts
      text and stores it, but `_column_row_expr` is None for those targets so
      `_searchable_targets` leaves them out and `compose_column_searches` never
      sees them — nothing filters, yet the header goes `col-filtered` and the ▾
      goes `active`, so the UI claims a filter is on. The tally in the same menu
      already gates on `filterable`; the search row never got the same treatment.
      Either hide the row when `_column_row_expr` is None or dim it, and gate
      `_column_search_active` the same way so stale stored text stops lighting
      the header. Note `$j` could not work there even if the search were wired
      up: the lift carries sigils into main-search scope, which binds only
      `{'i': ...}` (or the dict trio), and the main search filters ROOT rows
      while `$j` names a position inside one root row's splatted group
- [ ] certain drags modify their exp so you can drag into e.g. the col expression
- [ ] hiding the $ sometimes is a bit funky
- [ ] $item instead of $, maybe?
- [ ] col action: convert to int, float
- [ ] dictionary visualizer
- [ ] tuple visualizer
- [ ] list of tuples
- [ ] tuple of lists
- [x] group by (i.e. dictionaries of lists)
- [ ] generic object visualizer
- [ ] visualize sets
- [ ] make it clearer what is temp state versus reified in code. *jacob: the fact that there is temp state is a little funky too*
- [ ] make the above work nicely for large, nested JSON blobs (Ultorg lol)
- [ ] use VS Code debug config to know how to launch python and app

## Details

- [x] col add button: show on visualizer focus rather than on hover
- [x] close column menu when un-focusing
- [ ] list visualizer search: be smart so that simple var uses are == rather than treated as simple truthy predicates
- [ ] below multiline exp
- [ ] there may be some AI-written parse hacks to avoid figuring out BiTemplates (e.g. `_parse_generated_join`). see if these can be turned into BiTemplates
