# Tournament table

- **Source:** Exercism `tournament` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/tournament (problem-specifications repo, MIT licence). The exercise has been part of Exercism's Python track since ~2017 and is widely used in teaching.
- **Tags:** string parsing · dict-of-dicts tally · sorting by multiple keys · string formatting/rendering
- **Data:** `tournament-table.input.txt` — 8 lines (the canonical example from the spec, one extra line). Synthetic team names from the spec.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium (a good ~15‑minute task)
- **Shape:** string → nested dict → string (goes "both directions")

## Task description (as given to participant)

You have a text file where each line records one football match in the form

```
<home team>;<away team>;<result>
```

where `<result>` is `win` (home team won), `loss` (home team lost) or `draw`.
Write a script that reads `tournament-table.input.txt` and prints a league table like this:

```
Team                           | MP |  W |  D |  L |  P
Devastating Donkeys            |  5 |  3 |  1 |  1 | 10
...
```

- MP = matches played, W/D/L = wins/draws/losses, P = points (3 for a win, 1 for a draw, 0 for a loss).
- Sort by points descending; break ties by team name ascending.
- Ignore blank lines.
- The team column is padded to 31 characters; number columns are right-aligned to width 2.

## Expected output

```
Team                           | MP |  W |  D |  L |  P
Devastating Donkeys            |  5 |  3 |  1 |  1 | 10
Allegoric Alaskans             |  4 |  3 |  0 |  1 |  9
Blithering Badgers             |  4 |  1 |  0 |  3 |  3
Courageous Californians        |  3 |  0 |  1 |  2 |  1
```

## Notes for study designers

- Natural stages: (1) split each line on `;`; (2) build `team -> stats` dict, updating *both* teams per line; (3) sort by `(-points, name)`; (4) render with fixed-width formatting.
- Common gotcha: `loss` must be interpreted as a win for the *away* team — a nice small "edit this script" moment if you first give participants a version that forgets this.
- Easy extensions: add a goal-difference column parsed from a `2-1` score field; handle malformed lines; read from a CSV instead.
- Exercism supplies a `canonical-data.json` with ~12 test cases if you want more inputs.

## Example solution

```python
# Tournament table: parse "home;away;result" lines, tally points, print a table.

POINTS = {"win": 3, "draw": 1, "loss": 0}

def parse_line(line):
    home, away, result = line.strip().split(";")
    return home, away, result

def tally(lines):
    table = {}  # team -> {"MP", "W", "D", "L", "P"}
    def team(name):
        return table.setdefault(name, {"MP": 0, "W": 0, "D": 0, "L": 0, "P": 0})

    for line in lines:
        if not line.strip():
            continue
        home, away, result = parse_line(line)
        # Normalise so we always record from the winner's/loser's perspective.
        if result == "loss":
            home, away, result = away, home, "win"
        h, a = team(home), team(away)
        h["MP"] += 1
        a["MP"] += 1
        if result == "win":
            h["W"] += 1; a["L"] += 1
        else:  # draw
            h["D"] += 1; a["D"] += 1
        h["P"] += POINTS[result]
        a["P"] += POINTS["draw" if result == "draw" else "loss"]
    return table

def render(table):
    header = f"{'Team':<31}| MP |  W |  D |  L |  P"
    rows = [header]
    # Sort by points descending, then name ascending.
    for name, s in sorted(table.items(), key=lambda kv: (-kv[1]["P"], kv[0])):
        rows.append(f"{name:<31}| {s['MP']:>2} | {s['W']:>2} | {s['D']:>2} | {s['L']:>2} | {s['P']:>2}")
    return "\n".join(rows)

with open("tournament-table.input.txt") as f:
    lines = f.readlines()
print(render(tally(lines)))
```
