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

if __name__ == "__main__":
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
