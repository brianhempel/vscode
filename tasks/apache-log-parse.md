# Apache access-log summary

- **Source:** Apache HTTP Server "Common Log Format" (NCSA CLF) — https://httpd.apache.org/docs/2.4/logs.html#common. This is a real, decades-old file format produced by Apache, nginx (default `combined` is a superset) and many other servers; "parse the access log and count statuses / top URLs" is a canonical sysadmin/data-cleaning chore and a staple of Python tutorials and interview questions. Log lines here are synthetic but follow the format exactly, including the documented example line's shape (`frank`, `/apache_pb.gif`).
- **Tags:** delimiter-aware parsing (brackets, quotes, a path containing a space) · `-` meaning missing · `Counter` / grouped sums · string slicing for the hour · sorting and `most_common` · text bar chart rendering
- **Data:** `apache-log-parse.input.log` — 20 lines, one HTTP request per line.
- **Stdlib used in solution:** `collections`
- **Difficulty:** medium
- **Shape:** string → list of dicts → several aggregations → formatted report

## Task description (as given to participant)

`apache-log-parse.input.log` is a web-server access log in Common Log Format. Each line looks like

```
10.0.0.5 - frank [10/Oct/2000:13:58:02 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326
```

i.e. `client-ip ident user [timestamp] "METHOD path PROTOCOL" status size`. `-` means "not available" (for `size` treat it as 0). Beware: the quoted request can contain spaces inside the path.

Write a script that parses every line into a record and prints:

1. the number of requests per HTTP status code, ascending;
2. the top 3 paths by number of hits (drop any `?query` part first, so `/search?q=a` and `/search?q=b` count as the same path);
3. total bytes sent per client IP, largest first, with thousands separators;
4. requests per hour of day, as a small `#` bar chart.

## Expected output

```
Requests per status:
  200: 12
  302: 1
  304: 2
  403: 1
  404: 3
  500: 1
Top 3 paths:
   6  /index.html
   2  /images/logo.png
   2  /css/site.css
Bytes per client:
  10.0.0.5         93,154
  192.168.1.10     15,361
  203.0.113.7       6,570
  198.51.100.23     3,862
Requests per hour:
  13:00  #### (4)
  14:00  ######### (9)
  15:00  ##### (5)
  16:00  ## (2)
```

## Notes for study designers

- The parsing stage is the heart of it: participants must notice that naive `split()` breaks on the timestamp (space before the timezone) and on the one path with a space. Splitting on ` [`, `] `, and `" ` in sequence is the plain-string-methods route; a regex is the other route.
- Nice pre-made buggy version: a script that uses `line.split()` and silently miscounts the `q3 summary.pdf` requests — ask participants to find and fix it.
- Extensions: also parse the *combined* format (adds `"referer" "user-agent"`); group by day; find IPs that produced only 404s (the scanner at `198.51.100.23`).
- The `hour` extraction is a small string-pattern task by itself (`time.split(":")[1]`).

## Example solution

```python
# Parse Apache/NCSA Common Log Format lines and summarise them.
from collections import Counter, defaultdict

def parse_line(line):
    """Return a dict for one CLF line:
    host ident user [time] "request" status size
    The request is quoted and may itself contain spaces, so we split around
    the brackets and quotes rather than on whitespace alone."""
    head, rest = line.split(" [", 1)          # 'host ident user', 'time] "req" status size'
    time, rest = rest.split("] ", 1)          # '10/Oct/2000:13:55:36 -0700', '"req" status size'
    assert rest.startswith('"')
    request, tail = rest[1:].split('" ', 1)   # 'GET /x HTTP/1.0', '200 2326'
    status, size = tail.split()
    host, ident, user = head.split()
    method, path_and_proto = request.split(" ", 1)
    path, protocol = path_and_proto.rsplit(" ", 1)  # path may contain spaces
    return {
        "host": host,
        "user": None if user == "-" else user,
        "time": time,
        "hour": time.split(":")[1],           # '13' from '10/Oct/2000:13:55:36 -0700'
        "method": method,
        "path": path,
        "protocol": protocol,
        "status": int(status),
        "size": 0 if size == "-" else int(size),
    }

def main():
    with open("apache-log-parse.input.log") as f:
        entries = [parse_line(l.rstrip("\n")) for l in f if l.strip()]

    by_status = Counter(e["status"] for e in entries)
    print("Requests per status:")
    for status in sorted(by_status):
        print(f"  {status}: {by_status[status]}")

    # Strip query strings so /search?q=a and /search?q=b count as one path.
    by_path = Counter(e["path"].split("?")[0] for e in entries)
    print("Top 3 paths:")
    for path, n in by_path.most_common(3):
        print(f"  {n:2d}  {path}")

    bytes_by_host = defaultdict(int)
    for e in entries:
        bytes_by_host[e["host"]] += e["size"]
    print("Bytes per client:")
    for host, total in sorted(bytes_by_host.items(), key=lambda kv: -kv[1]):
        print(f"  {host:<15} {total:>7,}")

    by_hour = Counter(e["hour"] for e in entries)
    print("Requests per hour:")
    for hour in sorted(by_hour):
        print(f"  {hour}:00  {'#' * by_hour[hour]} ({by_hour[hour]})")

main()
```
