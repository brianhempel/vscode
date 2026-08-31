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

with open("minesweeper.input.txt", encoding="utf-8") as f:
    boards = parse_boards(f.read())
for i, board in enumerate(boards, 1):
    print(f"Board {i}:")
    for row in annotate(board):
        print("|" + row + "|")
    print()
