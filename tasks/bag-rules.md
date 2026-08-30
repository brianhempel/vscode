# Bag containment rules

- **Source:** Paraphrased from Advent of Code 2020, day 7 ("Handy Haversacks") — https://adventofcode.com/2020/day/7. AoC asks that puzzle text and inputs not be copied, so the wording is our own and `bag-rules.input.txt` is a small synthetic rule set we wrote (it follows the puzzle's grammar). AoC puzzles are an established source for program-synthesis and LLM benchmarks (e.g. several PSB2 problems come from AoC), which supports ecological validity.
- **Tags:** English-like sentence parsing (split on fixed phrases, strip plural suffixes) · dict of dicts (graph) · recursion / memoisation · two queries over the same structure
- **Data:** `bag-rules.input.txt` — 10 rules.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium (~20–25 minutes; the parsing is fiddly, the recursion is short)
- **Shape:** sentences → nested dict → recursive queries → numbers/lists

## Task description (as given to participant)

`bag-rules.input.txt` describes which coloured bags must be packed inside which other bags, one rule per line:

```
light red bags contain 1 bright white bag, 2 muted yellow bags.
bright white bags contain 1 shiny gold bag.
faded blue bags contain no other bags.
```

Note the singular/plural (`bag`/`bags`), the trailing full stop, and the special phrase `no other bags`. Colours are always two words.

1. Parse the rules into a dictionary mapping each outer colour to a dictionary of `inner colour → count`.
2. **Query A:** how many different bag colours can *eventually* contain a `shiny gold` bag (directly or through any number of intermediate bags)? Print the count and the sorted list of colours.
3. **Query B:** how many individual bags must a single `shiny gold` bag contain in total, counting bags at every level?

## Expected output

```
Rules: 10
Colours that can eventually contain shiny gold: 5
  bright white
  dark orange
  light red
  muted yellow
  posh teal
Bags inside one shiny gold bag: 32
```

## Notes for study designers

- Natural stages: (1) split each line on `" bags contain "`, strip `"."`; (2) split the contents on `", "`, then split off the leading number, then remove `" bag"`/`" bags"` — three small pattern-detection steps; (3) build the nested dict; (4) two recursive functions.
- Query A is "walk the graph upwards" (or: for each colour, can it reach the target?) and Query B is a weighted recursive sum; participants often get `n * (1 + inside)` wrong as `n * inside` — an easy targeted "fix the script" variant.
- Good edits: add a rule that creates a second level of nesting; ask for the *list* of bags with counts inside shiny gold instead of a total; invert the dict (inner → outers) explicitly as an intermediate step.
- The rule grammar is regular enough for a regex, but the split-based parse is shown to stay within plain string methods.

## Example solution

```python
# Bag rules: parse "X bags contain N Y bags, M Z bags." into a nested dict and query it.

def parse_rule(line):
    outer, inner = line.strip().rstrip(".").split(" bags contain ")
    contents = {}
    if inner != "no other bags":
        for part in inner.split(", "):
            count, colour = part.split(" ", 1)
            colour = colour.replace(" bags", "").replace(" bag", "")
            contents[colour] = int(count)
    return outer, contents

def parse_rules(lines):
    return dict(parse_rule(line) for line in lines if line.strip())

def can_contain(rules, outer, target, memo=None):
    """True if `outer` can (eventually) hold a `target` bag."""
    memo = {} if memo is None else memo
    if outer in memo:
        return memo[outer]
    result = any(inner == target or can_contain(rules, inner, target, memo)
                 for inner in rules[outer])
    memo[outer] = result
    return result

def bags_inside(rules, colour):
    """Total number of bags a `colour` bag must contain."""
    return sum(n * (1 + bags_inside(rules, inner)) for inner, n in rules[colour].items())

if __name__ == "__main__":
    with open("bag-rules.input.txt") as f:
        rules = parse_rules(f.readlines())

    print(f"Rules: {len(rules)}")
    holders = sorted(c for c in rules if can_contain(rules, c, "shiny gold"))
    print(f"Colours that can eventually contain shiny gold: {len(holders)}")
    for c in holders:
        print(f"  {c}")
    print(f"Bags inside one shiny gold bag: {bags_inside(rules, 'shiny gold')}")
```
