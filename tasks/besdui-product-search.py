# BESDUI / Berlin SPARQL Benchmark "explore" tasks over a nested product
# catalogue (products -> offers, reviews), written as plain list/dict filters.
import json

with open("besdui-product-search.input.json") as f:
    PRODUCTS = json.load(f)["products"]

def by_id(pid):
    return next(p for p in PRODUCTS if p["id"] == pid)

def labels(products):
    return ", ".join(p["label"] for p in products) or "(none)"

# T1: type + ALL given features + numeric property above a threshold
def t1(ptype, feats, min_num1):
    return [p for p in PRODUCTS if p["type"] == ptype
            and all(f in p["features"] for f in feats)
            and p["propertyNumeric1"] > min_num1]

# T2: type + ANY of the given features
def t2(ptype, feats, min_num1):
    return [p for p in PRODUCTS if p["type"] == ptype
            and any(f in p["features"] for f in feats)
            and p["propertyNumeric1"] > min_num1]

# T4: features that must be present, one that must be absent
def t4(ptype, must, must_not, min_num1):
    return [p for p in PRODUCTS if p["type"] == ptype
            and all(f in p["features"] for f in must)
            and must_not not in p["features"]
            and p["propertyNumeric1"] > min_num1]

# T6: products similar to a given one: >= 1 shared feature and
# propertyNumeric1 within +/- 100 of the reference product
def t6(pid, tolerance=100):
    ref = by_id(pid)
    return [p for p in PRODUCTS if p["id"] != pid
            and set(p["features"]) & set(ref["features"])
            and abs(p["propertyNumeric1"] - ref["propertyNumeric1"]) <= tolerance]

# T7: label contains a word (case-insensitive, whole word)
def t7(word):
    return [p for p in PRODUCTS if word.lower() in p["label"].lower().split()]

# T9: the N most recent reviews in a given language for a product
def t9(pid, language, n):
    reviews = [r for r in by_id(pid)["reviews"] if r["language"] == language]
    return sorted(reviews, key=lambda r: r["date"], reverse=True)[:n]

# T11: cheapest offer from a vendor in `country`, delivering within `max_days`,
# valid on `today` (ISO dates compare correctly as strings)
def t11(pid, country, max_days, today):
    offers = [o for o in by_id(pid)["offers"]
              if o["country"] == country and o["deliveryDays"] <= max_days
              and o["validFrom"] <= today <= o["validTo"]]
    return min(offers, key=lambda o: o["price"]) if offers else None

# T12: export the chosen offer into another system's schema
def t12(product, offer):
    return {
        "item": {"sku": f"BSBM-{product['id']:04d}", "name": product["label"]},
        "seller": {"name": offer["vendor"], "location": offer["country"]},
        "terms": {"amount": offer["price"], "currency": "USD",
                  "shipping_days": offer["deliveryDays"],
                  "valid": [offer["validFrom"], offer["validTo"]]},
    }

print("T1 sheeny + stroboscopes AND gadgeteers, num1 > 450:", labels(t1("sheeny", ["stroboscopes", "gadgeteers"], 450)))
print("T2 sheeny + stroboscopes OR gadgeteers, num1 > 450: ", labels(t2("sheeny", ["stroboscopes", "gadgeteers"], 450)))
print("T4 sheeny + stroboscopes, NOT gadgeteers, num1 > 300:", labels(t4("sheeny", ["stroboscopes"], "gadgeteers", 300)))
print("T6 similar to 'boozed thermostats':", labels(t6(2)))
print("T7 label contains 'ales':", labels(t7("ales")))
print("T9 3 most recent English reviews for product 1:")
for r in t9(1, "en", 3):
    print(f"   {r['date']}  {r['rating']:>2}/10  {r['title']} ({r['reviewer']})")
offer = t11(1, "US", 3, "2008-05-28")
print(f"T11 cheapest US offer, <=3 days, valid 2008-05-28: {offer['vendor']} ${offer['price']:.2f}")
print("T12 exported offer:")
print(json.dumps(t12(by_id(1), offer), indent=2))
