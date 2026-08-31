# Extract Entity: split orders into customers + orders, and back

- **Source:** Jonathan Edwards, Tomas Petricek & Tijs van der Storm, "Live & Local Schema Change: Challenge Problems" (2023), https://arxiv.org/abs/2309.11406 — §2 *Extract Entity* (Acme's orders spreadsheet duplicates customer name and address on every row; split into a Customers table and an Orders table that references it, deduplicating customers first) and §3 *Divergence Control* (another department keeps the old wide schema and needs new data converted back). The Acme/Wile E Coyote example is theirs; the rows here are extended synthetically, including one conflicting address.
- **Tags:** CSV in/out · deduplicate into a dict keyed by name · conflict detection · projecting columns · join to reverse the migration · filtered view (blank field) with lookup
- **Data:** `extract-entity-migration.input.csv` — 10 orders, 4 customers, one customer with two different addresses.
- **Stdlib used in solution:** `csv`, `io`
- **Difficulty:** easy–medium
- **Shape:** wide table → two related tables (dict + list) → wide table again → filtered report. Bidirectional.

## Task description (as given to participant)

`extract-entity-migration.input.csv` is Acme's order sheet: `item,quantity,ship_date,customer_name,customer_address`. Each order repeats the customer's address, and when a customer moves someone has to edit every row. Write a script that performs the *Extract Entity* schema change and checks it:

1. Build `customers` (one row per distinct `customer_name` with their address; if a customer appears with two different addresses keep the first and report the conflict) and `orders` (the original columns minus `customer_address`). Print both as CSV under `== customers.csv` (sorted by name) and `== orders.csv` (original order), then `== conflicts` lines `Name: kept '...', ignored '...'`.
2. Reverse the migration: rebuild the wide format by looking each order's address up in `customers`; report how many rows are identical to the original and list the ones that differ.
3. Print the shipping department's view: every order with a blank `ship_date`, as `  <qty> x <item> -> <customer>, <address>`.

## Expected output

```
== customers.csv
name,address
Bugs Bunny,Rabbit Hole Lane
Daffy Duck,White Rock Lake
Road Runner,Route 66 Milepost 9
Wile E Coyote,123 Desert Station

== orders.csv
item,quantity,ship_date,customer_name
Anvil,1,2/3/23,Wile E Coyote
Dynamite,2,,Daffy Duck
Bird Seed,1,,Wile E Coyote
Rocket Skates,1,2/5/23,Wile E Coyote
Carrots,12,2/6/23,Bugs Bunny
Anvil,3,,Daffy Duck
Giant Rubber Band,1,,Wile E Coyote
Bird Seed,5,2/7/23,Road Runner
Earmuffs,2,,Bugs Bunny
Dehydrated Boulders,1,,Wile E Coyote

== conflicts
Wile E Coyote: kept '123 Desert Station', ignored '124 Desert Station'

== reverse migration (old wide schema)
9 of 10 rows identical to the original; differing rows:
  Giant Rubber Band for Wile E Coyote: address now '123 Desert Station' (was '124 Desert Station')

== shipping view: unshipped orders
  2 x Dynamite             -> Daffy Duck, White Rock Lake
  1 x Bird Seed            -> Wile E Coyote, 123 Desert Station
  3 x Anvil                -> Daffy Duck, White Rock Lake
  1 x Giant Rubber Band    -> Wile E Coyote, 123 Desert Station
  2 x Earmuffs             -> Bugs Bunny, Rabbit Hole Lane
  1 x Dehydrated Boulders  -> Wile E Coyote, 123 Desert Station
```

## Notes for study designers

- This is the paper's challenge as a plain script: the interesting decisions (which address wins, what "reversible" means when the data had a conflict) are exactly the ones the paper says tooling leaves to custom code.
- Edit-the-script variants: (a) make the *latest* address win instead of the first; (b) key customers by a generated id instead of the name and emit `customer_id` in orders; (c) accept an *update* to a customer's address in the new schema and push it back through to the old wide view (the paper's §3 reverse direction).
- Pure structure work with a small amount of CSV string handling; pairs with `wrangler-housing-crosstab` (also a reversible reshape).

## Example solution

```python
# Extract Entity: split a wide orders table into customers + orders,
# report conflicts, then reverse the migration and build the shipping view.
import csv, io

def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))

def to_csv(rows, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().rstrip()

def extract_customers(orders):
    """name -> address; first address seen wins, later differences are conflicts."""
    customers, conflicts = {}, []
    for o in orders:
        name, addr = o["customer_name"], o["customer_address"]
        if name not in customers:
            customers[name] = addr
        elif customers[name] != addr:
            conflicts.append((name, customers[name], addr))
    return customers, conflicts

def narrow_orders(orders):
    return [{k: v for k, v in o.items() if k != "customer_address"} for o in orders]

def rejoin(narrow, customers):
    """Reverse migration: old wide schema, address looked up by name."""
    return [dict(o, customer_address=customers[o["customer_name"]]) for o in narrow]

wide = read_csv("extract-entity-migration.input.csv")
customers, conflicts = extract_customers(wide)
narrow = narrow_orders(wide)

print("== customers.csv")
print(to_csv([{"name": n, "address": a} for n, a in sorted(customers.items())], ["name", "address"]))
print("\n== orders.csv")
print(to_csv(narrow, ["item", "quantity", "ship_date", "customer_name"]))
print("\n== conflicts")
for name, kept, other in conflicts:
    print(f"{name}: kept {kept!r}, ignored {other!r}")

print("\n== reverse migration (old wide schema)")
back = rejoin(narrow, customers)
same = sum(1 for x, y in zip(back, wide) if x == y)
print(f"{same} of {len(wide)} rows identical to the original; differing rows:")
for x, y in zip(back, wide):
    if x != y:
        print(f"  {x['item']} for {x['customer_name']}: address now {x['customer_address']!r} (was {y['customer_address']!r})")
print("\n== shipping view: unshipped orders")
for o in rejoin(narrow, customers):
    if o["ship_date"] == "":
        print(f"{o['quantity']:>3} x {o['item']:<20} -> {o['customer_name']}, {o['customer_address']}")
```
