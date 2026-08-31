"""Verify every task: run <slug>.py from the tasks dir, compare its stdout
with the "## Expected output" block of <slug>.md, and confirm the
"## Example solution" code block is identical to the .py file.

Usage (from the tasks directory):  python3 check_all.py
"""
import glob, os, subprocess, sys

def section_block(md, heading):
    """Return the first fenced code block after `heading`, or None."""
    i = md.find(heading)
    if i < 0:
        return None
    j = md.find("```", i)
    if j < 0:
        return None
    k = md.find("\n", j)          # end of the opening fence line
    end = md.find("\n```", k)
    return md[k + 1:end + 1] if end >= 0 else None

ok = True
for md_path in sorted(glob.glob("*.md")):
    slug = md_path[:-3]
    if slug in ("README", "CLAUDE") or "." in slug:   # skip data files like foo.input.md
        continue
    py = slug + ".py"
    if not os.path.exists(py) and os.path.exists(os.path.join("solutions", py)):
        py = os.path.join("solutions", py)   # not yet moved alongside the .md
    if not os.path.exists(py):
        print(f"MISSING  {slug}: no {py}")
        ok = False
        continue
    md = open(md_path).read()
    expected = section_block(md, "## Expected output")
    code = section_block(md, "## Example solution")
    proc = subprocess.run([sys.executable, py], capture_output=True, text=True)
    problems = []
    if proc.returncode != 0:
        problems.append(f"exit {proc.returncode}: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ''}")
    if expected is None:
        problems.append("no Expected output block")
    elif proc.stdout.strip() != expected.strip():
        problems.append("stdout != Expected output")
    if code is None:
        problems.append("no Example solution block")
    elif code.strip() != open(py).read().strip():
        problems.append("md code != .py")
    if problems:
        ok = False
        print(f"FAIL     {slug}: " + "; ".join(problems))
    else:
        print(f"ok       {slug}")
sys.exit(0 if ok else 1)
