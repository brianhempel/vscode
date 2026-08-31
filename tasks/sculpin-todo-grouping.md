# TODO list: apply commands, group by assignee, snooze and dim

- **Source:** Josh Horowitz & Jeffrey Heer, "Sculpin: Direct-Manipulation Transformation of JSON" (2025), Figure 6 — a shared team TODO-list app built atop a JSON document: restyle the list to group tasks by assignee, dim completed tasks, and program an "Add todo" button. The *snooze until a date* feature comes from Geoffrey Litt & Daniel Jackson, "Wildcard: Spreadsheet-Driven Customization of Web Applications", Onward! 2020, https://doi.org/10.1145/3426428.3426914 (their TodoMVC example). Data and commands are synthetic.
- **Tags:** JSON document as state · applying a command list (add / done / snooze) · id allocation · group-by · date comparison on ISO strings · text-UI rendering
- **Data:** `sculpin-todo-grouping.input.json` (6 todos + a `today` date) and `sculpin-todo-grouping.commands.json` (5 commands).
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium
- **Shape:** JSON + command list → mutated nested state → grouped → rendered text. A small *app-like* task rather than data analysis.

## Task description (as given to participant)

`sculpin-todo-grouping.input.json` holds a team's shared TODO list:

```
{"today": "2024-05-08",
 "todos": [{"id": 1, "text": "...", "assignee": "Maya", "done": false, "snoozed_until": null}, ...]}
```

`sculpin-todo-grouping.commands.json` is a list of button presses recorded from the app's UI, in order:
`{"op": "add", "text", "assignee"}` (new todo, next free id, not done, not snoozed), `{"op": "done", "id"}`, `{"op": "snooze", "id", "until": "YYYY-MM-DD"}`.

Write a script that applies the commands to the list and then prints the list grouped by assignee (alphabetical):

- A header line per assignee: `<name>: <open> open, <done> done` plus `, <n> snoozed` when some items are hidden.
- Todos whose `snoozed_until` is after `today` are hidden (and counted as snoozed). A snooze date that has already passed shows the item normally.
- Each visible todo on its own line as `  [x] #<id> ~~text~~` when done, `  [ ] #<id> text` otherwise.
- A blank line between groups. First line: `TODOs as of <today>`.

## Expected output

```
TODOs as of 2024-05-08

Maya: 1 open, 1 done, 1 snoozed
  [x] #1 ~~Write the intro section~~
  [ ] #7 Send the calendar invite

Ravi: 0 open, 1 done, 1 snoozed
  [x] #6 ~~Review pull request #42~~

Theo: 1 open, 2 done
  [x] #2 ~~Fix the login bug~~
  [ ] #4 Update the README
  [x] #8 ~~Prepare slides~~
```

## Notes for study designers

- Stages: (1) apply commands — needs an id→todo index and a next-id counter (note the last command marks a todo that was *created by an earlier command*); (2) group; (3) date filter; (4) render with counts.
- Gotchas: ISO dates compare correctly as strings, which participants may not trust; "snoozed" must be counted from the *hidden* items only; done+snoozed interplay.
- Extensions: an `"assign"` command that moves a todo to another person; a `"today"` override from the command line; render as HTML `<ul>` per assignee instead of text; a `"purge"` op that removes done items and renumbers.
- Pairs well with `rest-api-ious` (also JSON-state-plus-commands) and `wildcard-listings`.

## Example solution

```python
# TODO app on a JSON document: apply commands (add / done / snooze), then
# render the list grouped by assignee, hiding snoozed items and dimming
# completed ones.
import json

def apply(todos, commands):
    next_id = max((t["id"] for t in todos), default=0) + 1
    by_id = {t["id"]: t for t in todos}
    for cmd in commands:
        if cmd["op"] == "add":
            todo = {"id": next_id, "text": cmd["text"], "assignee": cmd["assignee"],
                    "done": False, "snoozed_until": None}
            todos.append(todo)
            by_id[next_id] = todo
            next_id += 1
        elif cmd["op"] == "done":
            by_id[cmd["id"]]["done"] = True
        elif cmd["op"] == "snooze":
            by_id[cmd["id"]]["snoozed_until"] = cmd["until"]
        else:
            raise ValueError(f"unknown op {cmd['op']!r}")
    return todos

def is_hidden(todo, today):
    # ISO dates compare correctly as strings.
    return todo["snoozed_until"] is not None and todo["snoozed_until"] > today

def render(todos, today):
    groups = {}
    for t in todos:
        groups.setdefault(t["assignee"], []).append(t)
    lines = [f"TODOs as of {today}", ""]
    for assignee in sorted(groups):
        items = groups[assignee]
        visible = [t for t in items if not is_hidden(t, today)]
        open_count = sum(1 for t in visible if not t["done"])
        hidden = len(items) - len(visible)
        header = f"{assignee}: {open_count} open, {len(visible) - open_count} done"
        if hidden:
            header += f", {hidden} snoozed"
        lines.append(header)
        for t in visible:
            text = f"~~{t['text']}~~" if t["done"] else t["text"]
            lines.append(f"  [{'x' if t['done'] else ' '}] #{t['id']} {text}")
        lines.append("")
    return "\n".join(lines).rstrip()

with open("sculpin-todo-grouping.input.json") as f:
    doc = json.load(f)
with open("sculpin-todo-grouping.commands.json") as f:
    commands = json.load(f)
todos = apply(doc["todos"], commands)
print(render(todos, doc["today"]))
```
