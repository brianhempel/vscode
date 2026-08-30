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

if __name__ == "__main__":
    with open("sculpin-todo-grouping.input.json") as f:
        doc = json.load(f)
    with open("sculpin-todo-grouping.commands.json") as f:
        commands = json.load(f)
    todos = apply(doc["todos"], commands)
    print(render(todos, doc["today"]))
