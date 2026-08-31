# mbox headers: count messages per sender, per hour, and average spam confidence.

def parse_mbox(lines):
    """Return a list of message dicts: {"sender", "hour", "confidence"}."""
    messages = []
    current = None
    for line in lines:
        line = line.rstrip("\n")
        # A message starts with "From " (with a space) - NOT "From:"
        if line.startswith("From "):
            parts = line.split()
            # e.g. ["From", "stephen.marquard@uct.ac.za", "Sat", "Jan", "5", "09:14:16", "2008"]
            time = parts[5]
            current = {"sender": parts[1], "hour": time.split(":")[0], "confidence": None}
            messages.append(current)
        elif line.startswith("X-DSPAM-Confidence:") and current is not None:
            current["confidence"] = float(line.split(":", 1)[1].strip())
    return messages

def count_by(messages, key):
    counts = {}
    for m in messages:
        counts[m[key]] = counts.get(m[key], 0) + 1
    return counts

with open("mbox-mail-headers.input.txt") as f:
    messages = parse_mbox(f)

print(f"Messages: {len(messages)}")

senders = count_by(messages, "sender")
top = max(senders.items(), key=lambda kv: kv[1])
print(f"Most prolific sender: {top[0]} ({top[1]} messages)")

print("Messages per hour:")
for hour, n in sorted(count_by(messages, "hour").items()):
    print(f"  {hour} {n}")

confidences = [m["confidence"] for m in messages if m["confidence"] is not None]
print(f"Average spam confidence: {sum(confidences) / len(confidences):.4f}")
