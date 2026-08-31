# Flatten a nested JSON config into dotted keys ("server.tls.enabled"),
# then unflatten it back and check the round trip.
import json

def flatten(obj, prefix=""):
    """Return {dotted_key: leaf_value} for a nested dict/list structure."""
    flat = {}
    if isinstance(obj, dict):
        items = obj.items()
    elif isinstance(obj, list):
        items = ((str(i), v) for i, v in enumerate(obj))
    else:
        return {prefix: obj}
    for key, value in items:
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, (dict, list)) and value:
            flat.update(flatten(value, full))
        else:
            flat[full] = value
    return flat

def unflatten(flat):
    """Rebuild the nested structure. A container whose keys are all
    consecutive integers 0..n-1 becomes a list, otherwise a dict."""
    root = {}
    for dotted, value in flat.items():
        parts = dotted.split(".")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return _listify(root)

def _listify(node):
    if not isinstance(node, dict):
        return node
    node = {k: _listify(v) for k, v in node.items()}
    keys = list(node)
    if keys and all(k.isdigit() for k in keys):
        as_int = sorted(int(k) for k in keys)
        if as_int == list(range(len(keys))):
            return [node[str(i)] for i in as_int]
    return node

with open("flatten-nested-dict.input.json") as f:
    config = json.load(f)

flat = flatten(config)
width = max(len(k) for k in flat)
for key in sorted(flat):
    print(f"{key:<{width}}  = {json.dumps(flat[key])}")

rebuilt = unflatten(flat)
print()
print("round trip ok:", rebuilt == config)
print("replica hosts:", [r["host"] for r in rebuilt["database"]["replicas"]])
