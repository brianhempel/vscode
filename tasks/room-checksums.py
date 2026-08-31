# Room checksums: validate encrypted room names, sum sector ids, then decrypt the real ones.

from collections import Counter

def parse(line):
    """'aaaaa-bbb-z-y-x-123[abxyz]' -> ('aaaaa-bbb-z-y-x', 123, 'abxyz')"""
    body, checksum = line.strip().rstrip("]").split("[")
    name, sector = body.rsplit("-", 1)
    return name, int(sector), checksum

def expected_checksum(name):
    counts = Counter(name.replace("-", ""))
    # Most common first; ties broken alphabetically.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "".join(letter for letter, _ in ranked[:5])

def decrypt(name, shift):
    out = []
    for ch in name:
        if ch == "-":
            out.append(" ")
        else:
            out.append(chr((ord(ch) - ord("a") + shift) % 26 + ord("a")))
    return "".join(out)

with open("room-checksums.input.txt") as f:
    rooms = [parse(line) for line in f if line.strip()]

real = [(name, sector) for name, sector, chk in rooms if expected_checksum(name) == chk]
fake = [name for name, sector, chk in rooms if expected_checksum(name) != chk]
print(f"Real rooms: {len(real)} of {len(rooms)}; rejected: {fake}")
print(f"Sum of real sector ids: {sum(sector for _, sector in real)}")
print()
print("Decrypted names:")
for name, sector in real:
    plain = decrypt(name, sector)
    marker = "   <-- here" if "northpole" in plain else ""
    print(f"  {sector:>4}  {plain}{marker}")
