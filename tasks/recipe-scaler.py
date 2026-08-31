# Recipe scaler: parse "2 1/2 cups flour" lines into (quantity, unit, name), scale, and print again.
from fractions import Fraction

UNITS = {"cup", "cups", "tbsp", "tsp", "oz", "lb", "g", "ml", "pinch", "clove", "cloves"}

def parse_quantity(tokens):
    """Consume leading number tokens ('2', '1/2', '2 1/2'). Returns (Fraction or None, remaining tokens)."""
    qty = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isdigit():
            value = Fraction(int(tok))
        elif "/" in tok and all(p.isdigit() for p in tok.split("/", 1)):
            num, den = tok.split("/")
            value = Fraction(int(num), int(den))
        else:
            break
        qty = value if qty is None else qty + value
        i += 1
    return qty, tokens[i:]

def parse_line(line):
    """'2 1/2 cups all-purpose flour' -> {'qty': Fraction(5, 2), 'unit': 'cups', 'name': 'all-purpose flour'}"""
    tokens = line.split()
    qty, rest = parse_quantity(tokens)
    unit = ""
    if rest and rest[0].lower() in UNITS:
        unit = rest[0]
        rest = rest[1:]
    return {"qty": qty, "unit": unit, "name": " ".join(rest)}

def format_quantity(q):
    """Fraction(15, 4) -> '3 3/4'; Fraction(3) -> '3'."""
    whole, frac = divmod(q.numerator, q.denominator)
    parts = []
    if whole:
        parts.append(str(whole))
    if frac:
        parts.append(f"{frac}/{q.denominator}")
    return " ".join(parts) if parts else "0"

def pluralise(unit, qty):
    if unit == "cup" and qty > 1:
        return "cups"
    if unit == "cups" and qty <= 1:
        return "cup"
    return unit

def format_line(item, factor):
    if item["qty"] is None:                      # "a pinch of nutmeg", "butter for the pan"
        return item["name"] if not item["unit"] else f"{item['unit']} {item['name']}"
    qty = item["qty"] * factor
    unit = pluralise(item["unit"], qty)
    return " ".join(p for p in (format_quantity(qty), unit, item["name"]) if p)

FACTOR = Fraction(3, 2)
with open("recipe-scaler.input.txt") as f:
    lines = [l.rstrip("\n") for l in f]

title, ingredients = lines[0], [l for l in lines[1:] if l.strip()]
print(title.replace("serves 4", f"serves {int(4 * FACTOR)}"))
print()
for line in ingredients:
    print(format_line(parse_line(line), FACTOR))
