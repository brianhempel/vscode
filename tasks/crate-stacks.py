# Crate stacks: parse an ASCII stack diagram plus move instructions, then simulate.

def parse(text):
    diagram, instructions = text.split("\n\n", 1)
    rows = diagram.split("\n")
    number_line = rows[-1]
    n = len(number_line.split())
    # Crate letters sit at character positions 1, 5, 9, ... (column i -> 1 + 4*i).
    stacks = [[] for _ in range(n)]
    for row in reversed(rows[:-1]):          # bottom row first so stacks build upward
        for i in range(n):
            pos = 1 + 4 * i
            if pos < len(row) and row[pos] != " ":
                stacks[i].append(row[pos])
    moves = []
    for line in instructions.strip().split("\n"):
        words = line.split()                 # move N from A to B
        moves.append((int(words[1]), int(words[3]) - 1, int(words[5]) - 1))
    return stacks, moves

def simulate(stacks, moves, one_at_a_time):
    stacks = [s[:] for s in stacks]          # don't mutate the parsed input
    for count, src, dst in moves:
        lifted = stacks[src][-count:]
        del stacks[src][-count:]
        if one_at_a_time:
            lifted.reverse()                 # moving one by one reverses the order
        stacks[dst].extend(lifted)
    return stacks

def tops(stacks):
    return "".join(s[-1] if s else "-" for s in stacks)

def show(stacks):
    return "\n".join(f"stack {i + 1}: {' '.join(s) or '(empty)'}" for i, s in enumerate(stacks))

with open("crate-stacks.input.txt") as f:
    stacks, moves = parse(f.read())
print("Initial stacks (bottom -> top):")
print(show(stacks))
a = simulate(stacks, moves, one_at_a_time=True)
print("\nStage A (one crate at a time):")
print(show(a))
print("Top crates:", tops(a))
b = simulate(stacks, moves, one_at_a_time=False)
print("\nStage B (several crates at once):")
print(show(b))
print("Top crates:", tops(b))
