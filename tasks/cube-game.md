# Cube game

- **Source:** Paraphrased from Advent of Code 2023, day 2 ("Cube Conundrum") — https://adventofcode.com/2023/day/2. AoC asks that puzzle text and inputs not be copied, so the wording is our own and `cube-game.input.txt` is a small synthetic input we wrote (it follows the puzzle's line format). AoC puzzles are an established source for program-synthesis and LLM benchmarks (e.g. several PSB2 problems come from AoC), which supports ecological validity.
- **Tags:** three-level string splitting (`: `, `; `, `, `) · list of dicts inside a list of records · per-key maximum · filter by limits · aggregate
- **Data:** `cube-game.input.txt` — 10 games.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium (~15 minutes)
- **Shape:** strings → nested list/dict structure → filter + reduce → formatted summary

## Task description (as given to participant)

Each line of `cube-game.input.txt` records one game. In a game, an unknown number of red, green and blue cubes are in a bag; several times a handful is drawn out, shown, and put back. Draws are separated by `;`, colours within a draw by `,`:

```
Game 1: 3 blue, 4 red; 1 red, 2 green, 6 blue; 2 green
```

1. Parse each line into a structure like `{"id": 1, "draws": [{"blue": 3, "red": 4}, {"red": 1, "green": 2, "blue": 6}, {"green": 2}]}`.
2. **Part A:** which games would have been *possible* if the bag contained only **12 red, 13 green and 14 blue** cubes? (A game is impossible if any single draw shows more of a colour than the bag holds.) Print the possible game ids and the sum of those ids.
3. **Part B:** for each game, find the *minimum* number of cubes of each colour that must have been in the bag (the maximum shown per colour across the draws). The "power" of that set is red × green × blue. Print each game's minimum set and power, and the sum of all powers.

## Expected output

```
Games: 10
Possible with {'red': 12, 'green': 13, 'blue': 14}: ids [1, 2, 5, 6, 7, 8, 9], sum = 38
  Game  1: min set {'red': 4, 'green': 2, 'blue': 6} -> power 48
  Game  2: min set {'red': 1, 'green': 3, 'blue': 4} -> power 12
  Game  3: min set {'red': 20, 'green': 13, 'blue': 6} -> power 1560
  Game  4: min set {'red': 14, 'green': 3, 'blue': 15} -> power 630
  Game  5: min set {'red': 6, 'green': 3, 'blue': 2} -> power 36
  Game  6: min set {'red': 12, 'green': 13, 'blue': 14} -> power 2184
  Game  7: min set {'red': 3, 'green': 2, 'blue': 7} -> power 42
  Game  8: min set {'red': 9, 'green': 11, 'blue': 10} -> power 990
  Game  9: min set {'red': 1, 'green': 1, 'blue': 1} -> power 1
  Game 10: min set {'red': 6, 'green': 2, 'blue': 16} -> power 192
Sum of powers: 5695
```

## Notes for study designers

- A textbook "string → nested data → computation" pipeline with three nested `split` calls, then a small per-record reduction. Draws omit colours that were not shown, so participants must handle missing keys (`dict.get` / defaults).
- Game 6 sits exactly on the limit (12/13/14) to test `<=` vs `<`; Game 9 has a draw of a single colour per draw.
- Good edits: change the limit; add a fourth colour; output a CSV `id,max_red,max_green,max_blue,power`; report the *draw index* that made a game impossible.
- Part A and Part B share the `max_per_colour` helper — a nice check of whether participants factor it out or duplicate the loop.

## Example solution

```python
# Cube game: parse "Game N: a red, b green; c blue ..." lines into nested data,
# then filter games by a bag limit and compute the minimum-set "power" of each.

LIMIT = {"red": 12, "green": 13, "blue": 14}

def parse_game(line):
    header, body = line.strip().split(": ")
    game_id = int(header.split(" ")[1])
    draws = []
    for draw in body.split("; "):
        counts = {}
        for item in draw.split(", "):
            n, colour = item.split(" ")
            counts[colour] = int(n)
        draws.append(counts)
    return {"id": game_id, "draws": draws}

def max_per_colour(game):
    best = {"red": 0, "green": 0, "blue": 0}
    for draw in game["draws"]:
        for colour, n in draw.items():
            best[colour] = max(best[colour], n)
    return best

def possible(game, limit):
    return all(n <= limit[c] for c, n in max_per_colour(game).items())

def power(game):
    m = max_per_colour(game)
    return m["red"] * m["green"] * m["blue"]

if __name__ == "__main__":
    with open("cube-game.input.txt") as f:
        games = [parse_game(line) for line in f if line.strip()]

    ok = [g for g in games if possible(g, LIMIT)]
    print(f"Games: {len(games)}")
    print(f"Possible with {LIMIT}: ids {[g['id'] for g in ok]}, sum = {sum(g['id'] for g in ok)}")
    for g in games:
        m = max_per_colour(g)
        print(f"  Game {g['id']:>2}: min set {m} -> power {power(g)}")
    print(f"Sum of powers: {sum(power(g) for g in games)}")
```
