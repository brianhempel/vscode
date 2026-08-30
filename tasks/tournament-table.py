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

if __name__ == "__main__":
    with open("tournament-table.input.txt") as f:
        lines = f.readlines()
    print(render(tally(lines)))
