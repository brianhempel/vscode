# JSON abacus

- **Source:** Paraphrased from Advent of Code 2015, day 12 ("JSAbacusFramework.io") — https://adventofcode.com/2015/day/12. AoC asks that puzzle text and inputs not be copied, so the wording is our own and `json-abacus.input.json` is a small synthetic document we wrote. AoC puzzles are an established source for program-synthesis and LLM benchmarks (e.g. several PSB2 problems come from AoC), which supports ecological validity.
- **Tags:** recursive traversal of arbitrary nested JSON · type dispatch (`dict` / `list` / number / string) · conditional pruning of subtrees
- **Data:** `json-abacus.input.json` — one document, ~15 lines, nesting depth 4.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium (~10–15 minutes)
- **Shape:** nested JSON → number. Pure nested-data task with a small string-comparison twist.

## Task description (as given to participant)

`json-abacus.input.json` is a JSON document containing arbitrarily nested objects and arrays, with numbers, strings and other objects/arrays inside them.

1. Print the sum of **every number** anywhere in the document, at any depth. Strings that look like numbers (e.g. `"12"`) do **not** count; only real JSON numbers do.
2. Print the same sum, but this time **ignore any object that has any property whose value is the string `"red"`** — ignore the whole object, including everything nested inside it. This applies to objects only; an array containing `"red"` is unaffected, and an object whose value is `["red", "vip"]` (a list, not the string) is also unaffected.

## Expected output

```
Sum of all numbers: 3211.5
Sum ignoring 'red' objects: 80.5
```

## Notes for study designers

- A compact test of recursion over heterogeneous nested data: the whole solution is one function with a type-dispatch chain.
- Traps built into the data: a string `"12"` and `"6"` (must not count), a float, `"red"` as a *list element* (does not disqualify), `"red"` as a value inside an object nested inside a list (that inner object is skipped but its siblings are not), and a `"red"` object at the top of a subtree so the whole subtree (`bob`: 25 + 1000 + 2000) disappears in part 2.
- Good edits: add a third variant that ignores objects with a *key* named `"red"`; count how many numbers were skipped; also collect the *paths* (`accounts.alice.history[2]`) of every number found — this turns the task into string-building from nested structure.
- Python gotcha worth noting in a "fix" variant: `bool` is a subclass of `int`, so `true` would be counted as 1 without the explicit check.

## Example solution

```python
# JSON abacus: sum every number in a nested JSON document, then again while
# ignoring any object that has a value equal to "red".
import json

def total(node, skip_red=False):
    if isinstance(node, bool):          # bool is a subclass of int; don't count it
        return 0
    if isinstance(node, (int, float)):
        return node
    if isinstance(node, list):
        return sum(total(item, skip_red) for item in node)
    if isinstance(node, dict):
        if skip_red and "red" in node.values():
            return 0
        return sum(total(value, skip_red) for value in node.values())
    return 0                            # strings (even "12") and None count as zero

if __name__ == "__main__":
    with open("json-abacus.input.json") as f:
        doc = json.load(f)
    print(f"Sum of all numbers: {total(doc)}")
    print(f"Sum ignoring 'red' objects: {total(doc, skip_red=True)}")
```
