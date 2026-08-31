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
