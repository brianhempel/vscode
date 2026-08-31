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
