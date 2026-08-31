# Build a nested table of contents for a Markdown file, using GitHub-style
# heading anchors (lowercase, punctuation removed, spaces -> '-', duplicates
# suffixed with -1, -2, ...).

def slugify(title):
    slug = []
    for ch in title.lower():
        if ch.isalnum() or ch in "-_":
            slug.append(ch)
        elif ch == " ":
            slug.append("-")
        # any other punctuation is dropped
    return "".join(slug)

def headings(lines):
    """Yield (level, title) for ATX headings, skipping fenced code blocks."""
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.startswith("#"):
            continue
        hashes = len(line) - len(line.lstrip("#"))
        rest = line[hashes:]
        if not rest.startswith(" "):      # '#Not a heading' -> ignore
            continue
        yield hashes, rest.strip()

def build_toc(lines):
    seen = {}         # base slug -> how many times used so far
    entries = []      # (level, title, unique slug)
    for level, title in headings(lines):
        base = slugify(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        slug = base if n == 0 else f"{base}-{n}"
        entries.append((level, title, slug))
    return entries

with open("markdown-toc.input.md") as f:
    lines = [l.rstrip("\n") for l in f]
toc = build_toc(lines)
top = min(level for level, _, _ in toc)
for level, title, slug in toc:
    indent = "  " * (level - top)
    print(f"{indent}- [{title}](#{slug})")
