# BESDUI product search (Berlin SPARQL Benchmark explore tasks)

- **Source:** Roberto García, Rosa Gil, Eirik Bakke, David R. Karger, "A Benchmark for End-User Structured Data User Interfaces" (BESDUI) — https://github.com/rhizomik/BESDUI (paper: Semantic Web journal / ISWC 2020–2021). Its 12 user tasks are adopted almost verbatim from the Berlin SPARQL Benchmark (BSBM, http://wifo5-03.informatik.uni-mannheim.de/bizer/berlinsparqlbenchmark/) e-commerce "explore" use case: a consumer looking for a product. Bakke's 2016 MIT thesis (Table 3.7) evaluates SIEUFERD on the same tasks with KLM keystroke counts. The product labels here mimic BSBM's generated nonsense words ("waterskiing sharpness horseshoes", "boozed thermostats"); all data is synthetic and tiny.
- **Tags:** nested JSON (products → offers, reviews) · list-of-dicts filtering with `all`/`any`/negation · set intersection · substring / whole-word matching · sort by ISO date string · date-range validity check · `min` by key · re-shaping a record into another schema
- **Data:** `besdui-product-search.input.json` — 10 products, each with 1–4 offers and 0–4 reviews.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium (many small stages; each one is a 3–5-line filter)
- **Shape:** nested JSON → filtered lists / single records → short strings, plus one structure → structure export

## Task description (as given to participant)

`besdui-product-search.input.json` is a small product catalogue: a list of products, each with `id`, `label`, `type`, a list of `features`, two numeric properties, a list of `offers` (`vendor, country, price, deliveryDays, validFrom, validTo`) and a list of `reviews` (`title, language, date, rating, reviewer`). Dates are ISO `YYYY-MM-DD` strings.

Write a script that answers these consumer queries and prints each result on one line (product labels comma-separated), in this order:

- **T1** products of type `sheeny` having **both** features `stroboscopes` and `gadgeteers`, with `propertyNumeric1 > 450`.
- **T2** as T1 but having **at least one** of the two features.
- **T4** products of type `sheeny` having `stroboscopes` but **not** `gadgeteers`, with `propertyNumeric1 > 300`.
- **T6** products similar to `boozed thermostats` (id 2): share at least one feature and have `propertyNumeric1` within ±100 of it.
- **T7** products whose label contains the word `ales`.
- **T9** the 3 most recent **English** reviews of product 1, one per line: date, rating, title, reviewer.
- **T11** the cheapest offer for product 1 from a **US** vendor delivering within **3 days** that is valid on **2008-05-28**.
- **T12** export that offer into another system's schema as JSON: `{"item": {"sku": "BSBM-0001", "name": …}, "seller": {"name": …, "location": …}, "terms": {"amount": …, "currency": "USD", "shipping_days": …, "valid": [from, to]}}`.

(T3, T5, T8 and T10 of the benchmark are display/detail tasks and are omitted.)

## Expected output

```
T1 sheeny + stroboscopes AND gadgeteers, num1 > 450: waterskiing sharpness horseshoes
T2 sheeny + stroboscopes OR gadgeteers, num1 > 450:  waterskiing sharpness horseshoes, ales gadgeteers, sheeny stroboscopes deluxe, gadgeteers unplugged, stroboscopes for morales
T4 sheeny + stroboscopes, NOT gadgeteers, num1 > 300: sheeny stroboscopes deluxe, stroboscopes for morales
T6 similar to 'boozed thermostats': waterskiing sharpness horseshoes, ales gadgeteers, gadgeteers unplugged, stroboscopes for morales, wormholes weekender, sheeny horseshoes mini
T7 label contains 'ales': ales gadgeteers, horseshoes and ales
T9 3 most recent English reviews for product 1:
   2008-05-27   9/10  Great gadgeteers support (Reviewer1)
   2008-05-20   7/10  Sturdy but loud (Reviewer3)
   2008-04-02   4/10  Not what I expected (Reviewer5)
T11 cheapest US offer, <=3 days, valid 2008-05-28: Vendor12 $1299.50
T12 exported offer:
{
  "item": {
    "sku": "BSBM-0001",
    "name": "waterskiing sharpness horseshoes"
  },
  "seller": {
    "name": "Vendor12",
    "location": "US"
  },
  "terms": {
    "amount": 1299.5,
    "currency": "USD",
    "shipping_days": 2,
    "valid": [
      "2008-05-01",
      "2008-06-15"
    ]
  }
}
```

## Notes for study designers

- A benchmark whose *tasks* were designed for user-interface evaluation (BESDUI reports capability, operator count, time per task), so it is directly reusable as a set of user-study tasks; here each task becomes one small function over nested data.
- Stage-by-stage difficulty rises gently: T1/T2/T4 differ by one word (`all` / `any` / `not in`) — a clean "edit this predicate" sequence; T6 introduces set intersection and a numeric window; T7 is the only string-pattern task (whole-word match: `ales` must not match `morales`); T9/T11 sort and filter *inside* a product; T12 is a pure reshaping step.
- Deliberate traps in the data: the globally cheapest offer for product 1 is German (T11 must filter on country); Vendor04 is US and cheap but ships in 5 days; Vendor07's offer is not yet valid on the query date; product 8 contains `morales` for the T7 whole-word check; reviews include non-English ones that must be dropped in T9.
- Extensions: T8 (offers from German vendors valid today plus all reviews, as a nested report), T10 (everything known about a reviewer across products — inverting the nesting), or reading the JSON from a URL.

## Example solution

```python
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
```
