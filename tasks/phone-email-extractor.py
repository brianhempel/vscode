# Extract phone numbers (normalised to NNN-NNN-NNNN) and email addresses from free text.

def digits_only(s):
    return "".join(ch for ch in s if ch.isdigit())

def find_phones(text):
    """Scan the text for runs that look like US phone numbers.

    A candidate is a maximal run of characters drawn from digits and the
    separator set " ()-.+". It counts as a phone number if it contains exactly
    10 digits (or 11 starting with a leading 1) AND at least one separator
    (so bare 10-digit codes like an order number are ignored).
    """
    allowed = set("0123456789 ()-.+")
    phones = []
    i = 0
    while i < len(text):
        if text[i] in allowed:
            j = i
            while j < len(text) and text[j] in allowed:
                j += 1
            chunk = text[i:j]
            # A run may contain several numbers separated by whitespace-only
            # gaps ("ext 4" breaks the run, but "or 415..." does not); split on
            # 2+ spaces or newlines to be safe, and then test each piece.
            for piece in chunk.replace("\n", "  ").split("  "):
                d = digits_only(piece)
                if len(d) == 11 and d[0] == "1":
                    d = d[1:]
                has_separator = any(c in piece.strip() for c in " ()-.")
                if len(d) == 10 and has_separator:
                    phones.append(f"{d[0:3]}-{d[3:6]}-{d[6:]}")
            i = j
        else:
            i += 1
    return phones

def find_emails(text):
    """An email is a maximal run of email-safe characters containing exactly one '@'
    with a '.' after it. Trailing punctuation is stripped."""
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@")
    emails = []
    for token in text.replace("<", " ").replace(">", " ").replace("(", " ").replace(")", " ").split():
        run = "".join(ch for ch in token if ch in safe).strip(".,;:")
        if run.count("@") == 1:
            local, domain = run.split("@")
            if local and "." in domain and not domain.startswith(".") and not domain.endswith("."):
                emails.append(run)
    return emails

def dedupe(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

if __name__ == "__main__":
    with open("phone-email-extractor.input.txt") as f:
        text = f.read()

    phones = dedupe(find_phones(text))
    emails = dedupe(find_emails(text))

    print(f"Phone numbers ({len(phones)}):")
    for p in phones:
        print("  " + p)
    print(f"Emails ({len(emails)}):")
    for e in emails:
        print("  " + e)
