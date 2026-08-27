"""
The user program's stdin/stdout/stderr, replayed across reruns.

Sculpt-n-Code reruns the whole file on a 100ms debounce in a brand-new worker
each time, so a program that reads stdin can't be handed a live pipe: there is
nobody at the other end, and the worker's real stdin is already the runner's
command channel. Instead the editor owns a stdin *document* — literally what the
user would have typed at a terminal — and ships it in with every run. This
module replays that text through a `sys.stdin` stand-in, so `input()`,
`sys.stdin.read()` and `for line in sys.stdin:` all behave as if the session had
been typed live, and behave the same way on every rerun.

A read that runs off the end of the recorded text is not an error, it's the
program waiting for the user. It raises `NeedsInput`, which unwinds the run
cleanly so the editor can show the prompt and let the user type. `NeedsInput`
subclasses `BaseException` so a user's `except Exception:` can't swallow it. (A
bare `except:` still can, and the program then carries on with the read
unsatisfied — an acceptable corner.)

Whether the stream *ends* is a property of the document too: the editor sends
`stdin_eof` for a document carrying an end-of-stream marker. Without it, a read
that only completes at end of stream can never complete, so it starves rather
than silently returning short.

Output goes back out over the same NDJSON channel as everything else rather than
being buffered into the run's result, so a slow loop's prints appear as they
happen. Each chunk carries the number of stdin characters consumed at the moment
it was written, which is what lets the editor place it between the right two
lines of the stdin document.

Run outside Sculpt-n-Code the program is ordinary Python: nothing here is
installed and stdin is the real one.
"""

from contextlib import contextmanager
from io import TextIOBase
from typing import Callable, Iterator, List, Optional

import sys

# Output below this size waits for the end of the run (or the next stdin read)
# rather than being emitted immediately. The common case is then one extra
# NDJSON line for the whole run, while a slow loop still gets liveness.
FLUSH_THRESHOLD = 4096

# A runaway `while True: print(x)` would otherwise flood the message channel and
# wedge the editor. It still runs to the usual timeout; it just stops being
# listened to.
MAX_OUTPUT_CHARS = 256 * 1024

TRUNCATION_NOTICE = '\n[output truncated]\n'

# Callback receiving each chunk: (stream_name, text, stdin_offset).
Emit = Callable[[str, str, int], None]


class NeedsInput(BaseException):
    """The program read past the end of the recorded stdin.

    `kind` is `'line'` when more typing would satisfy the read, or `'eof'` when
    only ending the stream will (`sys.stdin.read()`, iteration to exhaustion).
    The editor uses it to decide whether to suggest the end-of-stream marker.
    """

    def __init__(self, kind: str = 'line') -> None:
        super().__init__('Clickacode: waiting for input')
        self.kind = kind


class _OutStream(TextIOBase):
    """stdout or stderr.

    Both share the session's buffer rather than keeping their own, so that
    writes alternating between them keep their relative order — a transcript
    that reordered a traceback around the prints surrounding it would be
    actively misleading.
    """

    def __init__(self, name: str, session: 'StdStreams') -> None:
        super().__init__()
        self._name = name
        self._session = session

    # -- TextIOBase contract ------------------------------------------------

    @property
    def encoding(self) -> str:
        return 'utf-8'

    @property
    def errors(self) -> str:
        return 'strict'

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return False

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            raise TypeError(f'write() argument must be str, not {type(s).__name__}')
        if s:
            self._session._append(self._name, s)
        return len(s)

    def writelines(self, lines) -> None:  # type: ignore[override]
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._session.flush()


class _InStream(TextIOBase):
    """stdin, replayed from the text the editor recorded."""

    def __init__(self, session: 'StdStreams', text: str, eof: bool) -> None:
        super().__init__()
        self._session = session
        self._text = text
        self._eof = eof
        self.pos = 0

    # -- TextIOBase contract ------------------------------------------------

    @property
    def encoding(self) -> str:
        return 'utf-8'

    @property
    def errors(self) -> str:
        return 'strict'

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return False

    def read(self, size: Optional[int] = -1) -> str:
        # Anything already printed belongs *before* this read, so it has to go
        # out carrying the pre-read offset.
        self._session.flush()

        if size is None or size < 0:
            if not self._eof:
                # There may be more to come, so "everything" isn't knowable yet.
                raise NeedsInput('eof')
            out = self._text[self.pos:]
            self.pos = len(self._text)
            return out

        end = self.pos + size
        if end > len(self._text) and not self._eof:
            # More typing fills this; ending the stream would only shorten it.
            raise NeedsInput('line')
        out = self._text[self.pos:end]
        self.pos = min(end, len(self._text))
        return out

    def readline(self, size: Optional[int] = -1) -> str:  # type: ignore[override]
        self._session.flush()

        newline = self._text.find('\n', self.pos)
        if newline >= 0:
            end = newline + 1
        elif self._eof:
            end = len(self._text)
        else:
            # A trailing partial line isn't a line yet — the user may still be
            # typing it.
            raise NeedsInput('line')

        if size is not None and size >= 0:
            end = min(end, self.pos + size)
        out = self._text[self.pos:end]
        self.pos = end
        return out

    def readlines(self, hint: Optional[int] = -1) -> List[str]:  # type: ignore[override]
        return self.read().splitlines(keepends=True)

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class StdStreams:
    """One run's worth of replayed stdin and captured stdout/stderr."""

    def __init__(self, stdin_text: str = '', stdin_eof: bool = True, emit: Optional[Emit] = None) -> None:
        self._emit = emit
        self._emitted = 0
        self._truncated = False
        self._saved: Optional[tuple] = None
        # Runs of same-stream writes, oldest first: [stream_name, [text, ...]].
        self._pending: List[list] = []
        self._pending_len = 0

        self.stdin = _InStream(self, stdin_text, stdin_eof)
        self.stdout = _OutStream('stdout', self)
        self.stderr = _OutStream('stderr', self)

    @property
    def consumed(self) -> int:
        """Characters of the stdin document read so far."""
        return self.stdin.pos

    def _append(self, name: str, text: str) -> None:
        if self._pending and self._pending[-1][0] == name:
            self._pending[-1][1].append(text)
        else:
            self._pending.append([name, [text]])
        self._pending_len += len(text)
        if self._pending_len >= FLUSH_THRESHOLD:
            self.flush()

    def flush(self) -> None:
        """Push buffered output out, one chunk per run of same-stream writes."""
        if not self._pending:
            return
        pending, self._pending, self._pending_len = self._pending, [], 0
        for name, parts in pending:
            self._emit_chunk(name, ''.join(parts))

    def _emit_chunk(self, name: str, text: str) -> None:
        if self._emit is None or self._truncated:
            return

        room = MAX_OUTPUT_CHARS - self._emitted
        if len(text) >= room:
            text = text[:room] + TRUNCATION_NOTICE
            self._truncated = True

        self._emitted += len(text)
        try:
            self._emit(name, text, self.stdin.pos)
        except Exception:
            # Never let a reporting failure break the user's program.
            pass

    # -- installation -------------------------------------------------------

    def install(self) -> 'StdStreams':
        if self._saved is None:
            self._saved = (sys.stdin, sys.stdout, sys.stderr)
            sys.stdin, sys.stdout, sys.stderr = self.stdin, self.stdout, self.stderr
        return self

    def restore(self) -> None:
        if self._saved is None:
            return
        self.flush()
        sys.stdin, sys.stdout, sys.stderr = self._saved
        self._saved = None

    @contextmanager
    def installed(self) -> Iterator['StdStreams']:
        self.install()
        try:
            yield self
        finally:
            self.restore()


def install(stdin_text: str = '', stdin_eof: bool = True, emit: Optional[Emit] = None) -> StdStreams:
    """Replace `sys.stdin`/`stdout`/`stderr` for the duration of a run.

    The returned session carries `restore()`, which puts the real streams back
    and flushes whatever the program wrote last.
    """
    return StdStreams(stdin_text, stdin_eof, emit).install()
