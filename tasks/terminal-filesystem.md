# Terminal filesystem

- **Source:** Paraphrased from Advent of Code 2022, day 7 ("No Space Left On Device", https://adventofcode.com/2022/day/7). AoC's About page asks that puzzle text and inputs not be copied, so the description below is rewritten in our own words and the input is a small synthetic transcript we generated. AoC puzzles are used as a problem source in the PSB2 program-synthesis benchmark (Helmuth & Kelly, GECCO 2021) and in several LLM code-generation benchmarks.
- **Tags:** line-oriented parsing · building a nested dict tree · recursive traversal · filtering by size · tree rendering
- **Data:** `terminal-filesystem.input.txt` — 34 lines, a made-up shell session over a tiny project tree (11 files/dirs).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** string → nested dict → numbers + rendered string

## Task description (as given to participant)

`terminal-filesystem.input.txt` is a transcript of someone exploring a disk with a tiny shell. Lines starting with `$` are commands: `$ cd /` goes to the root, `$ cd ..` goes up one level, `$ cd <name>` goes into a subdirectory, and `$ ls` lists the current directory. The lines following an `ls` (up to the next `$`) are its output: `dir <name>` for a subdirectory, or `<size> <filename>` for a file.

Write a script that:

1. Rebuilds the directory tree as nested dictionaries.
2. Prints an indented outline of the tree, with the total size of each directory (a directory's size is the sum of all files inside it, recursively).
3. Finds every directory whose total size is at most 100000, lists them, and prints the sum of their sizes.
4. The disk holds 250000 units and an upgrade needs 100000 free. Find the *smallest* directory that, if deleted, would leave at least 100000 free, and print its path and size.

## Expected output

```
- / (dir, size=215421)
  - docs (dir, size=94269)
    - changelog.txt (file, size=2557)
    - guide.pdf (file, size=29116)
    - images (dir, size=62596)
      - logo.png (file, size=62596)
  - notes.txt (file, size=14848)
  - readme.md (file, size=8504)
  - src (dir, size=97800)
    - lib (dir, size=86526)
      - parser.py (file, size=80900)
      - util.py (file, size=5626)
    - main.py (file, size=4060)
    - tests (dir, size=7214)
      - test_parser.py (file, size=7214)

Directories of size <= 100000: ['/docs', '/docs/images', '/src', '/src/lib', '/src/tests']
Sum of their sizes: 348405
Free space now: 34579; need to free at least 65421
Smallest directory to delete: /src/lib (size 86526)
```

## Notes for study designers

- Natural stages: (1) parse commands vs. output lines; (2) maintain a "current directory" stack while building the tree; (3) write a recursive size function that also records sizes per path; (4) filter/min over the resulting `{path: size}` dict; (5) render the outline.
- Gotchas: `$ ls` itself needs no action; `dir` entries may appear before being visited; the root directory must be included in the deletion candidates; the leaf name of `/` is empty when splitting on `/`.
- Variants: give participants a script that stores the tree but computes sizes non-recursively (wrong for nested dirs) and ask them to fix it; or ask for the outline sorted by size instead of name.
- The two numeric answers mirror the two "parts" of the original puzzle; the scaled-down disk sizes (250000 / 100000) keep the numbers readable.

## Example solution

```python
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
```
