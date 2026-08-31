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

base = open("speaker-list-refactor.base.md").read().splitlines()
a = open("speaker-list-refactor.a.md").read().splitlines()
b = open("speaker-list-refactor.b.md").read().splitlines()
print(render(base, merge(a, b)))
