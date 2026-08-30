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

if __name__ == "__main__":
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
