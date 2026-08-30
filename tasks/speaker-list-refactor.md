# Merge two divergent edits of a speaker list (list → table refactor)

- **Source:** Jonathan Edwards, Tomas Petricek & Tijs van der Storm, "Live & Local Schema Change: Challenge Problems" (2023), https://arxiv.org/abs/2309.11406 — §4 *Conference Organizer: merging structural document edits* and §5 *…in the presence of code*: organizer A adds a speaker and sorts the bullet list; organizer B refactors the list into a table with an extra Organizer column and updates the formula `=COUNT(/ul[id='speakers']/li)` to `=COUNT(/table[id='speakers']/tbody/tr)`; the merged document must contain A's speakers in A's order, in B's format. The same example is a formative example for Denicek (Petricek & Edwards, "Denicek: Computational Substrate for Document-Oriented End-User Programming", 2025). The three document versions are transcribed from the paper's figures.
- **Tags:** line-oriented Markdown parsing (bullets vs. table rows) · splitting `Name, email` · union by key preserving one side's order · re-rendering as a table · rewriting a formula path string
- **Data:** `speaker-list-refactor.base.md`, `speaker-list-refactor.a.md`, `speaker-list-refactor.b.md` (~14 lines each).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** two Markdown documents → lists of records → merged list → Markdown document. A *document-editing* task, not data analysis.

## Task description (as given to participant)

Three versions of a conference-planning document are given. `base.md` has an "Invited speakers" section as a bullet list (`- Name, email`) and a budget section with formulas. Two organizers edited the base independently:

- `a.md`: added a speaker (Ada Lovelace) and sorted the bullets alphabetically by first name.
- `b.md`: turned the bullets into a Markdown table `| Name | Email | Organizer |`, filled in organizer initials, and changed the formula `=COUNT(/ul[id='speakers']/li)` to `=COUNT(/table[id='speakers']/tbody/tr)`.

Write a script that merges the two edits and prints the resulting document: the speakers section must be a table in B's format containing every speaker from A **in A's order**, with Organizer values taken from B (blank for the speaker B never saw), and the budget formula must use the table path. Everything else stays as in the base document.

## Expected output

```
# PROGRAMMING CONFERENCE 2023

## Invited speakers

| Name | Email | Organizer |
|---|---|---|
| Ada Lovelace | lovelace@rsoc.ac.uk |  |
| Adele Goldberg | adele@xerox.com | TP |
| Betty Jean Jennings | betty@rand.com | JE |
| Margaret Hamilton | hamilton@mit.com | JE |

## Conference budget

Travel cost per speaker: $1200
Number of speakers: =COUNT(/table[id='speakers']/tbody/tr)
Travel expenses: =/dl/dd[0] * /dl/dd[1]
```

## Notes for study designers

- Stages: (1) a parser that accepts *either* representation (bullets or table rows, skipping the header and `|---|` separator); (2) merge keyed by email — the string step is `split(",", 1)` on `Name, email`; (3) render; (4) the formula rewrite is a one-line string replacement but participants must notice it.
- Variants: B also renamed a speaker (conflict → report it); A removed a speaker (union vs. A-wins semantics); merge three-way against `base.md` properly instead of assuming A's list is the superset; emit the table with aligned columns.
- Good for an *editing* tool because the target is a document diff the participant can eyeball.

## Example solution

```python
# Merge two divergent edits of a conference document: A added a speaker and
# sorted the bullet list; B refactored the list into a table (and updated a
# formula path). Result: A's speakers and order, B's format and organizers.

def parse_speakers(lines):
    """Return ([{"name","email","organizer"}...], is_table) from the
    'Invited speakers' section, whether it is a bullet list or a table."""
    speakers, is_table = [], False
    for line in lines:
        if line.startswith("- "):
            name, email = line[2:].split(",", 1)
            speakers.append({"name": name.strip(), "email": email.strip(), "organizer": ""})
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[0] in ("Name", "") or set(cells[0]) <= {"-"}:
                is_table = True
                continue
            speakers.append({"name": cells[0], "email": cells[1], "organizer": cells[2]})
    return speakers, is_table

def section(lines, heading):
    """Lines between `## heading` and the next `## `."""
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip() == heading
            continue
        if inside:
            out.append(line)
    return out

def merge(a_lines, b_lines):
    a_speakers, _ = parse_speakers(section(a_lines, "Invited speakers"))
    b_speakers, _ = parse_speakers(section(b_lines, "Invited speakers"))
    organizer = {s["email"]: s["organizer"] for s in b_speakers}
    merged = [dict(s, organizer=organizer.get(s["email"], "")) for s in a_speakers]  # A's order
    for s in b_speakers:                                   # anything only B has
        if s["email"] not in {m["email"] for m in merged}:
            merged.append(s)
    return merged

def render_table(speakers):
    rows = ["| Name | Email | Organizer |", "|---|---|---|"]
    rows += [f"| {s['name']} | {s['email']} | {s['organizer']} |" for s in speakers]
    return rows

def rewrite_formula(line):
    return line.replace("/ul[id='speakers']/li", "/table[id='speakers']/tbody/tr")

def render(base_lines, speakers):
    out, skipping = [], False
    for line in base_lines:
        if line.startswith("## "):
            skipping = line[3:].strip() == "Invited speakers"
            out.append(line)
            if skipping:
                out.append("")
                out += render_table(speakers)
                out.append("")
            continue
        if not skipping:
            out.append(rewrite_formula(line))
    return "\n".join(out)

if __name__ == "__main__":
    base = open("speaker-list-refactor.base.md").read().splitlines()
    a = open("speaker-list-refactor.a.md").read().splitlines()
    b = open("speaker-list-refactor.b.md").read().splitlines()
    print(render(base, merge(a, b)))
```
