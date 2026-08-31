# JSON abacus: sum every number in a nested JSON document, then again while
# ignoring any object that has a value equal to "red".
import json

def total(node, skip_red=False):
    if isinstance(node, bool):          # bool is a subclass of int; don't count it
        return 0
    if isinstance(node, (int, float)):
        return node
    if isinstance(node, list):
        return sum(total(item, skip_red) for item in node)
    if isinstance(node, dict):
        if skip_red and "red" in node.values():
            return 0
        return sum(total(value, skip_red) for value in node.values())
    return 0                            # strings (even "12") and None count as zero

with open("json-abacus.input.json") as f:
    doc = json.load(f)
print(f"Sum of all numbers: {total(doc)}")
print(f"Sum ignoring 'red' objects: {total(doc, skip_red=True)}")
