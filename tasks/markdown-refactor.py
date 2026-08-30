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

if __name__ == "__main__":
    with open("markdown-refactor.input.md") as f:
        print(parse(f.read().rstrip("\n")))
