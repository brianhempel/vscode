# Top-rated restaurants with driving times and a map URL

- **Source:** Kerry Shih-Ping Chang, *Using Web Services and Creating Interactive Web Applications in Spreadsheet Programs* (Gneiss), PhD thesis, CMU HCII — ch. 3 §3.3 usage scenario (Yelp restaurant search API + Google Directions API, "a popular task frequently used in prior literature") and §3.5.1 "City trip planner with a map" (Google Static Maps markers); see also Chang & Myers, "Creating Interactive Web Data Applications with Spreadsheets", UIST 2014, https://doi.org/10.1145/2642918.2647371 . Gneiss did this against the live web services; the data here is **synthetic** JSON in the shape of a Yelp business-search response and a mock directions lookup. A live-URL variant of the task is possible with `urllib` and an API key.
- **Tags:** nested JSON · multi-key sort · dict lookup by string key · URL string composition · fixed-width table
- **Data:** `gneiss-restaurants-route.input.json` (8 businesses, Yelp-style) and `gneiss-restaurants-route.directions.json` (mock directions: origin + 7 routes). Entirely synthetic: restaurant names, addresses, ratings and review snippets are invented (no real businesses, so no fabricated reviews are attached to real places).
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium
- **Shape:** nested JSON → sorted slice → joined table → composed URL string

## Task description (as given to participant)

`gneiss-restaurants-route.input.json` is the response of a restaurant-search web service (a list under `businesses`, each with `name`, `rating`, `review_count`, `location.address1`, `coordinates.latitude/longitude`, and a `reviews` list). `gneiss-restaurants-route.directions.json` is a mock directions service: `origin` and a `routes` dict mapping a destination street address to `{duration_text, duration_seconds}`.

1. Select the **top 5** restaurants by `rating` (ties broken by `review_count`, higher first) and label them A–E.
2. Print a table with label, name, rating, review count, address and the driving time from the origin (`n/a` if the directions service has no route for that address).
3. Build the URL of a static map showing all five: start from `https://maps.googleapis.com/maps/api/staticmap?size=600x400` and append, for each restaurant, `&markers=label:<letter>|<latitude>,<longitude>`. Print the URL.

## Expected output

```
Origin: 5000 Forbes Ave, Pittsburgh
  Restaurant                  Rating  Reviews  Address                  Drive
A Asado Alley                    4.5     1105  77 Coal Wharf Ln       16 mins
B Butler Street Garden           4.5      498  6101 Hazel Ct          15 mins
C Pierogi Parlor                 4.5      340  2211 Lorimer Ave       11 mins
D Steel City Sandwich Co.        4.0      812  410 Rivergate St       14 mins
E Ellsworth Noodle Bar           4.0      623  3805 Amberson Way       7 mins

Static map URL:
https://maps.googleapis.com/maps/api/staticmap?size=600x400&markers=label:A|40.4431,-80.0017&markers=label:B|40.4795,-79.9548&markers=label:C|40.4657,-79.9457&markers=label:D|40.4517,-79.9856&markers=label:E|40.4527,-79.9316
```

## Notes for study designers

- This is the thesis's ch. 3 usage scenario (Yelp search → sort/filter top 5 → Google Directions per row via autofill) plus the §3.5.1 "city trip planner" whose marker string is literally the spreadsheet formula `CONCATENATE("&markers=label:", F1, "|", D1, ",", E1)`. Gneiss called the live APIs; here both responses are local JSON so no keys are needed. A URL variant is easy: fetch `https://api.yelp.com/v3/businesses/search?term=...` with `urllib` and an API key (see also `sculpin-artic-gallery` for a keyless live API).
- Shape: nested JSON → sort/slice → dict lookup by a string key (address) → *string composition* of a URL from nested numeric fields. The address lookup is a small "join on a string" and one address (`221 Schenley Dr`) is shared by two businesses — a quiet trap if you index the other way round.
- Extensions: add the first review snippet to each row; compute straight-line distance from lat/lng instead of using the directions file; mark restaurants with an `x` column to include/exclude from the map, as in the thesis.

## Example solution

```python
# Top-5 rated restaurants from a Yelp-style search response, driving time
# from a fixed origin (mock Directions response), and a Static Maps URL with
# one marker per restaurant.
import json

with open("gneiss-restaurants-route.input.json") as f:
    businesses = json.load(f)["businesses"]
with open("gneiss-restaurants-route.directions.json") as f:
    directions = json.load(f)

# Sort by rating desc, then review_count desc; keep the first five.
top5 = sorted(businesses, key=lambda b: (-b["rating"], -b["review_count"]))[:5]

print(f"Origin: {directions['origin']}")
print(f"{'':2}{'Restaurant':<28}{'Rating':>6}{'Reviews':>9}  {'Address':<22}{'Drive':>8}")
markers = ""
for letter, b in zip("ABCDE", top5):
    address = b["location"]["address1"]
    route = directions["routes"].get(address)
    drive = route["duration_text"] if route else "n/a"
    print(f"{letter:<2}{b['name']:<28}{b['rating']:>6}{b['review_count']:>9}  {address:<22}{drive:>8}")
    lat, lng = b["coordinates"]["latitude"], b["coordinates"]["longitude"]
    # Same shape as the spreadsheet formula in the thesis:
    #   CONCATENATE("&markers=label:", F1, "|", D1, ",", E1)
    markers += f"&markers=label:{letter}|{lat},{lng}"

url = "https://maps.googleapis.com/maps/api/staticmap?size=600x400" + markers
print()
print("Static map URL:")
print(url)
```
