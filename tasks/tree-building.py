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
