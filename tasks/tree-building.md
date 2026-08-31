# Tree building

- **Source:** Exercism `tree-building` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/tree-building (problem-specifications repo, MIT licence). On Exercism this is framed as a refactoring exercise (the Go/Python tracks give you a slow, convoluted implementation to clean up); here it is given as a from-scratch task.
- **Tags:** flat records → nested tree · dict of nodes · recursion · validation · JSON out · indented text rendering
- **Data:** `tree-building.input.json` — 7 records in scrambled order.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium (~15 minutes)
- **Shape:** JSON list → nested dict → indented outline string + JSON

## Task description (as given to participant)

`tree-building.input.json` is a list of records for a discussion-forum thread. Each record has a `record_id` and a `parent_id`, and the records are **not** in any particular order:

```json
[
  {"record_id": 5, "parent_id": 1},
  {"record_id": 3, "parent_id": 2},
  ...
]
```

Rules for a valid set of records:

- The record with id `0` is the root and its `parent_id` is also `0`.
- Ids are contiguous: for *n* records the ids are exactly `0 … n-1`.
- Every non-root record's `parent_id` is smaller than its own `record_id`.

Write a script that validates the records (raise an error with a helpful message if any rule is broken) and builds a nested tree where every node is `{"id": ..., "children": [...]}` with children sorted by id. Print (1) an indented outline of the tree, one node per line, two spaces per level, and (2) the tree as a single-line JSON string.

## Expected output

```
- 0
  - 1
    - 4
    - 5
  - 2
    - 3
    - 6
{"id": 0, "children": [{"id": 1, "children": [{"id": 4, "children": []}, {"id": 5, "children": []}]}, {"id": 2, "children": [{"id": 3, "children": []}, {"id": 6, "children": []}]}]}
```

## Notes for study designers

- Natural stages: (1) load JSON; (2) validate (three separate rules — a natural place for three small edits); (3) create one node dict per record, then link children to parents; (4) recursive rendering to text; (5) `json.dumps`.
- Key insight participants tend to find: build a `id → node` dict first, then attach — you don't need recursion to *build* the tree, only to *print* it. Processing records in id order makes the children automatically sorted.
- Good "edit this script" variants: feed it a file with a broken rule (e.g. a cycle `{"record_id": 2, "parent_id": 3}`) and ask for a clearer error; add a `"text"` field to records and show it in the outline; output the depth of the deepest node.
- The Exercism `canonical-data.json` provides ~13 cases including all the error cases.

## Example solution

```python
# Tree building: flat, scrambled (record_id, parent_id) records -> nested tree.
import json

def validate(records):
    if not records:
        return
    ids = sorted(r["record_id"] for r in records)
    if ids != list(range(len(records))):
        raise ValueError("record ids must be contiguous from 0")
    for r in records:
        rid, pid = r["record_id"], r["parent_id"]
        if rid == 0 and pid != 0:
            raise ValueError("root record must have parent 0")
        if rid != 0 and pid >= rid:
            raise ValueError(f"record {rid}: parent id must be smaller than child id")

def build_tree(records):
    validate(records)
    if not records:
        return None
    nodes = {r["record_id"]: {"id": r["record_id"], "children": []} for r in records}
    for r in sorted(records, key=lambda r: r["record_id"]):
        if r["record_id"] != 0:
            nodes[r["parent_id"]]["children"].append(nodes[r["record_id"]])
    return nodes[0]

def outline(node, depth=0):
    lines = ["  " * depth + f"- {node['id']}"]
    for child in node["children"]:
        lines.extend(outline(child, depth + 1))
    return lines

with open("tree-building.input.json") as f:
    records = json.load(f)
tree = build_tree(records)
print("\n".join(outline(tree)))
print(json.dumps(tree))
```
