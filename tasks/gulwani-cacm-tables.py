# Two table-driven transformations from Gulwani, Harris & Singh (CACM 2012):
# Ex. 3 — selling price via lookups in two tables (markup + purchase cost);
# Ex. 5 — layout transformation: wide table of test dates -> long rows.
import csv

def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))

# ---- Example 3: semantic lookup -------------------------------------------
QUERIES = [("Stroller", "12/2010"), ("Bib", "12/2010"),
           ("Diapers", "1/2011"), ("Stroller", "11/2010")]

def selling_prices(markup_rows, cost_rows):
    markup_by_name = {r["name"]: r for r in markup_rows}
    price_by_id_date = {(r["id"], r["date"]): r["price"] for r in cost_rows}
    result = []
    for name, date in QUERIES:
        item = markup_by_name[name]
        price = float(price_by_id_date[(item["id"], date)].lstrip("$"))
        markup = float(item["markup"].rstrip("%")) / 100
        result.append((name, date, f"${price * (1 + markup):.2f}"))
    return result

# ---- Example 5: layout transformation -------------------------------------
def unpivot(wide_rows):
    long_rows = []
    for row in wide_rows:
        name = row["Name"]
        for column, value in row.items():
            if column != "Name" and value.strip():
                long_rows.append((name, column, value))
    return long_rows

if __name__ == "__main__":
    print("Selling prices (Ex. 3):")
    for name, date, price in selling_prices(read_csv("gulwani-cacm-tables.markup.csv"),
                                            read_csv("gulwani-cacm-tables.cost.csv")):
        print(f"  {name:<9} {date:<8} {price}")
    print()
    print("Test dates, long format (Ex. 5):")
    for name, qual, date in unpivot(read_csv("gulwani-cacm-tables.input.csv")):
        print(f"  {name:<7} {qual:<7} {date}")
