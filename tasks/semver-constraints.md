# Resolve semver version ranges

- **Source:** Semantic Versioning 2.0.0 — https://semver.org/ (§9–11: pre-release identifiers and precedence) and npm's range syntax — https://docs.npmjs.com/cli/v10/configuring-npm/package-json#dependencies / https://github.com/npm/node-semver#ranges. This is exactly what `npm`, `pip`, `cargo` and `bundler` do when picking a version, so it is a real-world spec rather than a toy; small "pick the highest matching version" reimplementations appear frequently in interview questions and Stack Overflow ("How do I compare version numbers in Python?", ~1M views: https://stackoverflow.com/questions/11887762). Version list and constraints are synthetic.
- **Tags:** splitting strings into comparable tuples · pre-release handling (`-rc.1`, mixed int/str segments) · parsing a tiny constraint language (`^`, `~`, `x`, comparators) · filtering a list against predicates · sectioned input file
- **Data:** `semver-constraints.input.txt` — 18 available versions (incl. 4 pre-releases) and 8 constraints, in two labelled sections with `#` comments.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium–hard (the tuple-comparison trick is the key insight; range operators are then mechanical)
- **Shape:** strings → tuples → filtered/sorted list → formatted strings

## Task description (as given to participant)

`semver-constraints.input.txt` has two sections: `versions:` (the versions of a package that exist) and `constraints:` (version ranges someone has asked for). Lines starting with `#` are comments.

Versions are `MAJOR.MINOR.PATCH` with an optional pre-release suffix such as `1.5.0-rc.1` or `2.0.0-beta.2`. Ordering: compare major, minor, patch numerically; a pre-release sorts *before* the corresponding release (`2.0.0-beta.2 < 2.0.0`); pre-release identifiers compare segment by segment, numerically when numeric.

Constraint syntax (a subset of npm's):

| form | meaning |
|---|---|
| `*` | anything |
| `1.x` | `>=1.0.0 <2.0.0` |
| `^1.2.0` | `>=1.2.0` and same leading non-zero component (`<2.0.0`; for `^0.9.0` it is `<0.10.0`) |
| `~1.4.1` | `>=1.4.1 <1.5.0` |
| `>=1.0.0 <2.0.0` | space-separated comparators (`>=`, `>`, `<=`, `<`, `=`), all must hold |

Pre-release versions never match a range unless the range itself mentions a pre-release version.

For each constraint print the highest matching version and the full list of matches, e.g.

```
~1.4.1                 -> 1.4.7        (2 matches: 1.4.1, 1.4.7)
```

## Expected output

```
^1.2.0                 -> 1.5.0        (7 matches: 1.2.0, 1.2.3, 1.3.1, 1.4.0, 1.4.1, 1.4.7, 1.5.0)
~1.4.1                 -> 1.4.7        (2 matches: 1.4.1, 1.4.7)
>=1.0.0 <2.0.0         -> 1.5.0        (10 matches: 1.0.0, 1.0.2, 1.1.0, 1.2.0, 1.2.3, 1.3.1, 1.4.0, 1.4.1, 1.4.7, 1.5.0)
1.x                    -> 1.5.0        (10 matches: 1.0.0, 1.0.2, 1.1.0, 1.2.0, 1.2.3, 1.3.1, 1.4.0, 1.4.1, 1.4.7, 1.5.0)
2.x                    -> 2.1.5        (3 matches: 2.0.0, 2.1.0, 2.1.5)
*                      -> 2.1.5        (14 matches: 0.9.4, 1.0.0, 1.0.2, 1.1.0, 1.2.0, 1.2.3, 1.3.1, 1.4.0, 1.4.1, 1.4.7, 1.5.0, 2.0.0, 2.1.0, 2.1.5)
>2.0.0-beta.1 <2.0.0   -> 2.0.0-beta.2 (1 match: 2.0.0-beta.2)
^0.9.0                 -> 0.9.4        (1 match: 0.9.4)
```

## Notes for study designers

- Stage decomposition: (1) sectioned-file reader; (2) `parse_version` string→tuple; (3) `parse_constraint` string→list of (op, tuple); (4) filter + max; (5) formatting. Each stage is small and independently checkable.
- Classic bugs to seed for an "edit" task: comparing versions as strings (`"1.10.0" < "1.9.0"`), forgetting that `1.5.0-rc.1 < 1.5.0`, or letting `^1.2.0`'s upper bound accidentally admit `1.5.0-rc.1`.
- Simplifications: drop pre-releases entirely; support only `^` and `~`. Extensions: `||` unions, `1.2.x`, hyphen ranges `1.2.3 - 2.3.4`.
- Real npm's pre-release rule is narrower (a pre-release matches only if a comparator has the *same* major.minor.patch); the task uses the simpler rule stated above.

## Example solution

```python
# Resolve npm-style version ranges against a list of available semver versions.

def parse_version(text):
    """'1.5.0-rc.1' -> (1, 5, 0, ('rc', 1)).  A release (no pre-release tag)
    sorts *after* any pre-release of the same number, so we use () as the
    tag for releases and a tuple that compares smaller for pre-releases."""
    core, _, pre = text.partition("-")
    major, minor, patch = (int(p) for p in core.split("."))
    if pre:
        tag = tuple(int(p) if p.isdigit() else p for p in pre.split("."))
        return (major, minor, patch, 0, tag)     # 0 = pre-release
    return (major, minor, patch, 1, ())          # 1 = release

def is_prerelease(v):
    return v[3] == 0

def parse_constraint(text):
    """Turn one constraint into a list of (op, version_tuple) that must ALL hold.
    Supports: *, X.x, ^, ~, and space-separated comparators (>=, >, <=, <, =)."""
    clauses = []
    for part in text.split():
        if part == "*":
            continue
        if part.endswith(".x") or part.endswith(".*"):
            major = int(part.split(".")[0])
            clauses += [(">=", (major, 0, 0, 1, ())), ("<", (major + 1, 0, 0, 1, ()))]
        elif part.startswith("^"):
            v = parse_version(part[1:])
            if v[0] > 0:
                upper = (v[0] + 1, 0, 0, 1, ())
            elif v[1] > 0:
                upper = (0, v[1] + 1, 0, 1, ())
            else:
                upper = (0, 0, v[2] + 1, 1, ())
            clauses += [(">=", v), ("<", upper)]
        elif part.startswith("~"):
            v = parse_version(part[1:])
            clauses += [(">=", v), ("<", (v[0], v[1] + 1, 0, 1, ()))]
        else:
            for op in (">=", "<=", ">", "<", "="):
                if part.startswith(op):
                    clauses.append((op, parse_version(part[len(op):])))
                    break
            else:
                clauses.append(("=", parse_version(part)))
    return clauses

OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    "=":  lambda a, b: a == b,
}

def satisfies(version, clauses):
    if is_prerelease(version) and not any(is_prerelease(v) for _, v in clauses):
        return False   # pre-releases only match if the range itself mentions one
    return all(OPS[op](version, v) for op, v in clauses)

def read_input(path):
    sections = {"versions": [], "constraints": []}
    current = None
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            current = line[:-1]
        else:
            sections[current].append(line)
    return sections["versions"], sections["constraints"]

versions, constraints = read_input("semver-constraints.input.txt")
parsed = sorted(((parse_version(v), v) for v in versions))
for c in constraints:
    clauses = parse_constraint(c)
    matches = [text for tup, text in parsed if satisfies(tup, clauses)]
    best = matches[-1] if matches else "none"
    print(f"{c:<22} -> {best:<12} ({len(matches)} match{'es' if len(matches) != 1 else ''}: {', '.join(matches)})")
```
