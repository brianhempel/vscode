# Wildcard-style customisation of a listings page: parse the price and rating
# strings, filter by rating, sort by price, join a walk score, and mark
# favourites.
import json

def parse_price(text):
    """'$1,234 / night' or '$98' -> 1234"""
    amount = text.split("/")[0].strip()          # drop '/ night'
    return int(amount.lstrip("$").replace(",", ""))

def parse_rating(text):
    """'4.87 (213)' -> (4.87, 213); 'New' -> (None, 0)"""
    if text.strip() == "New":
        return None, 0
    score, count = text.split(" ", 1)
    return float(score), int(count.strip("()"))

def enrich(listings, walkscores):
    rows = []
    for l in listings:
        rating, reviews = parse_rating(l["rating"])
        rows.append({
            "name": l["name"],
            "price": parse_price(l["price"]),
            "rating": rating,
            "reviews": reviews,
            "neighborhood": l["neighborhood"],
            "walkscore": walkscores.get(l["neighborhood"]),
        })
    return rows

def table(rows):
    out = [f"{'Listing':<28}{'Price':>6}  {'Rating':<12}{'Walk':>5}  Neighborhood"]
    for r in rows:
        rating = f"{r['rating']:.2f} ({r['reviews']})" if r["rating"] is not None else "New"
        out.append(f"{r['name']:<28}{'$' + str(r['price']):>6}  {rating:<12}{r['walkscore']:>5}  {r['neighborhood']}")
    return "\n".join(out)

if __name__ == "__main__":
    with open("wildcard-listings.input.json") as f:
        listings = json.load(f)
    with open("wildcard-listings.walkscore.json") as f:
        walkscores = json.load(f)

    rows = enrich(listings, walkscores)
    good = [r for r in rows if r["rating"] is not None and r["rating"] > 4.5]
    good.sort(key=lambda r: r["price"])
    print(f"Rated above 4.5, cheapest first ({len(good)} of {len(rows)}):")
    print(table(good))

    favourites = {"Quiet garden cottage", "Victorian with garden", "Brand new condo"}
    print()
    print("Favourites:")
    print(table([r for r in rows if r["name"] in favourites]))
