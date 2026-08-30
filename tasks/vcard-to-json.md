# vCard address book → JSON

- **Source:** vCard 3.0, RFC 2426 — https://www.rfc-editor.org/rfc/rfc2426 (property/parameter syntax in §2 and §4; line folding in §2.6 / RFC 2425 §5.8.1). `.vcf` is the interchange format exported by Apple Contacts, Google Contacts, Outlook, and phones, so "turn my exported contacts into JSON/CSV" is a genuine end-user task. Contacts here are synthetic (example.com addresses, 555 numbers).
- **Tags:** line-oriented stateful parsing (BEGIN/END blocks) · unfolding continuation lines · `NAME;PARAM=a,b:value` splitting · `;`-separated structured values (`N:`, `ORG:`) · lists of dicts inside dicts · JSON output · filtering nested records
- **Data:** `vcard-to-json.input.vcf` — 38 lines, 4 contacts. Includes multi-valued `TYPE=` parameters, a `pref` flag, a folded `NOTE` line, and a contact with no `ORG`.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium
- **Shape:** string → nested records (dict with lists of dicts) → JSON string, then a query over the nested records

## Task description (as given to participant)

`vcard-to-json.input.vcf` is an exported address book in vCard 3.0 format. Each contact is enclosed in `BEGIN:VCARD` … `END:VCARD`. Each other line is a *property*:

```
NAME[;PARAM=value[,value...]]*:VALUE
```

e.g. `TEL;TYPE=cell,voice:+1-555-0101`. Some values are themselves `;`-separated: `N:Family;Given;Middle;Prefix;Suffix` and `ORG:Company;Department`. A line that begins with a single space is a continuation of the previous line (remove the space and glue it on).

Write a script that parses the file into a list of contact records shaped like

```
{"full_name": ..., "name": {"family":..., "given":..., "middle"?:..., "prefix"?:...},
 "phones": [{"type": ["cell","voice"], "number": "..."}], "emails": [{"type": [...], "address": "..."}],
 "org"?: ..., "department"?: ..., "title"?: ..., "url"?: ..., "note"?: ...}
```

(omit optional keys when absent; parameter values lowercased), prints each contact as one line of JSON, and then prints the names of everyone who has a `cell` phone number together with that number.

## Expected output

```
{"full_name": "Dr. John Q. Doe", "name": {"family": "Doe", "given": "John", "middle": "Quinlan", "prefix": "Dr."}, "phones": [{"type": ["work", "voice"], "number": "+1-555-0100"}, {"type": ["cell", "voice"], "number": "+1-555-0101"}], "emails": [{"type": ["work"], "address": "jdoe@example.com"}, {"type": ["home"], "address": "john.doe@example.net"}], "org": "Example Corp", "department": "Research", "title": "Staff Scientist", "note": "Prefers email. Available Tue/Thu afternoons for meetings."}
{"full_name": "Aiko Nakamura", "name": {"family": "Nakamura", "given": "Aiko"}, "phones": [{"type": ["cell"], "number": "+81-90-5555-0102"}], "emails": [{"type": ["work"], "address": "aiko@example.com"}], "org": "Example Corp", "department": "Design", "url": "https://aiko.example.com"}
{"full_name": "Chidi Okonkwo", "name": {"family": "Okonkwo", "given": "Chidi"}, "phones": [{"type": ["work", "voice", "pref"], "number": "+44 20 5555 0103"}, {"type": ["fax"], "number": "+44 20 5555 0104"}], "emails": [{"type": ["work"], "address": "c.okonkwo@bluebird.example"}], "org": "Bluebird Logistics"}
{"full_name": "Elena M. Petrov", "name": {"family": "Petrov", "given": "Elena", "middle": "Maria"}, "phones": [{"type": ["home"], "number": "+7 495 555 0105"}], "emails": [{"type": [], "address": "elena.petrov@example.org"}]}

Contacts with a cell phone:
  Dr. John Q. Doe: +1-555-0101
  Aiko Nakamura: +81-90-5555-0102
```

## Notes for study designers

- Three distinct string-splitting patterns in one small task: first `:` (property vs value), `;` in the property head (parameters), `,` inside a parameter, and `;` again inside `N:`/`ORG:` values — with different rules each time. Good for testing how a tool helps users keep them straight.
- The folded `NOTE` line is a small "pattern in strings" trap (whether the note reads "…afternoons for meetings." or "…afternoonsfor meetings.").
- Simpler variant: skip folding and `N:` structure, just `FN`/`TEL`/`EMAIL`. Harder variant: also write back out as CSV with one row per phone number, or emit vCard from the JSON (round trip).
- vCard 4.0 (RFC 6350) differs slightly (`TYPE="cell"` quoting); stick to 3.0 as in the data.

## Example solution

```python
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

if __name__ == "__main__":
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
```
