# Gulwani CACM table examples (lookup pricing, layout unpivot)

- **Source:** Sumit Gulwani, William R. Harris, Rishabh Singh, "Spreadsheet Data Manipulation Using Examples", *Communications of the ACM* 55(8), 2012 — https://doi.org/10.1145/2240236.2240260. Example 3 (a shopkeeper computing selling prices from two inventory tables — the paper's motivating case for *semantic* string transformations with table lookups) and Example 5 (a layout transformation posted by a novice on an Excel help thread). Table contents follow the paper's figures; the queries and one extra row are ours.
- **Tags:** CSV loading · dict indexes for lookup/join · parsing `$145.67` and `30%` · float formatting · wide → long (unpivot) with blank-skipping
- **Data:** `gulwani-cacm-tables.markup.csv` (5 rows: `id,name,markup`), `gulwani-cacm-tables.cost.csv` (6 rows: `id,date,price`), `gulwani-cacm-tables.input.csv` (3 rows: `Name,Qual 1,Qual 2,Qual 3`).
- **Stdlib used in solution:** `csv`
- **Difficulty:** easy–medium
- **Shape:** CSV tables → dict indexes → computed rows; wide table → long list of tuples

## Task description (as given to participant)

Write one script that prints two results.

**Part 1 — selling prices.** A shop's inventory is split across two CSV files: `gulwani-cacm-tables.markup.csv` (`id,name,markup`, e.g. `S33,Stroller,30%`) and `gulwani-cacm-tables.cost.csv` (`id,date,price`, e.g. `S33,12/2010,$145.67`, the purchase price in that month). For each of the queries `(Stroller, 12/2010)`, `(Bib, 12/2010)`, `(Diapers, 1/2011)`, `(Stroller, 11/2010)`, compute the selling price = purchase price for that item and month × (1 + markup), and print it as `$NNN.NN`.

**Part 2 — layout transformation.** `gulwani-cacm-tables.input.csv` is a wide table: one row per test taker, one column per qualifier (`Qual 1`…`Qual 3`) holding the date the test was taken (`01.02.2003`) or blank if not taken. Print one line per *taken* test in the form `name  qualifier  date`, in row-major order, skipping blanks.

## Expected output

```
Selling prices (Ex. 3):
  Stroller  12/2010  $189.37
  Bib       12/2010  $5.16
  Diapers   1/2011   $28.96
  Stroller  11/2010  $185.09

Test dates, long format (Ex. 5):
  Andrew  Qual 1  01.02.2003
  Andrew  Qual 2  27.06.2008
  Andrew  Qual 3  06.04.2007
  Ben     Qual 1  31.08.2001
  Ben     Qual 3  05.07.2004
  Carl    Qual 1  18.04.2003
  Carl    Qual 2  09.12.2009
```

## Notes for study designers

- Part 1 is a two-table join done with dict indexes (`name → item`, `(id, date) → price`) plus two small string-to-number parses (`$`, `%`). Part 2 is the paper's `Filter(λc. c.data ≠ "" ∧ c.col ≠ 1 ∧ c.row ≠ 1, SEQ…)` program written by hand.
- Natural edit-task variants: (a) a starting script that keys the price table by `id` only, so the 11/2010 stroller price silently overwrites 12/2010; (b) ask for the *inverse* of Part 2 (long → wide, i.e. the `wrangler-housing-crosstab` shape); (c) add a `Total` column or a rounding rule (`round half up` vs Python's banker's rounding — `$189.37` vs the naive expectation).
- Pairs with `gulwani-cacm-strings` (the same paper's syntactic examples).

## Example solution

```python
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
```
