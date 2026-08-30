# Minesweeper board annotation

- **Source:** Exercism `minesweeper` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/minesweeper (MIT). A staple of Exercism's Python/other tracks.
- **Tags:** string grid · 2-D neighbourhood scan · list-of-strings → list-of-strings · record separation by blank lines
- **Data:** `minesweeper.input.txt` — two small boards (4×5 and 5×5) separated by a blank line; `*` = mine, `·` (U+00B7) = empty. Synthetic.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** string grid → string grid (a *rendering/annotation* task rather than a data-processing one)

## Task description (as given to participant)

`minesweeper.input.txt` contains one or more rectangular Minesweeper boards, separated by blank lines. `*` marks a mine and `·` an empty square. Write a script that prints each board with every empty square replaced by the number of mines in the 8 surrounding squares — or a space if that number is 0. Mines stay as `*`. Print a header `Board N:` before each board, wrap each row in `|…|`, and print a blank line after each board.

## Expected output

```
Board 1:
|1*3*1|
|13*31|
| 2*2 |
| 111 |

Board 2:
|**1  |
|2321 |
| 1*1 |
|1221 |
|1*1  |

```

## Notes for study designers

- Stages: (1) split the file into boards on blank lines (a "record separator" pattern that recurs in `passport-validation`); (2) for each cell, count neighbours with bounds checks; (3) re-render as strings.
- Good "edit the script" variants: start participants with a version that mis-handles corners (no bounds check → `IndexError`), or one that prints `0` instead of blank; or ask them to switch the mine/empty glyphs to `X`/`.` read from a first header line.
- Exercism's canonical data has 13 cases (empty board, single row, single column, etc.) if more inputs are needed.
- The middle-dot glyph is non-ASCII on purpose — a tiny encoding wrinkle; swap to `.` to remove it.

## Example solution

```python
# Minesweeper: replace each empty cell of a mine grid with the number of
# adjacent mines (blank when zero). Boards are separated by blank lines.

MINE, EMPTY = "*", "·"

def parse_boards(text):
    boards, current = [], []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                boards.append(current)
                current = []
        else:
            current.append(line)
    if current:
        boards.append(current)
    return boards

def annotate(board):
    rows, cols = len(board), len(board[0])
    out = []
    for r in range(rows):
        row = ""
        for c in range(cols):
            if board[r][c] == MINE:
                row += MINE
                continue
            n = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if (dr or dc) and 0 <= rr < rows and 0 <= cc < cols and board[rr][cc] == MINE:
                        n += 1
            row += str(n) if n else " "
        out.append(row)
    return out

if __name__ == "__main__":
    with open("minesweeper.input.txt", encoding="utf-8") as f:
        boards = parse_boards(f.read())
    for i, board in enumerate(boards, 1):
        print(f"Board {i}:")
        for row in annotate(board):
            print("|" + row + "|")
        print()
```
