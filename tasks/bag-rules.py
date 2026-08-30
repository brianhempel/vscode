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
