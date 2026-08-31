# Markdown table of contents

- **Source:** GitHub-flavored Markdown auto-generated heading anchors, as implemented by GitHub's `gfm-auto-identifiers` and by the widely used `markdown-toc` npm package (https://github.com/jonschlinkert/markdown-toc, ~1M weekly downloads) / `remark-slug`. The slug rules (lowercase; strip everything except letters, digits, `-`, `_`; spaces → `-`; repeated slugs get `-1`, `-2`, …) are documented in the GitHub Docs: https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#section-links. Generating a TOC is a real, common README chore; the input document is synthetic.
- **Tags:** line classification (heading vs. code vs. text) · counting a leading-character run · character-class filtering to build a slug · de-duplication with a counter dict · nesting by level · rendering an indented list
- **Data:** `markdown-toc.input.md` — 36 lines: headings at levels 1–3, punctuation in titles (`()`, `&`, `:`, `?`, quotes), two pairs of duplicate headings, a fenced code block containing a `#` line, and a `#Not a heading` decoy.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** string (document) → list of (level, title) → strings (slugs) → indented text

## Task description (as given to participant)

Write a script that reads `markdown-toc.input.md` and prints a table of contents as a nested Markdown bullet list, one line per heading, indented two spaces per heading level below the top-most level:

```
- [Widget Toolkit](#widget-toolkit)
  - [Installation](#installation)
    - [Requirements](#requirements)
```

Rules:

- A heading is a line starting with 1–6 `#` characters **followed by a space**; the number of `#`s is its level. Ignore lines inside fenced code blocks (between a pair of lines starting with ` ``` `).
- The link target is the GitHub-style anchor of the heading text: lowercase it, keep letters, digits, `-` and `_`, turn spaces into `-`, drop every other character. If the same anchor has already been used, append `-1` to the second occurrence, `-2` to the third, and so on.

## Expected output

```
- [Widget Toolkit](#widget-toolkit)
  - [Installation](#installation)
    - [Requirements](#requirements)
    - [Requirements](#requirements-1)
  - [Usage](#usage)
    - [Creating a widget](#creating-a-widget)
    - [Widget.render() & friends](#widgetrender--friends)
  - [FAQ: Why "Widget"?](#faq-why-widget)
  - [Usage](#usage-1)
```

## Notes for study designers

- A compact task with three clean stages that a tool could show live: (1) heading detection incl. the code-fence toggle, (2) slug generation (pure per-character string filtering — a "small pattern" task), (3) duplicate numbering with a dict.
- Seedable bugs for an edit task: forgetting the code fence (the comment line `# This is a comment…` appears in the TOC), forgetting the "space after #" rule (`#Not a heading` appears), or numbering duplicates from `-2`.
- Extensions: write the TOC back *into* the document between `<!-- toc -->` markers (`markdown-toc -i` behaviour); support setext (`====`) headings; limit depth.
- A regex (`^(#{1,6})\s+(.*)`) is the alternative for stage 1.

## Example solution

```python
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
```
