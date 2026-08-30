# Recipe scaler

- **Source:** synthetic — no specific benchmark or paper. Scaling ingredient lines is a very common everyday scripting/app task (recipe sites, "servings" sliders) and appears as a beginner exercise in many Python tutorials, but we wrote this recipe and spec ourselves.
- **Tags:** parsing numbers/mixed fractions from text · small unit vocabulary · structured record → arithmetic → re-rendering · pluralisation
- **Data:** `recipe-scaler.input.txt` — a title line + 10 ingredient lines, including two lines without a quantity.
- **Stdlib used in solution:** `fractions` (only for exact arithmetic; a `(numerator, denominator)` pair with `math.gcd` works too)
- **Difficulty:** medium
- **Shape:** text lines → list of dicts → scaled → text lines (full round trip)

## Task description (as given to participant)

`recipe-scaler.input.txt` is a recipe: a title line `Buttermilk Pancakes (serves 4)`, a blank line, then one ingredient per line such as

```
2 1/2 cups all-purpose flour
1/4 tsp salt
2 eggs
a pinch of nutmeg
butter for the pan
```

Write a script that prints the same recipe scaled by 1.5 (to serve 6):

- Parse each ingredient into a quantity (which may be a whole number, a fraction like `1/4`, or a mixed number like `2 1/2`), an optional unit (`cup`, `cups`, `tbsp`, `tsp`, …) and the ingredient name (everything else, verbatim).
- Multiply the quantity by 1.5 and print it back as a mixed fraction in lowest terms (`2 1/2` → `3 3/4`, `1/4` → `3/8`, `2` → `3`).
- Lines with no leading quantity (`a pinch of nutmeg`) are printed unchanged.
- Fix the unit's plural: `1/2 cup` → `3/4 cup`, but `2 cups` → `3 cups`.
- Update the `serves N` in the title.

## Expected output

```
Buttermilk Pancakes (serves 6)

3 3/4 cups all-purpose flour
3 tbsp sugar
2 1/4 tsp baking powder
3/8 tsp salt
3 eggs
3 cups buttermilk
4 1/2 tbsp unsalted butter, melted
3/4 cup blueberries (optional)
a pinch of nutmeg
butter for the pan
```

## Notes for study designers

- Round-trip shape: string → record → number crunching → string. The tricky part is on both ends: recognising `2 1/2` as *one* quantity (two tokens), and rendering `15/4` back as `3 3/4`.
- Ingredients without a quantity or without a unit (`2 eggs`) exercise the optional-field logic; `unsalted butter, melted` and `blueberries (optional)` check that the name is kept verbatim.
- Good follow-up edits: scale by an arbitrary factor from the command line; convert `tbsp` ↔ `tsp` when a scaled quantity gets awkward (`4 1/2 tbsp` → `1/4 cup + 1/2 tbsp`); handle ranges (`2-3 cloves garlic`); emit the parsed records as JSON.
- If floats are used instead of fractions, `1/4 × 1.5 = 0.375` must still render as `3/8` — a natural place for a rounding bug.

## Example solution

```python
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

if __name__ == "__main__":
    FACTOR = Fraction(3, 2)
    with open("recipe-scaler.input.txt") as f:
        lines = [l.rstrip("\n") for l in f]

    title, ingredients = lines[0], [l for l in lines[1:] if l.strip()]
    print(title.replace("serves 4", f"serves {int(4 * FACTOR)}"))
    print()
    for line in ingredients:
        print(format_line(parse_line(line), FACTOR))
```
