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

if __name__ == "__main__":
    db = {u["name"]: u for u in load("rest-api-ious.input.json")["users"]}
    for cmd in load("rest-api-ious.commands.json"):
        apply(db, cmd)
    final = {"users": [db[n] for n in sorted(db)]}
    print(json.dumps(final, indent=2))
