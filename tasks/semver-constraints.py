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

if __name__ == "__main__":
    versions, constraints = read_input("semver-constraints.input.txt")
    parsed = sorted(((parse_version(v), v) for v in versions))
    for c in constraints:
        clauses = parse_constraint(c)
        matches = [text for tup, text in parsed if satisfies(tup, clauses)]
        best = matches[-1] if matches else "none"
        print(f"{c:<22} -> {best:<12} ({len(matches)} match{'es' if len(matches) != 1 else ''}: {', '.join(matches)})")
