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

with open("cube-game.input.txt") as f:
    games = [parse_game(line) for line in f if line.strip()]

ok = [g for g in games if possible(g, LIMIT)]
print(f"Games: {len(games)}")
print(f"Possible with {LIMIT}: ids {[g['id'] for g in ok]}, sum = {sum(g['id'] for g in ok)}")
for g in games:
    m = max_per_colour(g)
    print(f"  Game {g['id']:>2}: min set {m} -> power {power(g)}")
print(f"Sum of powers: {sum(power(g) for g in games)}")
