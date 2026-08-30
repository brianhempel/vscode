# Vegemite: real-estate walkability mashup

- **Source:** James Lin, Jeffrey Wong, Jeffrey Nichols, Allen Cypher, Tessa Lau, "End-User Programming of Mashups with Vegemite", IUI 2009 — https://doi.org/10.1145/1502650.1502667. User-study task 1, "Real Estate Walkability": *for all houses for sale in ZIP 95003 with asking prices between $1,750,000 and $2,000,000, find their Walk Score* (originally by scraping mercurynews.com/realestate and walkscore.com through the CoScripter/Vegemite browser extension). Here both sites are replaced by small local JSON files with synthetic data; the joining problem — addresses written differently on the two sites — is preserved.
- **Tags:** JSON lists of dicts · filter by parsed price string · address normalisation (case, abbreviations, trailing city/state) · join via normalised key · sorted table rendering
- **Data:** `vegemite-walkability.input.json` — 9 listings; `vegemite-walkability.walkscore.json` — mock Walk Score API keyed by normalised address.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium
- **Shape:** JSON → filtered list → string normalisation → dict lookup → table

## Task description (as given to participant)

`vegemite-walkability.input.json` is a list of houses for sale (`address`, `city`, `zip`, `price` as a string like `$1,850,000`). `vegemite-walkability.walkscore.json` is the response of a Walk Score service: a dict from a *normalised* street address (upper-case, no punctuation, street types abbreviated: `450 SEACLIFF DR`) to `{"walkscore": …, "description": …}`.

Print a table of every listing in ZIP `95003` with a price between $1,750,000 and $2,000,000 inclusive, with its Walk Score and description, sorted by Walk Score descending. Addresses in the listings are written inconsistently (`3300 Soquel Avenue`, `450 SEACLIFF DRIVE, APTOS CA`, `12 Redwood Dr.`), so you must normalise them before looking them up; print `no score found` if an address is not in the service.

## Expected output

```
Address                             Price  Walk  Description
3300 Soquel Avenue             $1,799,000    78  Very Walkable
901 Rio Del Mar Blvd           $1,999,999    72  Very Walkable
12 Redwood Dr.                 $1,850,000    41  Car-Dependent
15 CABRILLO ST.                $1,750,000    36  Car-Dependent
88 Valencia Road               $1,825,000    19  Car-Dependent
```

## Notes for study designers

- Stages: parse price strings → filter → normalise address strings (the pattern-detection step: strip `, CITY ST`, remove dots, map `AVENUE→AVE` etc.) → dict join → sort/format. Data and string work alternate, which is the target profile.
- Deliberate wrinkles: `450 SEACLIFF DRIVE, APTOS CA` is over budget *and* has a city suffix; `901 Rio Del Mar Blvd` is $1 under the limit; `680 University Ave` matches the score table but is in the wrong ZIP.
- Edit-task variants: start with a script that joins on the raw address (most rows show `no score found`), or one that compares `price` strings lexicographically; then ask to add the Vegemite study's second task (driving distance from a fixed home address, another mock table).
- The original study used live sites; if you want the URL-fetching variant, the Walk Score API is real (needs a key) — the local JSON keeps the task offline.

## Example solution

```python
# "Real Estate Walkability" mashup: filter listings by ZIP and price, then
# join each address to a (mock) Walk Score service keyed by a normalised
# street address.
import json

ZIP, LOW, HIGH = "95003", 1_750_000, 2_000_000
ABBREVIATIONS = {"AVENUE": "AVE", "STREET": "ST", "DRIVE": "DR",
                 "ROAD": "RD", "BOULEVARD": "BLVD", "LANE": "LN"}

def parse_price(s):
    return int(s.replace("$", "").replace(",", ""))

def normalise_address(s):
    """'450 SEACLIFF DRIVE, APTOS CA' -> '450 SEACLIFF DR'."""
    street = s.split(",")[0]                       # drop city/state suffix
    words = street.upper().replace(".", "").split()
    return " ".join(ABBREVIATIONS.get(w, w) for w in words)

if __name__ == "__main__":
    with open("vegemite-walkability.input.json") as f:
        listings = json.load(f)
    with open("vegemite-walkability.walkscore.json") as f:
        walkscore = json.load(f)

    selected = [l for l in listings
                if l["zip"] == ZIP and LOW <= parse_price(l["price"]) <= HIGH]
    rows = []
    for l in selected:
        key = normalise_address(l["address"])
        ws = walkscore.get(key)
        rows.append((ws["walkscore"] if ws else -1, l["address"], l["price"],
                     ws["description"] if ws else "no score found"))
    rows.sort(key=lambda r: -r[0])

    print(f"{'Address':<30} {'Price':>10}  {'Walk':>4}  Description")
    for score, address, price, desc in rows:
        print(f"{address:<30} {price:>10}  {score:>4}  {desc}")
```
