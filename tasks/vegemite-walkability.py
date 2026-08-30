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
