# The Twelve Days of Christmas (text generation)

- **Source:** Exercism `twelve-days` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/twelve-days (MIT). The lyrics are a traditional (public-domain) English carol.
- **Tags:** text generation from a list · cumulative slicing · reversing · joining with `, ` and a final `and` · templating
- **Data:** `twelve-days.input.txt` — 12 lines `ordinal|gift`.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy
- **Shape:** list of pairs → string; no data processing in the usual sense

## Task description (as given to participant)

`twelve-days.input.txt` lists the twelve gifts of the carol, one per line in the form `ordinal|gift` (e.g. `third|three French Hens`).

Write a script that builds verse *n* of the song for any *n* from 1 to 12:

```
On the <ordinal> day of Christmas my true love gave to me: <gifts>.
```

where `<gifts>` lists the gifts for days *n* down to 1, separated by `, `, with `and ` before the last one. Verse 1 has a single gift and no `and`. Print verses 1, 2, 3 and 12, each followed by a blank line.

## Expected output

```
On the first day of Christmas my true love gave to me: a Partridge in a Pear Tree.

On the second day of Christmas my true love gave to me: two Turtle Doves, and a Partridge in a Pear Tree.

On the third day of Christmas my true love gave to me: three French Hens, two Turtle Doves, and a Partridge in a Pear Tree.

On the twelfth day of Christmas my true love gave to me: twelve Drummers Drumming, eleven Pipers Piping, ten Lords-a-Leaping, nine Ladies Dancing, eight Maids-a-Milking, seven Swans-a-Swimming, six Geese-a-Laying, five Gold Rings, four Calling Birds, three French Hens, two Turtle Doves, and a Partridge in a Pear Tree.

```

## Notes for study designers

- One of the "doesn't fit the data-processing mould" tasks: output is prose generated from a small list; the only tricky bits are the `and` rule and the reversed cumulative slice.
- The Exercism spec uses an Oxford comma (`, and a Partridge`), which is easy to get wrong and easy to describe as an edit ("remove the comma before `and`").
- Extensions: print all 12 verses; accept the day number on the command line; generalise to the cumulative-song pattern used by Exercism's `house` and `food-chain` exercises.

## Example solution

```python
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

if __name__ == "__main__":
    gifts = load_gifts("twelve-days.input.txt")
    for n in (1, 2, 3, 12):
        print(verse(n, gifts))
        print()
```
