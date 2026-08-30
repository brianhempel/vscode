# Movie mashup: merge reviews into a nested theaters → movies table

- **Source:** Guiling Wang, Shaohua Yang, Yanbo Han et al., "Mashroom: End-User Mashup Programming Using Nested Tables", WWW 2009, https://doi.org/10.1145/1526709.1526806 — its "Newest Movie Information" scenario: theatre/showtime data from one service (a nested table *theaters → movies*), reviews from another (douban.com) looked up by title, where the review search returns *approximate* matches ("subjectID that matches the name approximately instead of the precise one") that must be filtered to the exact title. Data here is synthetic but keeps that shape and that problem.
- **Tags:** nested JSON (list inside list) · title normalisation (case, punctuation, `, The` suffix) · exact-match filtering of fuzzy search results · in-place enrichment of nested records · indented rendering + JSON lines
- **Data:** `mashroom-movies.input.json` (2 theatres × 3 movies) and `mashroom-movies.reviews.json` (search results per title: 1–3 candidates each, mostly near-misses).
- **Stdlib used in solution:** `json`
- **Difficulty:** medium
- **Shape:** nested structure + string matching → enriched nested structure → text and JSON

## Task description (as given to participant)

`mashroom-movies.input.json` lists cinemas, each with a nested list of movies and showtimes. `mashroom-movies.reviews.json` holds, for each movie title, the raw results of searching a review site for that title — a list of candidates with `title`, `rating` and `review`. Searches are fuzzy, so most candidates are *not* the movie ("The Dark Knight Rises", "Up in the Air", "Body Heat"); the right one may also be spelled differently ("Dark Knight, The", "UP", "Spirited Away.").

Write a script that, for every movie in every cinema, picks the candidate whose title is the *same movie* — compare titles after lower-casing, removing punctuation, collapsing whitespace, and moving a trailing `, The` to the front — and copies its `rating` and `review` into the movie record (`null` if there is no exact match). Then print:

1. Each cinema as `Name (District)` with its movies indented below, best-rated first, as `title  rating  showtimes` (`n/a` when unmatched).
2. A line `No exact review match: <cinema>: <title>, ...`.
3. One compact JSON line per merged movie record including the theatre name.

## Expected output

```
Grand Cinema (Haidian)
  The Dark Knight   9.2  14:00, 19:30
  Up                9.0  11:00, 15:15
  Amelie            n/a  21:00
Star Multiplex (Chaoyang)
  Spirited Away     9.3  10:30, 13:00, 16:45
  The Dark Knight   9.2  18:00
  Heat              n/a  22:15

No exact review match: Grand Cinema: Amelie, Star Multiplex: Heat

Merged records (one JSON line per movie):
{"theater": "Grand Cinema", "title": "The Dark Knight", "showtimes": ["14:00", "19:30"], "rating": 9.2, "review": "Ledger's Joker steals every scene."}
{"theater": "Grand Cinema", "title": "Up", "showtimes": ["11:00", "15:15"], "rating": 9.0, "review": "The first ten minutes."}
{"theater": "Grand Cinema", "title": "Amelie", "showtimes": ["21:00"], "rating": null, "review": null}
{"theater": "Star Multiplex", "title": "The Dark Knight", "showtimes": ["18:00"], "rating": 9.2, "review": "Ledger's Joker steals every scene."}
{"theater": "Star Multiplex", "title": "Spirited Away", "showtimes": ["10:30", "13:00", "16:45"], "rating": 9.3, "review": "A bathhouse for the gods."}
{"theater": "Star Multiplex", "title": "Heat", "showtimes": ["22:15"], "rating": null, "review": null}
```

## Notes for study designers

- The core string step is `normalise()`; participants typically discover the needed rules one at a time from the near-misses in the data: case (`UP`), punctuation (`Spirited Away.`), the `, The` inversion. `Amelie` vs `Amélie` deliberately stays unmatched — a natural extension is to strip accents (`unicodedata`), which then matches.
- Nested-data step: mutate records inside a list inside a list, then sort within each group — with `None` ratings that must sort last.
- Extensions from the paper: merge two theatre sources first (same movie at different cinemas), then attach reviews; export the merged table as CSV (one row per theatre×movie×showtime — an unnesting step).

## Example solution

```python
# Movie mashup: merge review search results into a nested theaters -> movies
# table, keeping only the candidate whose normalised title matches exactly.
import json

def normalise(title):
    """Lower-case, move a trailing ', The' to the front, drop punctuation and
    collapse whitespace so that 'Dark Knight, The' == 'The Dark Knight'."""
    t = title.strip().lower()
    if t.endswith(", the"):
        t = "the " + t[:-len(", the")]
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return " ".join(t.split())

def exact_match(title, candidates):
    wanted = normalise(title)
    hits = [c for c in candidates if normalise(c["title"]) == wanted]
    return hits[0] if hits else None

def merge(theaters, reviews):
    unmatched = []
    for theater in theaters:
        for movie in theater["movies"]:
            hit = exact_match(movie["title"], reviews.get(movie["title"], []))
            if hit:
                movie["rating"] = hit["rating"]
                movie["review"] = hit["review"]
            else:
                movie["rating"] = None
                movie["review"] = None
                unmatched.append((theater["name"], movie["title"]))
    return theaters, unmatched

if __name__ == "__main__":
    with open("mashroom-movies.input.json") as f:
        theaters = json.load(f)["theaters"]
    with open("mashroom-movies.reviews.json") as f:
        reviews = json.load(f)

    theaters, unmatched = merge(theaters, reviews)
    for theater in theaters:
        print(f"{theater['name']} ({theater['district']})")
        for m in sorted(theater["movies"], key=lambda m: -(m["rating"] or 0)):
            rating = f"{m['rating']:.1f}" if m["rating"] is not None else "n/a"
            print(f"  {m['title']:<16} {rating:>4}  {', '.join(m['showtimes'])}")
    print()
    print("No exact review match:", ", ".join(f"{t}: {m}" for t, m in unmatched) or "none")
    print()
    print("Merged records (one JSON line per movie):")
    for theater in theaters:
        for m in theater["movies"]:
            print(json.dumps({"theater": theater["name"], **m}, ensure_ascii=False))
```
