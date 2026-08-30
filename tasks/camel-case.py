# Camel case: convert kebab-case / snake_case identifiers to camelCase, and back.

def to_camel(identifier):
    # Treat both '-' and '_' as word separators.
    words = identifier.replace("_", "-").split("-")
    words = [w for w in words if w]  # drop empties from doubled separators
    if not words:
        return ""
    first, rest = words[0], words[1:]
    # First word keeps its original casing; the rest get a capital first letter.
    return first + "".join(w[0].upper() + w[1:] for w in rest)

def to_kebab(identifier):
    # Insert '-' before every uppercase letter, then lowercase everything.
    out = []
    for ch in identifier:
        if ch.isupper():
            out.append("-")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).strip("-")

if __name__ == "__main__":
    with open("camel-case.input.txt") as f:
        identifiers = [line.strip() for line in f if line.strip()]

    print("Stage 1: to camelCase")
    camels = []
    for ident in identifiers:
        camel = to_camel(ident)
        camels.append(camel)
        print(f"{ident:<26} -> {camel}")

    print()
    print("Stage 2: back to kebab-case")
    for camel in camels:
        print(f"{camel:<26} -> {to_kebab(camel)}")
