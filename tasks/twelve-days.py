# Twelve Days of Christmas: generate verses from an (ordinal, gift) list.

def load_gifts(path):
    gifts = []
    with open(path) as f:
        for line in f:
            ordinal, gift = line.rstrip("\n").split("|")
            gifts.append((ordinal, gift))
    return gifts

def verse(n, gifts):
    ordinal = gifts[n - 1][0]
    # Gifts for this verse, most recent first.
    todays = [g for _, g in gifts[:n]][::-1]
    if len(todays) == 1:
        gift_text = todays[0]
    else:
        gift_text = ", ".join(todays[:-1]) + ", and " + todays[-1]
    return f"On the {ordinal} day of Christmas my true love gave to me: {gift_text}."

gifts = load_gifts("twelve-days.input.txt")
for n in (1, 2, 3, 12):
    print(verse(n, gifts))
    print()
