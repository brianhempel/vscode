# Terminal filesystem: rebuild a directory tree from a shell transcript and size it.

TOTAL_SPACE = 250000
NEEDED_FREE = 100000
SMALL_LIMIT = 100000

def build_tree(lines):
    root = {}          # a directory is a dict: name -> subdirectory dict | file size int
    path = [root]      # stack of dicts; path[-1] is the current directory
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "$":
            if parts[1] == "cd":
                target = parts[2]
                if target == "/":
                    path = [root]
                elif target == "..":
                    path.pop()
                else:
                    path.append(path[-1].setdefault(target, {}))
            # "$ ls" needs no action; the lines that follow are its output.
        elif parts[0] == "dir":
            path[-1].setdefault(parts[1], {})
        else:
            size, name = parts
            path[-1][name] = int(size)
    return root

def sizes_of(tree):
    """Return {"/path/to/dir": total_size} for every directory in the tree."""
    out = {}
    def walk(node, name):
        total = 0
        for child, value in node.items():
            if isinstance(value, dict):
                total += walk(value, name.rstrip("/") + "/" + child)
            else:
                total += value
        out[name] = total
        return total
    walk(tree, "/")
    return out

def outline(tree, sizes, name="/", depth=0):
    label = name.split("/")[-1] or "/"
    lines = [f"{'  ' * depth}- {label} (dir, size={sizes[name]})"]
    for child, value in sorted(tree.items()):
        if isinstance(value, dict):
            lines += outline(value, sizes, name.rstrip("/") + "/" + child, depth + 1)
        else:
            lines.append(f"{'  ' * (depth + 1)}- {child} (file, size={value})")
    return lines

with open("terminal-filesystem.input.txt") as f:
    tree = build_tree(f.readlines())
sizes = sizes_of(tree)
print("\n".join(outline(tree, sizes)))
print()
small = {d: s for d, s in sizes.items() if s <= SMALL_LIMIT}
print(f"Directories of size <= {SMALL_LIMIT}: {sorted(small)}")
print(f"Sum of their sizes: {sum(small.values())}")
free_now = TOTAL_SPACE - sizes["/"]
must_free = NEEDED_FREE - free_now
candidates = {d: s for d, s in sizes.items() if s >= must_free}
best = min(candidates, key=candidates.get)
print(f"Free space now: {free_now}; need to free at least {must_free}")
print(f"Smallest directory to delete: {best} (size {sizes[best]})")
