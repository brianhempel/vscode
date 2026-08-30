# Deep-merge layered JSON configs (defaults <- site <- local) and report
# which layer each leaf value came from.
import json

def deep_merge(base, override):
    """Return a new dict: override wins; nested dicts are merged recursively;
    lists and scalars are replaced wholesale."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def leaves(d, prefix=""):
    """Yield (dotted.path, value) for every non-dict value in a nested dict."""
    for key, value in d.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from leaves(value, path)
        else:
            yield path, value

if __name__ == "__main__":
    with open("deep-merge-configs.input.json") as f:
        layers = json.load(f)
    order = ["defaults", "site", "local"]
    merged = {}
    for name in order:
        merged = deep_merge(merged, layers[name])

    print(json.dumps(merged, indent=2, sort_keys=True))
    print()
    # Provenance: last layer (in order) whose leaves contain the same path.
    layer_leaves = {name: dict(leaves(layers[name])) for name in order}
    for path, value in sorted(leaves(merged)):
        origin = [name for name in order if path in layer_leaves[name]][-1]
        print(f"{path:<28} = {json.dumps(value):<22} (from {origin})")
