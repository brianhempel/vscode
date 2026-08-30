# snc — user-study task corpus: notes for Claude

This repo collects candidate tasks for a user study of a Python script-editing tool.
`tasks/README.md` is the human-facing index; this file holds working knowledge that
is *not* in the README.

## What the user wants (constraints, in priority order)

- Plain Python only: no numpy/pandas or other specialised libraries. Stdlib `json`,
  `csv`, `collections`, `urllib` are fine. `re` is explicitly allowed ("hopefully not in a
  super-complex way") — reference solutions still prefer plain string methods so each
  small-pattern step is visible; add a regex variant only where regex is the canonical
  approach (see `phone-email-extractor.regex.py`).
- Tiny data: "even a hundred things in a table might be a problem". Keep ≤ ~30 records /
  ~40 lines per file. Trim real datasets rather than reproducing them.
- Ideal shape: string manipulation (split/join/detect small patterns) **interleaved** with
  list/dict/nested-data work, ideally going string → structure → string.
- Ecological validity matters: prefer tasks from benchmarks (PSB1/2, Exercism, BESDUI),
  courses (PY4E, Automate the Boring Stuff), HCI user studies (Wrangler, Gneiss, SIEUFERD,
  Vegemite, Toped, FlashFill/BlinkFill), real formats (CLF logs, vCard, SemVer). Purely
  synthetic tasks are acceptable but label them as such.
- Most tasks are data-processing shaped (start with data, transform/compute); that is the
  core. The user is *open to* — not preferring — tasks that don't fit that pattern
  (generation, simulation, rendering, refactoring, document merging), and found the idea
  "kind of interesting", so include a few for variety but don't over-weight them.
- Reading local files or downloading CSV/JSON from URLs is fine.

## Layout conventions (enforced by `tasks/check_all.py`)

- One task = `tasks/<slug>.md` + `tasks/<slug>.py` (solution **alongside** the md — the
  user asked for this explicitly; there is no `solutions/` folder) + data
  `tasks/<slug>.input.<ext>` (extra files: `<slug>.<role>.<ext>`, e.g. `mad-libs.words.txt`).
- Shared datasets used by several tasks are allowed and named by dataset, not slug:
  `chi15.papers.json` / `chi15.sessions.json` (Gneiss tasks), `course-db.*.csv` (Bakke tasks).
- Solutions run from `tasks/` and open data by bare relative filename.
- `check_all.py` (run from `tasks/`) runs every `<slug>.py`, diffs stdout against the
  `## Expected output` block, and requires the `## Example solution` block to be
  byte-identical to the `.py`. It skips `README.md` and any md whose name contains a dot
  (data files like `markdown-refactor.input.md`). **Every task must pass before you report.**
- Workflow that avoids drift: write the `.py`, run it, then generate the md with
  `cat <slug>.py` inside a heredoc-built file so the code block cannot diverge. If you edit
  a `.py` later, regenerate the md's code block *and* expected output.
- md header block: Source (with URL + licence/reuse note), Tags, Data, Stdlib used,
  Difficulty, Shape. Sections: Task description (participant-ready), Expected output,
  Notes for study designers (sub-stages, a "buggy starting version" idea, extensions),
  Example solution.

## Licensing / provenance rules used so far

- Advent of Code: About page forbids copying puzzle text/inputs → paraphrase, synthetic
  inputs, cite the puzzle URL, and say so.
- Exercism problem-specifications: MIT. Rosetta Code: GFDL — rewrite descriptions.
- Course/book data (PY4E mbox, ABS): regenerate synthetic data in the same shape.
- Papers' user-study tasks: reconstruct with synthetic data; substitute invented names
  for any real people named in the paper (e.g. instructors in Bakke CHI'11).
- Real public API data is OK when keyless and small: `sculpin-artic-gallery.input.json` is
  a genuine response from `https://api.artic.edu/api/v1/artworks/search?q=cats&limit=8&...`.

## Mining the user's Zotero library for more tasks

- PDFs live in `~/Zotero/storage/<KEY>/`. Each folder has `.zotero-ft-cache` = extracted
  full text; grep that instead of reading PDFs (cheap and fast):
  `grep -n -i -E 'task ?[0-9]|participants were asked|Example [0-9]' ~/Zotero/storage/*/.zotero-ft-cache`
- Find a paper's folder by filename: `find ~/Zotero/storage -maxdepth 2 -name '*Bakke*'`.
- Already mined (keys): Chang thesis APSY4Q2N, Chang & Myers 2016 5FZ5FHME, Bakke 2011
  93MFUNCP, Bakke 2016 thesis H3YQ9H6N (SIEUFERD; appendix has the BESDUI tasks),
  García 2021 BESDUI ZXP6RVRJ, Edwards 2023 schema change MDRP5QT4, Gulwani 2012 VAYLYCVS,
  BlinkFill 4QQE4M62, Vegemite 8334332P, Toped F3YI69ZV, Wildcard J876LCYY, Sculpin
  BIA5S4GF, Mashroom PXY7S7FB, Denicek UQ4L4W4Y, Kandel Wrangler (used from memory).
- Not yet mined but promising: Rousillon (Chasins 2018, web-scraping tasks), Object
  Spreadsheets (McCutchen 2016, car-sharing example), Gradual structuring (Miller 2016),
  Unravel (Shrestha 2021, R/dplyr snippets → could be re-expressed in plain Python),
  Heer "Predictive Interaction", Scaffidi "Editor and Parser for Data Formats" (7TIRQW3W),
  Cambronero FlashFill++ (AHA25MUX), Homer jq (Q8SD8CIU), Krebs 2023 example-based live
  programming, Santolucito 2019 Live PBE, Kubelka/Sillito "programming change task" papers.

## Leftover task ideas (not written)

Exercism `ledger`, `poker`, `sgf-parsing`, `bowling`; PSB2 `shopping-list`, `bowling`;
Rosetta "Abbreviations, automatic", "Comma quibbling", "CSV to HTML"; AoC 2015 d5 "nice
strings"; ABS ch16 CSV header stripping / mail merge; iCalendar (RFC 5545) parsing.

## Pitfalls hit

- Parallel forks writing the same directory: changing layout mid-run (solutions/ → flat)
  broke several forks' md embedding; decide layout before fanning out.
- Expected-output blocks can contain trailing spaces (crypto-square) — the checker strips
  only leading/trailing whitespace of the whole block, so interior trailing spaces must
  match exactly; don't hand-edit expected output.
- `minesweeper.input.txt` uses U+00B7 middle dots (open with `encoding="utf-8"`).
- Never `git commit`; the user asks explicitly when they want commits. The repo is not a
  git repository as of Aug 2026.
- Zotero `.zotero-ft-cache` text loses bold/italics and can garble letter case in
  extracted tables (e.g. Gulwani CACM'12 Ex. 2 read as `aCM`/`PoPL`); when a worked
  example looks odd, derive the intended behaviour from the paper's DSL program or figure
  rather than the extracted strings.
- Real people named in papers (instructors, journalists) → substitute invented names.
