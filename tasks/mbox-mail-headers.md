# Mailbox header statistics

- **Source:** *Python for Everybody* (Charles Severance), Assignments 9.4 ("count messages per sender") and 10.2 ("count messages per hour of day") — https://www.py4e.com/ (chapters 9–10; original data file `mbox-short.txt`, an excerpt of an Apache Software Foundation Sakai mailing-list archive). Data here is a **synthetic** mbox-style file in the same shape; sender addresses are the same style used in the course.
- **Tags:** line-oriented parsing · prefix detection (`From ` vs `From:`) · dict counting · float parsing/averaging
- **Data:** `mbox-mail-headers.input.txt` — 10 messages, ~85 lines.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy
- **Shape:** text → list of dicts → aggregate counts

## Task description (as given to participant)

`mbox-mail-headers.input.txt` is a mailbox file in the classic Unix "mbox" format. Each message starts with a line that begins with the four characters `From ` (with a trailing space), for example:

```
From stephen.marquard@uct.ac.za Sat Jan  5 09:14:16 2008
```

Below that come header lines such as `From: stephen.marquard@uct.ac.za`, `Subject: …`, `X-DSPAM-Confidence: 0.8475`, then a blank line and the message body.

Write a script that reads the file and prints:

1. the total number of messages;
2. the most prolific sender (address and count), using the address on the `From ` line;
3. the number of messages sent in each hour of the day (from the time on the `From ` line), one `HH count` line per hour, sorted by hour;
4. the average `X-DSPAM-Confidence` across all messages, to 4 decimal places.

Be careful: `From:` header lines and message bodies may also contain the word `From` — only the `From ` separator lines mark the start of a message.

## Expected output

```
Messages: 10
Most prolific sender: zqian@umich.edu (3 messages)
Messages per hour:
  09 2
  11 2
  15 2
  16 2
  18 1
  19 1
Average spam confidence: 0.7244
```

## Notes for study designers

- The core "small pattern" is distinguishing `From ` from `From:` — `line.startswith("From ")` vs `startswith("From")`. The data deliberately contains a body line reading `See message From: sakai-dev list…` so a sloppy check over-counts (11 instead of 10).
- Natural stages: (1) split the file into messages by detecting separator lines; (2) `split()` the separator line to get the address and time, then `split(":")` the time for the hour; (3) count with a dict; (4) `float()` the confidence and average.
- Variations used in the course: sum the confidences instead of averaging; count by day-of-week (`parts[2]`); extract the domain after `@`.
- Extension: build a per-sender nested dict `{sender: {"hours": {...}, "avg_confidence": …}}` and print a small report.

## Example solution

```python
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

if __name__ == "__main__":
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
```
