# Markdown converter refactor

- **Source:** Exercism `markdown` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/markdown and its Python-track description (https://exercism.org/tracks/python/exercises/markdown). On Exercism this is explicitly a *refactoring* exercise: the student receives a working but convoluted implementation and a test suite, and must clean it up without breaking the tests. The starting code below is our own clunky implementation in that spirit (not Exercism's).
- **Tags:** refactoring · extracting functions · removing duplication · string prefix detection · inline pattern replacement (`__bold__`, `_italic_`) · state machine over lines
- **Data:** `markdown-refactor.input.md` (13 lines of Markdown); `markdown-refactor.starting.py` (the code to refactor).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium (~20–30 minutes). The output must not change.
- **Shape:** an *editing* task rather than a data-processing task: string → HTML string, with the deliverable being cleaner code.

## Task description (as given to participant)

`markdown-refactor.starting.py` converts a tiny subset of Markdown to HTML:

- `# Heading` … `###### Heading` → `<h1>` … `<h6>`
- lines starting with `* ` → `<ul><li>…</li>…</ul>` (consecutive bullets share one `<ul>`)
- `__text__` → `<strong>text</strong>`, `_text_` → `<em>text</em>` (first occurrence on the line)
- any other line → `<p>…</p>`

It works — run `python3 markdown-refactor.starting.py` on `markdown-refactor.input.md` and note the output — but it is hard to read: six near-identical heading branches, the bold/italic code is copy-pasted three times, and the list handling uses two confusing flags.

Refactor it so that it is easy to read and extend, **without changing its output for any input**. Suggested goals:

1. One function that handles inline `__bold__` / `_italic_` replacement.
2. One function that detects a heading and returns its level.
3. A single loop with a single `in_list` flag.
4. No unused variables (`is_bold`, `is_italic`).

Verify by diffing the output of your version against the original.

## Expected output

(Identical for the starting code and the refactored solution.)

```
<h1>Shopping notes</h1><p>This is a <strong>very</strong> short document.</p><p>It has <em>italic</em> and <strong>bold</strong> text.</p><h2>Things to buy</h2><ul><li>apples</li><li><strong>ripe</strong> bananas</li><li><em>good</em> cheese</li></ul><h3>Notes</h3><p>Remember to check the <em>date</em> on the milk.</p><ul><li>milk</li></ul><p>Done for <strong>now</strong>.</p><h6>Tiny heading</h6><p>The end.</p>
```

## Notes for study designers

- This is the one task in the set whose deliverable is *code shape*, not output — useful for evaluating an editing tool on "restructure this" operations (extract function, replace repeated block, delete dead code).
- Built-in correctness check: `diff <(python3 markdown-refactor.starting.py) <(python3 markdown-refactor.py)` must be empty. You could also give participants a handful of extra Markdown inputs as a test suite.
- Subtle behaviours the refactor must preserve: a heading line that contains `__x__` still gets bold applied; `__` must be handled *before* `_` (otherwise `__bold__` would turn into `<em></em>bold…`); a list is closed by the first non-bullet line (or end of input).
- Natural follow-up edits after the refactor (to test extensibility): add `**bold**` as an alternative to `__bold__`; support numbered lists `1. `; emit newlines between block elements.
- Because there is no "final answer", scoring is by test pass/fail plus a code-quality judgement (e.g. line count, number of functions, duplicated blocks).

## Starting code (`markdown-refactor.starting.py`)

```python
# Starting code: a working but clunky Markdown -> HTML converter.
# Supports: headings (# .. ######), * bullet lists, __bold__, _italic_, paragraphs.

def parse(markdown):
    lines = markdown.split('\n')
    res = ''
    in_list = False
    in_list_after = False
    for i in lines:
        if i.startswith('###### '):
            i = '<h6>' + i[7:] + '</h6>'
        elif i.startswith('##### '):
            i = '<h5>' + i[6:] + '</h5>'
        elif i.startswith('#### '):
            i = '<h4>' + i[5:] + '</h4>'
        elif i.startswith('### '):
            i = '<h3>' + i[4:] + '</h3>'
        elif i.startswith('## '):
            i = '<h2>' + i[3:] + '</h2>'
        elif i.startswith('# '):
            i = '<h1>' + i[2:] + '</h1>'
        if i.startswith('* '):
            if not in_list:
                in_list = True
                is_bold = False
                is_italic = False
                curr = i[2:]
                if curr.count('__') >= 2:
                    curr = curr.replace('__', '<strong>', 1)
                    curr = curr.replace('__', '</strong>', 1)
                    is_bold = True
                if curr.count('_') >= 2:
                    curr = curr.replace('_', '<em>', 1)
                    curr = curr.replace('_', '</em>', 1)
                    is_italic = True
                i = '<ul><li>' + curr + '</li>'
            else:
                is_bold = False
                is_italic = False
                curr = i[2:]
                if curr.count('__') >= 2:
                    curr = curr.replace('__', '<strong>', 1)
                    curr = curr.replace('__', '</strong>', 1)
                    is_bold = True
                if curr.count('_') >= 2:
                    curr = curr.replace('_', '<em>', 1)
                    curr = curr.replace('_', '</em>', 1)
                    is_italic = True
                i = '<li>' + curr + '</li>'
        else:
            if in_list:
                in_list_after = True
                in_list = False

        if not i.startswith('<h') and not i.startswith('<ul') and not i.startswith('<li'):
            i = '<p>' + i + '</p>'
        if i.count('__') >= 2:
            i = i.replace('__', '<strong>', 1)
            i = i.replace('__', '</strong>', 1)
        if i.count('_') >= 2:
            i = i.replace('_', '<em>', 1)
            i = i.replace('_', '</em>', 1)
        if in_list_after:
            i = '</ul>' + i
            in_list_after = False
        res += i
    if in_list:
        res += '</ul>'
    return res

with open('markdown-refactor.input.md') as f:
    print(parse(f.read().rstrip('\n')))
```

## Example solution

```python
# Refactored Markdown -> HTML converter. Same output as markdown-refactor.starting.py.
# Supports: headings (# .. ######), * bullet lists, __bold__, _italic_, paragraphs.

def wrap(text, tag):
    return f"<{tag}>{text}</{tag}>"

def inline(text):
    """Replace the first __x__ with <strong>, then the first _y_ with <em>."""
    for marker, tag in (("__", "strong"), ("_", "em")):
        if text.count(marker) >= 2:
            text = text.replace(marker, f"<{tag}>", 1).replace(marker, f"</{tag}>", 1)
    return text

def heading(line):
    """Return (level, text) if `line` is a heading, else None."""
    for level in range(6, 0, -1):
        prefix = "#" * level + " "
        if line.startswith(prefix):
            return level, line[len(prefix):]
    return None

def parse(markdown):
    html = []
    in_list = False
    for line in markdown.split("\n"):
        if line.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(wrap(inline(line[2:]), "li"))
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        h = heading(line)
        if h:
            level, text = h
            html.append(wrap(inline(text), f"h{level}"))
        else:
            html.append(wrap(inline(line), "p"))
    if in_list:
        html.append("</ul>")
    return "".join(html)

with open("markdown-refactor.input.md") as f:
    print(parse(f.read().rstrip("\n")))
```
