# IPv7 addresses (ABBA / ABA-BAB patterns)

- **Source:** Paraphrased from Advent of Code 2016, day 7 ("Internet Protocol Version 7", https://adventofcode.com/2016/day/7). AoC's About page asks that puzzle text and inputs not be copied, so the description is rewritten in our own words and the 12 addresses are synthetic (a few are the classic edge cases in our own spelling). AoC puzzles are used as a problem source in the PSB2 program-synthesis benchmark (Helmuth & Kelly, GECCO 2021) and in several LLM code-generation benchmarks.
- **Tags:** splitting a string on paired delimiters · sliding-window pattern detection · set of substrings · filtering a list
- **Data:** `ipv7-abba.input.txt` — 12 addresses.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** string → (list of outside parts, list of inside parts) → boolean → filtered list

## Task description (as given to participant)

Each line of `ipv7-abba.input.txt` is a made-up "IPv7" address: runs of lowercase letters, some of which are enclosed in square brackets, e.g. `abba[mnop]qrst` or `noon[time]lunch[room]stop`. Call the bracketed runs *inside* parts and the others *outside* parts.

- **Stage A.** An address *supports TLS* if some outside part contains an **ABBA** — four consecutive letters of the form `xyyx` with `x ≠ y` (so `abba` and `ioxxoj` qualify, `aaaa` does not) — **and** no inside part contains an ABBA. Print how many addresses support TLS and list them.
- **Stage B.** An address *supports SSL* if some outside part contains an **ABA** (`xyx`, `x ≠ y`) and some inside part contains the corresponding **BAB** (`yxy`). E.g. `aba[bab]xyz` qualifies, and so does `zazbz[bzb]cdb` (outside `zbz` pairs with inside `bzb`). Print how many addresses support SSL and list them.

Brackets never nest.

## Expected output

```
Stage A - 5 of 12 addresses support TLS:
  abba[mnop]qrst
  ioxxoj[asdfgh]zxcvbn
  hello[world]abbaxyz
  noon[time]lunch[room]stop
  kjklm[abcabc]xyzzyx
Stage B - 3 of 12 addresses support SSL:
  aba[bab]xyz
  aaa[kek]eke
  zazbz[bzb]cdb
```

## Notes for study designers

- This is a pure "detect small simple patterns in strings" task, with a light data-structure layer (two lists per address, a set of ABAs).
- Natural stages: (1) split on `[`/`]` into outside/inside lists; (2) window-of-4 check; (3) window-of-3 check producing a set; (4) build the BAB partner and search the inside parts; (5) filter and print.
- Gotchas: `x ≠ y` (`aaaa`, `xxx` must not count); multiple bracketed sections; an ABBA *inside* brackets disqualifies TLS even if one exists outside; overlapping windows.
- Regex users would reach for a backreference (`(.)(.)\2\1`) — with a plain-string tool this is instead an index-loop task, which is exactly the kind of thing worth observing.

## Example solution

```python
# IPv7 addresses: split into outside/inside-bracket parts and look for small letter patterns.

def split_parts(address):
    """'abba[mnop]qrst' -> (['abba', 'qrst'], ['mnop'])"""
    outside, inside = [], []
    rest = address.strip()
    while "[" in rest:
        before, rest = rest.split("[", 1)
        bracketed, rest = rest.split("]", 1)
        outside.append(before)
        inside.append(bracketed)
    outside.append(rest)
    return outside, inside

def has_abba(s):
    # Any 4-letter window of the form xyyx with x != y.
    return any(s[i] == s[i + 3] and s[i + 1] == s[i + 2] and s[i] != s[i + 1]
               for i in range(len(s) - 3))

def abas(s):
    # Every 3-letter window of the form xyx with x != y.
    return {s[i:i + 3] for i in range(len(s) - 2) if s[i] == s[i + 2] and s[i] != s[i + 1]}

def supports_tls(address):
    outside, inside = split_parts(address)
    return any(has_abba(p) for p in outside) and not any(has_abba(p) for p in inside)

def supports_ssl(address):
    outside, inside = split_parts(address)
    for part in outside:
        for aba in abas(part):
            bab = aba[1] + aba[0] + aba[1]
            if any(bab in p for p in inside):
                return True
    return False

with open("ipv7-abba.input.txt") as f:
    addresses = [line.strip() for line in f if line.strip()]
tls = [a for a in addresses if supports_tls(a)]
ssl = [a for a in addresses if supports_ssl(a)]
print(f"Stage A - {len(tls)} of {len(addresses)} addresses support TLS:")
for a in tls:
    print("  " + a)
print(f"Stage B - {len(ssl)} of {len(addresses)} addresses support SSL:")
for a in ssl:
    print("  " + a)
```
