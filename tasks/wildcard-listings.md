# Customising a listings page: price/rating parsing, sort, filter, join

- **Source:** Geoffrey Litt & Daniel Jackson, "Wildcard: Spreadsheet-Driven Customization of Web Applications", Onward! 2020, https://doi.org/10.1145/3426428.3426914 (also the follow-up "End-user software customization by direct manipulation of tabular data", Onward! 2020). Their headline example: Airbnb removed sort-by-price in 2012, so a user opens the page's search results as a spreadsheet, sorts by price, filters to ratings above 4.5, and joins a Walk Score column via a formula; a second example collects favourites with a row action. Listings and walk scores here are synthetic.
- **Tags:** parsing display strings (`$1,234 / night`, `4.87 (213)`, `New`) · None handling · filter + sort · join on a key · fixed-width table rendering · membership filter
- **Data:** `wildcard-listings.input.json` (10 listings) and `wildcard-listings.walkscore.json` (neighbourhood → score).
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium
- **Shape:** list of dicts with display strings → parsed records → filtered/sorted/joined → text table

## Task description (as given to participant)

`wildcard-listings.input.json` is a list of accommodation listings scraped from a web page, so the numbers are still *display strings*:

```
{"name": "Sunny loft near the park", "price": "$1,234 / night", "rating": "4.87 (213)",
 "neighborhood": "Mission", "amenities": ["Wifi", "Kitchen", "Washer"]}
```

`price` is either `$98` or `$1,234 / night`; `rating` is `<score> (<review count>)` or the word `New` for listings with no reviews yet. `wildcard-listings.walkscore.json` maps neighbourhood names to a walk score.

Write a script that:

1. Parses each listing's price into an integer and its rating into a score and review count (`New` → no score).
2. Prints the listings with a rating above 4.5, cheapest first, as a table with columns Listing, Price, Rating (as `4.87 (213)`, two decimals), Walk (score from the second file) and Neighborhood, under the heading `Rated above 4.5, cheapest first (<k> of <n>):`.
3. Prints a second table headed `Favourites:` containing only the listings named "Quiet garden cottage", "Victorian with garden" and "Brand new condo", in the original page order.

## Expected output

```
Rated above 4.5, cheapest first (7 of 10):
Listing                      Price  Rating       Walk  Neighborhood
Tiny room, big heart           $65  4.58 (9)       84  Dogpatch
Cozy studio                    $98  4.52 (41)      78  Sunset
Quiet garden cottage          $160  4.76 (305)     78  Sunset
Victorian with garden         $310  4.95 (88)      93  Haight
Family home, 3 bedrooms       $420  4.68 (57)      93  Haight
Sunny loft near the park     $1234  4.87 (213)     97  Mission
Bay view penthouse           $2050  4.90 (12)      99  Nob Hill

Favourites:
Listing                      Price  Rating       Walk  Neighborhood
Victorian with garden         $310  4.95 (88)      93  Haight
Brand new condo               $205  New            95  SoMa
Quiet garden cottage          $160  4.76 (305)     78  Sunset
```

## Notes for study designers

- Stages: (1) two small string parsers with format variants; (2) filter where `None` must not compare; (3) sort numerically (a string sort puts `$98` after `$1234` — a good first-version bug); (4) join; (5) render; (6) membership filter.
- Extension ideas from the paper: add an "amenities contains Kitchen" filter; compute price per rating point; hide listings by regex on the name; a "snooze" annotation column (see `sculpin-todo-grouping`).
- Every bug here is visible in the output table, which suits a live-preview editing tool.

## Example solution

```python
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
```
