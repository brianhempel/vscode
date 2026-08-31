# Crate stacks

- **Source:** Paraphrased from Advent of Code 2022, day 5 ("Supply Stacks", https://adventofcode.com/2022/day/5). AoC's About page asks that puzzle text and inputs not be copied, so the description is rewritten in our own words and the diagram/instructions are a small synthetic input we generated. AoC puzzles are used as a problem source in the PSB2 program-synthesis benchmark (Helmuth & Kelly, GECCO 2021) and in several LLM code-generation benchmarks.
- **Tags:** fixed-column text parsing · list of lists (stacks) · instruction parsing · simulation · rendering
- **Data:** `crate-stacks.input.txt` — a 4-column, 3-row crate diagram plus 6 move instructions.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** 2-D ASCII string → list of lists → simulate → string

## Task description (as given to participant)

`crate-stacks.input.txt` starts with a picture of some stacks of crates, drawn with the crate letters in square brackets and a line of stack numbers underneath:

```
    [D]        
[N] [C]     [T]
[Z] [M] [P] [Q]
 1   2   3   4 
```

Crate letters are always at character positions 1, 5, 9, ... of each line (the same columns as the digits on the number line). After a blank line come instructions of the form `move 3 from 1 to 3`, meaning "take 3 crates off the top of stack 1 and put them on stack 3".

Write a script that parses the diagram into one list per stack (bottom to top), parses the instructions, and then:

- **Stage A:** applies every instruction moving *one crate at a time* (so moving 3 crates reverses their order), and prints the final stacks and the string of top crates.
- **Stage B:** applies every instruction moving *all the crates at once* (order preserved), and prints the same.

Note that in the picture, a short stack has trailing spaces (or the line is simply shorter), so your parser must not assume every line is full width.

## Expected output

```
Initial stacks (bottom -> top):
stack 1: Z N
stack 2: M C D
stack 3: P
stack 4: Q T

Stage A (one crate at a time):
stack 1: C
stack 2: M
stack 3: P D N Z T
stack 4: Q
Top crates: CMTQ

Stage B (several crates at once):
stack 1: M
stack 2: C
stack 3: P Z N D Q
stack 4: T
Top crates: MCQT
```

## Notes for study designers

- This is not a "data processing" task in the tabular sense: it is parsing a picture by character position, then simulating. Nice for showing whether the tool helps with positional string indexing (`row[1 + 4*i]`).
- Natural stages: (1) split the file at the blank line; (2) read the diagram bottom-up into stacks; (3) parse `move N from A to B` by `split()`; (4) simulate with list slicing; (5) render.
- Gotchas: rows shorter than the widest row (index out of range); 1-based stack numbers in the instructions; forgetting to copy stacks before the second simulation (the two stages should start from the same initial state).
- Variants: ask for a rendered diagram (in the original bracket format) after each move; add a `swap A B` instruction.

## Example solution

```python
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
```
