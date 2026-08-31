# REST API: IOU tracker

- **Source:** Exercism `rest-api` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/rest-api (problem-specifications repo, MIT licence). Adapted from an HTTP-style API to a file-driven script: the "requests" are a list of commands in a JSON file.
- **Tags:** nested JSON in/out · dict of dicts · state updates · netting/merging entries · sorting by key
- **Data:** `rest-api-ious.input.json` (3 users, initial state from the spec's examples) and `rest-api-ious.commands.json` (6 commands).
- **Stdlib used in solution:** `json`
- **Difficulty:** medium (~20 minutes; the netting rule is the tricky part)
- **Shape:** JSON → mutable nested dict → JSON. Not a "compute a number" task: it is state maintenance.

## Task description (as given to participant)

You are simulating a tiny IOU-tracking service. `rest-api-ious.input.json` holds the current database:

```json
{"users": [
  {"name": "Adam", "owes": {"Bob": 12.0}, "owed_by": {"Chuck": 4.0}, "balance": -8.0},
  ...
]}
```

For every user, `owes` maps *creditor name → amount*, `owed_by` maps *debtor name → amount*, and `balance` = total owed_by − total owes.

`rest-api-ious.commands.json` is a list of commands to apply in order:

- `{"op": "add", "user": "Dan"}` — create a user with no debts.
- `{"op": "iou", "lender": "Adam", "borrower": "Dan", "amount": 5.5}` — the lender lent the borrower this amount. **Debts between the same two people must be netted**: if Adam already owes Bob 3 and Bob then lends Adam 5, Adam now owes Bob 8; if instead Adam lends Bob 5, Bob now owes Adam 2. If the debt cancels exactly, remove the entry from both users' dicts.
- `{"op": "get", "users": ["Adam", "Chuck"]}` — print `GET ` followed by the JSON `{"users": [...]}` for the named users (sorted by name, one line).

After applying every command, print the whole database as indented JSON with users sorted by name.

## Expected output

```
GET {"users": [{"name": "Adam", "owes": {"Bob": 15.0, "Chuck": 6.0}, "owed_by": {}, "balance": -21.0}, {"name": "Chuck", "owes": {}, "owed_by": {"Adam": 6.0}, "balance": 6.0}]}
{
  "users": [
    {
      "name": "Adam",
      "owes": {
        "Bob": 15.0,
        "Chuck": 6.0
      },
      "owed_by": {},
      "balance": -21.0
    },
    {
      "name": "Bob",
      "owes": {},
      "owed_by": {
        "Adam": 15.0
      },
      "balance": 15.0
    },
    {
      "name": "Chuck",
      "owes": {},
      "owed_by": {
        "Adam": 6.0
      },
      "balance": 6.0
    },
    {
      "name": "Dan",
      "owes": {},
      "owed_by": {},
      "balance": 0.0
    }
  ]
}
```

## Notes for study designers

- Natural stages: (1) load both files, index users by name; (2) dispatch on `op`; (3) implement the IOU netting (remove any opposite entry, compute the net, write to *both* users); (4) recompute balances; (5) dump sorted JSON.
- The command sequence is designed so every netting case occurs: a fresh debt (Adam→Dan), increasing an existing debt (Bob→Adam), reversing an existing debt (Chuck→Adam flips Adam's 4.0 credit into a 6.0 debt), and exact cancellation (Dan→Adam cancels 5.5, so Dan ends with empty dicts).
- Gotcha: forgetting to update the *other* user's dict, or leaving `0.0` entries behind. The `balance: 0.0` vs `0` distinction is also a nice small edit (`float(...)`).
- Extensions: reject `iou` for unknown users; add a `"op": "remove"` command; output the "GET" results as CSV instead.

## Example solution

```python
# REST-API IOUs: apply a list of commands (add user / record IOU / get) to a
# small in-memory "database" of users and print the final state as JSON.
import json

def load(path):
    with open(path) as f:
        return json.load(f)

def new_user(name):
    return {"name": name, "owes": {}, "owed_by": {}, "balance": 0.0}

def recompute_balance(user):
    user["balance"] = float(sum(user["owed_by"].values()) - sum(user["owes"].values()))

def record_iou(db, lender, borrower, amount):
    """lender lent `amount` to borrower; net it against any existing debt."""
    l, b = db[lender], db[borrower]
    # How much did the lender already owe the borrower?
    existing = l["owes"].pop(borrower, 0.0)
    b["owed_by"].pop(lender, None)
    net = amount - existing
    if net > 0:
        l["owed_by"][borrower] = l["owed_by"].get(borrower, 0.0) + net
        b["owes"][lender] = b["owes"].get(lender, 0.0) + net
    elif net < 0:
        l["owes"][borrower] = -net
        b["owed_by"][lender] = -net
    # net == 0 -> debts cancel, nothing recorded
    # Drop empty entries and refresh balances.
    for u in (l, b):
        u["owes"] = {k: v for k, v in u["owes"].items() if v}
        u["owed_by"] = {k: v for k, v in u["owed_by"].items() if v}
        recompute_balance(u)

def apply(db, cmd):
    op = cmd["op"]
    if op == "add":
        if cmd["user"] in db:
            raise ValueError(f"user exists: {cmd['user']}")
        db[cmd["user"]] = new_user(cmd["user"])
    elif op == "iou":
        record_iou(db, cmd["lender"], cmd["borrower"], cmd["amount"])
    elif op == "get":
        names = cmd.get("users") or sorted(db)
        print("GET", json.dumps({"users": [db[n] for n in sorted(names)]}))
    else:
        raise ValueError(f"unknown op {op}")

db = {u["name"]: u for u in load("rest-api-ious.input.json")["users"]}
for cmd in load("rest-api-ious.commands.json"):
    apply(db, cmd)
final = {"users": [db[n] for n in sorted(db)]}
print(json.dumps(final, indent=2))
```
