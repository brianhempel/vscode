# Candidate user-study tasks for a Python script-editing tool

Each task lives in one markdown file `<slug>.md` with:

1. a header block — **source** (benchmark / course / paper / spec, with URL), tags, data file, stdlib modules the reference solution uses, rough difficulty, and the task's *shape* (string → structure, structure → string, both directions, generation, refactoring …);
2. **Task description** written so it can be handed to a participant verbatim;
3. **Expected output** — the literal stdout of the reference solution;
4. **Notes for study designers** — natural sub-stages, gotchas that make good "edit the script" moments, extensions, licensing notes;
5. **Example solution** — a complete script.

Input data sits next to the markdown file as `<slug>.input.<ext>` (occasionally a second file `<slug>.<role>.<ext>`). A runnable copy of every solution sits alongside as `<slug>.py`; run it from this directory:

```
cd tasks
python3 tournament-table.py
python3 check_all.py                # runs every solution, diffs against the .md
```

## Constraints honoured

- Plain Python, no third-party libraries. Solutions use only builtins plus, where natural, `json`, `csv`, `collections`, `fractions`, `urllib`. No `numpy`/`pandas`.
- `re` is allowed but the reference solutions deliberately use plain string methods, so each "detect a small pattern" step is visible as explicit code. Participants may of course use `re`; the notes point out where a simple regex is the natural alternative, and `phone-email-extractor.md` includes a regex variant of its solution.
- All data files are tiny (≤ ~40 lines / ≤ ~30 records).
- Data is either synthetic-in-the-shape-of-the-source or the source's own openly-licensed example. Advent of Code puzzle text/inputs are **not** copied (their About page forbids it); those tasks are paraphrased with freshly generated inputs.

## Sources used, and why they count as ecologically valid

| Source | What it is | Licence / reuse |
|---|---|---|
| [Exercism problem-specifications](https://github.com/exercism/problem-specifications) | ~150 language-agnostic exercises with canonical test data; used on exercism.org by millions of learners and in several education-research papers | MIT |
| [PSB1](https://dl.acm.org/doi/10.1145/2739480.2754769) / [PSB2](https://arxiv.org/abs/2106.06086) | The standard *general program synthesis benchmark suites* (Helmuth & Spector 2015; Helmuth & Kelly 2021); PSB2 problems are curated from Codewars, Advent of Code, Project Euler and course homework | Descriptions are in the papers; data generators at https://www.cs.hamilton.edu/~thelmuth/PSB2/PSB2.html |
| [Advent of Code](https://adventofcode.com) | Annual puzzle series; heavily used in program-synthesis and LLM-code benchmarks (PSB2 draws from it) | Text and inputs must not be copied → paraphrased, synthetic inputs |
| [Rosetta Code](https://rosettacode.org) | Task corpus with solutions in hundreds of languages; used as a benchmark corpus (e.g. RosettaCode-based multilingual code datasets) | GFDL 1.3 — descriptions rewritten |
| [Python for Everybody](https://www.py4e.com) (Severance) | Very widely taken intro course; assignments are string/dict processing over mail logs and JSON | CC-BY; data regenerated |
| [Automate the Boring Stuff](https://automatetheboringstuff.com) (Sweigart) | Canonical end-user-programming text; its projects are archetypal "small script" tasks | CC-BY-NC-SA; data regenerated |
| Gulwani, POPL 2011 (FlashFill) & SyGuS PBE-Strings | The string-transformation tasks that motivated programming-by-example research; drawn from Excel help forums | Examples paraphrased |
| Kandel et al., CHI 2011 (Wrangler) | Data-wrangling user-study tasks from an HCI paper | Tasks reconstructed with synthetic data |
| Stack Overflow classics | Very high-view questions (natural sort, flatten nested dict) | CC-BY-SA; rewritten |
| Real-world formats (Apache Common Log Format, vCard RFC 2426, SemVer 2.0.0, GitHub heading anchors) | Formats people actually script against | Public specs |

## Task index (43 tasks)

Difficulty: E = easy, M = medium, H = medium–hard. "Both ways" = the solution goes string → structure → string (or list ⇄ string).

### From program-synthesis benchmarks (PSB1 / PSB2)

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [camel-case](camel-case.md) | kebab/snake → camelCase and back | E | both ways |
| [word-stats](word-stats.md) | word-length histogram, sentence count, averages from text | E | string → dict → report |
| [luhn-card-filter](luhn-card-filter.md) | validate spaced card numbers, filter, mask | E–M | list of strings → filtered/reformatted |
| [pig-latin](pig-latin.md) (also Exercism) | per-word prefix pattern rules (`qu`, `xr`, consonant clusters) | M | text → words → text |

### From Exercism problem-specifications

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [tournament-table](tournament-table.md) | `home;away;result` lines → tally → league table | E–M | both ways |
| [kindergarten-garden](kindergarten-garden.md) | plant-code grid → per-child lists | E | string grid → dict of lists → string |
| [etl-scrabble](etl-scrabble.md) | invert `score → letters` JSON, then score words | E | nested JSON → flat dict → map |
| [rest-api-ious](rest-api-ious.md) | apply IOU commands to a users JSON, net debts | M | JSON → stateful nested dict → JSON |
| [tree-building](tree-building.md) | flat parent-id records → nested tree + outline | E–M | list → tree → text/JSON |
| [wordy](wordy.md) | `What is 3 plus 2 multiplied by 3?` → numbers, errors | M | string → tokens → number |
| [ocr-numbers](ocr-numbers.md) | 3×4 pipe/underscore glyphs → digits | M | text grid → keys → dict lookup |
| [minesweeper](minesweeper.md) | annotate mine grids with neighbour counts | E–M | string grid → string grid |
| [crypto-square](crypto-square.md) | normalise, chunk into a rectangle, read columns; and decode | M | string → grid → string, and back |
| [twelve-days](twelve-days.md) | generate song verses from a list | E | list → text (generation) |
| [markdown-refactor](markdown-refactor.md) | refactor a clunky mini-Markdown→HTML converter, output unchanged | M | *editing task* |

### Advent of Code (paraphrased, synthetic inputs)

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [password-policy](password-policy.md) | `1-3 a: abcde` lines, two validation rules | E | lines → dicts → filter |
| [passport-validation](passport-validation.md) | blank-line records of `k:v`, per-field small-pattern checks | M | text → dicts → two filters |
| [bag-rules](bag-rules.md) | English containment sentences → graph → recursive queries | M | sentences → nested dict → numbers |
| [cube-game](cube-game.md) | `Game 1: 3 blue, 4 red; …` three-level split, max/filter | E–M | strings → nested → reduce |
| [json-abacus](json-abacus.md) | sum numbers in arbitrary JSON, prune objects containing `"red"` | E–M | nested JSON → number |
| [terminal-filesystem](terminal-filesystem.md) | shell transcript → directory tree → sizes | M | lines → nested dict → tree + numbers |
| [crate-stacks](crate-stacks.md) | parse ASCII stack diagram by column, simulate moves | E–M | 2-D string → stacks → string |
| [room-checksums](room-checksums.md) | letter-frequency checksums, Caesar decrypt | M | string → tuple → filter → string |
| [ipv7-abba](ipv7-abba.md) | ABBA/ABA pattern detection inside vs outside brackets | E–M | string → parts → boolean |
| [digit-words](digit-words.md) | first/last digit incl. spelled-out, overlapping words | E/M | string → ints → sum |

### Rosetta Code

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [range-extraction](range-extraction.md) | `0-2,4,6-8` ⇄ integer lists, negatives | E–M | both ways |
| [top-rank-per-group](top-rank-per-group.md) | CSV → group by dept → top‑N → table and JSON | E | CSV → dict of lists → text/JSON |
| [text-processing-readings](text-processing-readings.md) | date + (value, flag) pairs; stats, longest bad run across lines | M | TSV → tuples → report |

### Courses & end-user programming books

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [mbox-mail-headers](mbox-mail-headers.md) (PY4E) | `From ` vs `From:` lines, counts per sender/hour, averages | E | text → dicts → counts |
| [json-comment-counts](json-comment-counts.md) (PY4E) | sum/top‑N/group a JSON list of `{name,count}` (URL variant noted) | E | JSON → grouped dict → report |
| [phone-email-extractor](phone-email-extractor.md) (ABS ch7) | find & normalise phones/emails in free text without regex | M | text → lists of strings |
| [mad-libs](mad-libs.md) (ABS ch8) | fill ADJECTIVE/NOUN placeholders from a word file | E–M | text + list → text (generation) |

### HCI / PBE research tasks

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [flashfill-transforms](flashfill-transforms.md) (Gulwani POPL'11) | names → `Last, F.`, phone normalisation, weight-token extraction | M | CSV → per-field transforms → CSV |
| [wrangler-crime-reshape](wrangler-crime-reshape.md) (Kandel CHI'11 T1) | `Reported crime in <state>` blocks → tidy CSV + peaks | E | semi-structured text → tuples → CSV |
| [wrangler-housing-crosstab](wrangler-housing-crosstab.md) (Kandel CHI'11 T2) | long `year,month,price` → year × month crosstab and back | E–M | CSV → nested dict → CSV, round trip |

### Stack Overflow classics & real-world formats

| Task | What it involves | Diff. | Shape |
|---|---|---|---|
| [natural-sort](natural-sort.md) | `img10` after `img2`: digit/non-digit run keys | E | strings → mixed chunks → sorted |
| [flatten-nested-dict](flatten-nested-dict.md) | nested JSON ⇄ dotted keys, round trip | M | both ways |
| [deep-merge-configs](deep-merge-configs.md) | recursive merge of defaults/site/local + provenance report | M | nested → nested → flat report |
| [apache-log-parse](apache-log-parse.md) | Common Log Format: quotes/brackets, per-status/path/IP/hour stats | M | log lines → dicts → aggregates |
| [vcard-to-json](vcard-to-json.md) | RFC 2426 vCards with parameters and folded lines → JSON | M | text → nested records → JSON → query |
| [semver-constraints](semver-constraints.md) | versions → tuples; `^`, `~`, `x`, range constraints | H | strings → tuples → filtered → strings |
| [markdown-toc](markdown-toc.md) | headings → GitHub slugs (dedupe) → nested TOC, ignoring code fences | E–M | document → (level,title) → slugs → text |
| [recipe-scaler](recipe-scaler.md) (synthetic) | `2 1/2 cups flour` → parse → ×1.5 → mixed fractions back | M | full round trip |

## Suggested pairings for a study session

- **Warm-up (5 min):** camel-case, natural-sort, or password-policy.
- **Core string↔structure tasks (15–25 min):** tournament-table, cube-game, passport-validation, terminal-filesystem, vcard-to-json, recipe-scaler, range-extraction.
- **Pattern-detection heavy:** pig-latin, ipv7-abba, digit-words, phone-email-extractor, luhn-card-filter, room-checksums.
- **Nested-data heavy (little string work):** json-abacus, tree-building, deep-merge-configs, flatten-nested-dict, rest-api-ious.
- **Not data-processing (generation / simulation / editing):** twelve-days, mad-libs, minesweeper, crate-stacks, crypto-square, markdown-refactor.

Every `.md` has a "Notes for study designers" section listing natural sub-stages and a deliberately buggy starting variant that turns the task into an *edit-this-script* task.
