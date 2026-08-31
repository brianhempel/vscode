# Parse a vCard 3.0 (.vcf) address book into JSON records.
import json

def unfold(lines):
    """RFC 2426 line folding: a line starting with a space or tab continues
    the previous line (with the leading whitespace removed)."""
    out = []
    for line in lines:
        line = line.rstrip("\r\n")
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def parse_property(line):
    """'TEL;TYPE=cell,voice:+1-555-0101' ->
       ('TEL', {'TYPE': ['cell', 'voice']}, '+1-555-0101')"""
    head, value = line.split(":", 1)
    name, *raw_params = head.split(";")
    params = {}
    for p in raw_params:
        key, _, val = p.partition("=")
        params[key.upper()] = val.lower().split(",") if val else []
    return name.upper(), params, value

def parse_vcards(lines):
    cards, current = [], None
    for line in unfold(lines):
        if not line.strip():
            continue
        name, params, value = parse_property(line)
        if name == "BEGIN":
            current = {"full_name": None, "name": None, "phones": [], "emails": []}
        elif name == "END":
            cards.append(current)
            current = None
        elif name == "N":
            family, given, additional, prefix, suffix = (value.split(";") + [""] * 5)[:5]
            current["name"] = {"family": family, "given": given}
            if additional:
                current["name"]["middle"] = additional
            if prefix:
                current["name"]["prefix"] = prefix
        elif name == "FN":
            current["full_name"] = value
        elif name == "ORG":
            org, *units = value.split(";")
            current["org"] = org
            if units and units[0]:
                current["department"] = units[0]
        elif name == "TITLE":
            current["title"] = value
        elif name == "TEL":
            current["phones"].append({"type": params.get("TYPE", []), "number": value})
        elif name == "EMAIL":
            current["emails"].append({"type": params.get("TYPE", []), "address": value})
        elif name == "URL":
            current["url"] = value
        elif name == "NOTE":
            current["note"] = value
        # VERSION and anything unknown are ignored.
    return cards

with open("vcard-to-json.input.vcf") as f:
    contacts = parse_vcards(f.readlines())

for c in contacts:          # one compact JSON object per line
    print(json.dumps(c))
print()
print("Contacts with a cell phone:")
for c in contacts:
    cells = [p["number"] for p in c["phones"] if "cell" in p["type"]]
    if cells:
        print(f"  {c['full_name']}: {', '.join(cells)}")
