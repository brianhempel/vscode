# Deep-merge layered configs

- **Source:** Stack Overflow, "How to merge dictionaries of dictionaries?" — https://stackoverflow.com/questions/7204805/how-to-merge-dictionaries-of-dictionaries (CC BY-SA; ~300k views) plus the ubiquitous *defaults ← site ← local* config-layering pattern (e.g. Django/Flask settings, `pyproject` tool tables). Description and data are original.
- **Tags:** nested dicts · recursion · dict merge semantics · dotted-path flattening · JSON in/out
- **Data:** `deep-merge-configs.input.json` — three config layers (`defaults`, `site`, `local`), ~20 leaves total. Synthetic.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium
- **Shape:** nested structure → nested structure → flat strings (provenance report)

## Task description (as given to participant)

`deep-merge-configs.input.json` holds three configuration layers under the keys `defaults`, `site` and `local`. Write a script that:

1. Merges them in that order (later layers win). Nested dictionaries must be merged *recursively* — `site` overriding `server.host` must not wipe out `server.port` from `defaults`. Lists and scalar values are replaced wholesale.
2. Prints the merged config as pretty JSON with sorted keys.
3. Prints a provenance report: one line per leaf value, in the form `dotted.path = value (from layer)`, sorted by path, where *layer* is the last layer that set that leaf.

## Expected output

```
{
  "features": {
    "beta": true,
    "experimental_ui": true,
    "search": true
  },
  "logging": {
    "handlers": [
      "console",
      "file"
    ],
    "level": "debug"
  },
  "name": "app-dev",
  "server": {
    "host": "example.org",
    "port": 9090,
    "tls": {
      "cert": "/etc/ssl/site.pem",
      "enabled": true
    }
  }
}

features.beta                = true                   (from site)
features.experimental_ui     = true                   (from local)
features.search              = true                   (from defaults)
logging.handlers             = ["console", "file"]    (from site)
logging.level                = "debug"                (from local)
name                         = "app-dev"              (from local)
server.host                  = "example.org"          (from site)
server.port                  = 9090                   (from local)
server.tls.cert              = "/etc/ssl/site.pem"    (from site)
server.tls.enabled           = true                   (from site)
```

## Notes for study designers

- Stage 1 is the SO question itself (recursive merge); stage 3 forces a *flatten to dotted paths* step, so the task moves nested → flat and uses the flat keys as strings. Pairs well with `flatten-nested-dict`.
- Good "edit the script" moments: a naive `dict.update()` version silently loses `server.port` — give that as starting code and ask why `port` disappeared; then ask to add list *concatenation* instead of replacement for `logging.handlers`; then ask for `null` in an override to mean "delete this key".
- Everything is dict/JSON-shaped; no string parsing beyond building the dotted paths, so it is a good counterpart to string-heavy tasks.

## Example solution

```python
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
```
