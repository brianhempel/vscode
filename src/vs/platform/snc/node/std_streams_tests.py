"""
Tests for std_streams.py.

Run:
    python3 -m pytest src/vs/platform/snc/node/std_streams_tests.py -v
"""

import sys
import unittest

import std_streams
from std_streams import (
    MAX_OUTPUT_CHARS,
    NeedsInput,
    StdStreams,
    install,
)


class _Recorder:
    """Collects the chunks a session emits, in order."""

    def __init__(self):
        self.chunks = []

    def __call__(self, stream, text, stdin_offset):
        self.chunks.append((stream, text, stdin_offset))

    @property
    def text(self):
        return ''.join(text for _, text, _ in self.chunks)

    def text_of(self, stream):
        return ''.join(t for s, t, _ in self.chunks if s == stream)

    @property
    def offsets(self):
        return [offset for _, _, offset in self.chunks]


def session(stdin_text='', stdin_eof=True):
    """A session that isn't installed over the real sys streams."""
    recorder = _Recorder()
    return StdStreams(stdin_text, stdin_eof, recorder), recorder


class TestReplayingStdin(unittest.TestCase):

    def test_readline_returns_each_line_with_its_newline(self):
        s, _ = session('Brian\n30\n')
        self.assertEqual(s.stdin.readline(), 'Brian\n')
        self.assertEqual(s.stdin.readline(), '30\n')

    def test_readline_at_eof_returns_empty_string(self):
        s, _ = session('Brian\n', stdin_eof=True)
        s.stdin.readline()
        self.assertEqual(s.stdin.readline(), '')

    def test_input_reads_a_line_and_strips_the_newline(self):
        s, _ = session('Brian\n30\n')
        with s.installed():
            self.assertEqual(input(), 'Brian')
            self.assertEqual(input(), '30')

    def test_input_writes_its_prompt_to_stdout(self):
        s, rec = session('Brian\n')
        with s.installed():
            input('Name? ')
        s.flush()
        self.assertEqual(rec.text_of('stdout'), 'Name? ')

    def test_input_raises_eof_error_past_the_end_when_the_stream_ends(self):
        s, _ = session('Brian\n', stdin_eof=True)
        with s.installed():
            input()
            with self.assertRaises(EOFError):
                input()

    def test_read_to_end_returns_the_whole_remaining_stream(self):
        s, _ = session('a\nb\n', stdin_eof=True)
        s.stdin.readline()
        self.assertEqual(s.stdin.read(), 'b\n')

    def test_bounded_read_returns_exactly_that_many_characters(self):
        s, _ = session('abcdef', stdin_eof=True)
        self.assertEqual(s.stdin.read(3), 'abc')
        self.assertEqual(s.stdin.read(3), 'def')

    def test_iterating_stdin_yields_lines_then_stops(self):
        s, _ = session('a\nb\nc\n', stdin_eof=True)
        self.assertEqual(list(s.stdin), ['a\n', 'b\n', 'c\n'])

    def test_readlines_returns_every_line(self):
        s, _ = session('a\nb\n', stdin_eof=True)
        self.assertEqual(s.stdin.readlines(), ['a\n', 'b\n'])

    def test_a_final_line_without_a_newline_is_still_read(self):
        s, _ = session('Brian', stdin_eof=True)
        self.assertEqual(s.stdin.readline(), 'Brian')

    def test_stdin_is_not_a_tty(self):
        s, _ = session('')
        self.assertFalse(s.stdin.isatty())


class TestStarvedReads(unittest.TestCase):
    """Reading past the end of an unterminated stream stops the run."""

    def test_readline_past_the_end_raises_needs_input(self):
        s, _ = session('Brian\n', stdin_eof=False)
        s.stdin.readline()
        with self.assertRaises(NeedsInput) as caught:
            s.stdin.readline()
        self.assertEqual(caught.exception.kind, 'line')

    def test_input_past_the_end_raises_needs_input_rather_than_eof_error(self):
        s, _ = session('', stdin_eof=False)
        with s.installed():
            with self.assertRaises(NeedsInput):
                input('Name? ')

    def test_a_partial_last_line_is_not_returned_until_the_stream_ends(self):
        # "Bri" with more possibly still to be typed is not a line yet.
        s, _ = session('Bri', stdin_eof=False)
        with self.assertRaises(NeedsInput):
            s.stdin.readline()

    def test_read_to_end_raises_needs_input_when_the_stream_has_not_ended(self):
        s, _ = session('a\nb\n', stdin_eof=False)
        with self.assertRaises(NeedsInput) as caught:
            s.stdin.read()
        self.assertEqual(caught.exception.kind, 'eof')

    def test_iterating_stdin_raises_needs_input_when_the_stream_has_not_ended(self):
        s, _ = session('a\n', stdin_eof=False)
        it = iter(s.stdin)
        self.assertEqual(next(it), 'a\n')
        with self.assertRaises(NeedsInput):
            next(it)

    def test_a_bounded_read_that_cannot_be_filled_raises_needs_input(self):
        s, _ = session('ab', stdin_eof=False)
        with self.assertRaises(NeedsInput) as caught:
            s.stdin.read(5)
        # More typing satisfies this, so it asks for a line rather than EOF.
        self.assertEqual(caught.exception.kind, 'line')

    def test_needs_input_survives_a_user_except_exception(self):
        # A `except Exception:` in the user's program must not swallow the
        # signal that the run is waiting on input.
        s, _ = session('', stdin_eof=False)
        with self.assertRaises(NeedsInput):
            try:
                s.stdin.readline()
            except Exception:
                self.fail('NeedsInput must not be catchable as Exception')

    def test_needs_input_is_not_an_exception_subclass(self):
        self.assertTrue(issubclass(NeedsInput, BaseException))
        self.assertFalse(issubclass(NeedsInput, Exception))

    def test_the_prompt_is_emitted_before_the_starved_read_raises(self):
        # Without this the user never sees what the program is asking for.
        s, rec = session('', stdin_eof=False)
        with s.installed():
            try:
                input('Name? ')
            except NeedsInput:
                pass
        self.assertEqual(rec.text_of('stdout'), 'Name? ')


class TestConsumedOffsets(unittest.TestCase):
    """Every chunk records how much stdin had been eaten when it was written."""

    def test_consumed_starts_at_zero_and_tracks_reads(self):
        s, _ = session('Brian\n30\n')
        self.assertEqual(s.consumed, 0)
        s.stdin.readline()
        self.assertEqual(s.consumed, 6)
        s.stdin.readline()
        self.assertEqual(s.consumed, 9)

    def test_consumed_tracks_partial_reads(self):
        s, _ = session('abcdef')
        s.stdin.read(2)
        self.assertEqual(s.consumed, 2)

    def test_a_starved_read_consumes_nothing(self):
        s, _ = session('Bri', stdin_eof=False)
        try:
            s.stdin.readline()
        except NeedsInput:
            pass
        self.assertEqual(s.consumed, 0)

    def test_chunks_carry_the_offset_at_the_time_they_were_written(self):
        s, rec = session('Brian\n30\n')
        with s.installed():
            print('Name? ', end='')
            input()
            print('Age? ', end='')
            input()
            print('done')
        s.flush()
        self.assertEqual(rec.chunks, [
            ('stdout', 'Name? ', 0),
            ('stdout', 'Age? ', 6),
            ('stdout', 'done\n', 9),
        ])

    def test_output_is_flushed_before_a_read_so_the_ordering_survives(self):
        # The prompt must land at the offset before the read, not after it.
        s, rec = session('Brian\n')
        s.stdout.write('Name? ')
        s.stdin.readline()
        s.stdout.write('hi')
        s.flush()
        self.assertEqual(rec.offsets, [0, 6])


class TestOutputChunking(unittest.TestCase):

    def test_nothing_is_emitted_until_flush_for_small_output(self):
        s, rec = session()
        s.stdout.write('hello')
        self.assertEqual(rec.chunks, [])
        s.flush()
        self.assertEqual(rec.text_of('stdout'), 'hello')

    def test_flushing_an_empty_buffer_emits_nothing(self):
        s, rec = session()
        s.flush()
        s.flush()
        self.assertEqual(rec.chunks, [])

    def test_a_large_write_is_emitted_without_waiting_for_the_end(self):
        s, rec = session()
        s.stdout.write('x' * (std_streams.FLUSH_THRESHOLD + 1))
        self.assertNotEqual(rec.chunks, [])

    def test_stdout_and_stderr_are_tagged_separately(self):
        s, rec = session()
        with s.installed():
            print('out')
            print('err', file=sys.stderr)
        s.flush()
        self.assertEqual(rec.text_of('stdout'), 'out\n')
        self.assertEqual(rec.text_of('stderr'), 'err\n')

    def test_stdout_and_stderr_interleave_in_write_order(self):
        s, rec = session()
        s.stdout.write('a')
        s.stderr.write('b')
        s.stdout.write('c')
        s.flush()
        self.assertEqual([(stream, text) for stream, text, _ in rec.chunks],
                         [('stdout', 'a'), ('stderr', 'b'), ('stdout', 'c')])

    def test_explicit_stream_flush_emits_immediately(self):
        s, rec = session()
        s.stdout.write('partial')
        s.stdout.flush()
        self.assertEqual(rec.text_of('stdout'), 'partial')

    def test_output_is_capped_and_says_so(self):
        s, rec = session()
        s.stdout.write('x' * (MAX_OUTPUT_CHARS + 5000))
        s.stdout.write('never seen')
        s.flush()
        emitted = rec.text_of('stdout')
        self.assertLessEqual(len(emitted), MAX_OUTPUT_CHARS + len(std_streams.TRUNCATION_NOTICE))
        self.assertIn('truncated', emitted)
        self.assertNotIn('never seen', emitted)

    def test_the_truncation_notice_is_only_emitted_once(self):
        s, rec = session()
        s.stdout.write('x' * (MAX_OUTPUT_CHARS + 1))
        s.stdout.write('y' * 100)
        s.stdout.write('z' * 100)
        s.flush()
        self.assertEqual(rec.text.count(std_streams.TRUNCATION_NOTICE), 1)

    def test_the_cap_is_shared_across_both_streams(self):
        s, rec = session()
        s.stdout.write('x' * MAX_OUTPUT_CHARS)
        s.stderr.write('should not appear')
        s.flush()
        self.assertNotIn('should not appear', rec.text)

    def test_stdout_is_not_a_tty(self):
        s, _ = session()
        self.assertFalse(s.stdout.isatty())

    def test_stdout_reports_an_encoding(self):
        # Libraries probe this; None would break them.
        s, _ = session()
        self.assertEqual(s.stdout.encoding, 'utf-8')

    def test_writing_a_non_string_is_rejected_the_way_a_text_stream_would(self):
        s, _ = session()
        with self.assertRaises(TypeError):
            s.stdout.write(b'bytes')


class TestInstall(unittest.TestCase):

    def test_install_swaps_the_three_streams_and_restore_puts_them_back(self):
        original = (sys.stdin, sys.stdout, sys.stderr)
        s = install('a\n', True, _Recorder())
        try:
            self.assertIs(sys.stdin, s.stdin)
            self.assertIs(sys.stdout, s.stdout)
            self.assertIs(sys.stderr, s.stderr)
        finally:
            s.restore()
        self.assertEqual((sys.stdin, sys.stdout, sys.stderr), original)

    def test_restore_flushes_pending_output(self):
        rec = _Recorder()
        s = install('', True, rec)
        try:
            print('buffered', end='')
        finally:
            s.restore()
        self.assertEqual(rec.text_of('stdout'), 'buffered')

    def test_restore_is_idempotent(self):
        s = install('', True, _Recorder())
        s.restore()
        s.restore()
        self.assertIsNot(sys.stdout, s.stdout)

    def test_installed_restores_even_when_the_body_raises(self):
        original = sys.stdout
        s, _ = session()
        with self.assertRaises(ValueError):
            with s.installed():
                raise ValueError('boom')
        self.assertIs(sys.stdout, original)


if __name__ == '__main__':
    unittest.main()
