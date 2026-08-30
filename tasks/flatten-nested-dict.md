# Flatten a nested config (and unflatten it back)

- **Source:** Stack Overflow, "Flatten nested dictionaries, compressing keys" — https://stackoverflow.com/questions/6027558/flatten-nested-dictionaries-compressing-keys (one of the most-viewed Python dict questions on SO, ~500k views; the same operation exists as `pandas.json_normalize`, `flatten-dict` on PyPI, and in many config/ETL tools). This is a spec-by-popular-question rather than a benchmark, but the shape — nested JSON config ↔ flat `a.b.c` keys as used in `.env`/`.properties` files, Spring `application.properties`, Terraform, etc. — is a real everyday programming chore.
- **Tags:** recursion over nested dicts/lists · building dotted-string keys · splitting keys back into a path · list-vs-dict detection · JSON I/O
- **Data:** `flatten-nested-dict.input.json` — a 17-leaf synthetic app config with dicts inside dicts, a list of scalars and a list of dicts.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium (flatten is easy; the round trip back is the interesting half)
- **Shape:** nested data → strings (dotted keys) → nested data

## Task description (as given to participant)

`flatten-nested-dict.input.json` is an application config with nested objects and arrays. Write a script that:

1. **Flattens** it into a single-level dict whose keys are the paths to each leaf joined with `.` — array elements use their index as a key segment, e.g. `server.ports.0`, `database.replicas.1.host`.
2. Prints every flattened key/value, sorted by key, one per line, aligned like `key  = value` (values shown as JSON, so strings are quoted and booleans are `true`/`false`).
3. **Unflattens** the flat dict back into nested dicts/lists (a level whose keys are `0..n-1` becomes a list) and prints whether the result equals the original.
4. Prints the list of replica database hosts, read from the rebuilt structure.

## Expected output

```
app.debug                 = false
app.name                  = "inventory"
app.version               = "1.4.2"
database.primary.host     = "db1.internal"
database.primary.port     = 5432
database.replicas.0.host  = "db2.internal"
database.replicas.0.port  = 5432
database.replicas.1.host  = "db3.internal"
database.replicas.1.port  = 5433
features.0                = "search"
features.1                = "export"
log_level                 = "info"
server.host               = "0.0.0.0"
server.ports.0            = 8080
server.ports.1            = 8443
server.tls.cert           = "/etc/ssl/inventory.pem"
server.tls.enabled        = true

round trip ok: True
replica hosts: ['db2.internal', 'db3.internal']
```

## Notes for study designers

- Stage 1 (flatten) is pure recursion producing strings; stage 3 (unflatten) is the mirror: `split(".")`, walk/create the path, then a post-pass deciding which dicts are really lists. Doing both directions in one script exercises "strings ↔ nested data in synchrony".
- Decision points worth watching: what to do with empty dicts/lists (the solution keeps them as leaves); whether `"0"`-keyed dicts are ambiguous (they are — a good discussion prompt).
- Simpler variant: flatten only, dicts only (no lists). Harder variant: emit as a `.properties`/`.env` file and read it back.
- A regex is not needed anywhere; everything is `split`/`join`/`isdigit`.

## Example solution

```python
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

if __name__ == "__main__":
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
```
