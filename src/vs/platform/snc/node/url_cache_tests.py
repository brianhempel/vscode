"""
Tests for url_cache.py.

Run:
    python3 -m pytest src/vs/platform/snc/node/url_cache_tests.py -v
"""

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

import url_cache
from url_cache import (
    CACHE_DIR_NAME,
    cache_dir_for,
    install,
    make_caching_urlopen,
)


class _FakeResponse:
    """Stand-in for http.client.HTTPResponse as returned by urlopen."""

    def __init__(self, body: bytes, status: int = 200, headers=None, url: str = 'https://example.com/'):
        self._body = body
        self.status = status
        self.headers = dict(headers or {'Content-Type': 'text/plain'})
        self._url = url
        self.closed = False

    def read(self, amt=None):
        if amt is None:
            body, self._body = self._body, b''
            return body
        body, self._body = self._body[:amt], self._body[amt:]
        return body

    def geturl(self):
        return self._url

    def close(self):
        self.closed = True


class _FakeUrlopen:
    """Records calls so tests can assert how often the network was hit."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append((url, args, kwargs))
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def call_count(self):
        return len(self.calls)


class _CacheTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = os.path.join(self._tmp.name, CACHE_DIR_NAME)
        self.addCleanup(self._tmp.cleanup)

    def wrapper(self, real_urlopen):
        """Build a caching urlopen over this test's cache dir."""
        return make_caching_urlopen(real_urlopen, lambda: self.cache_dir)


class TestCacheDirFor(_CacheTestCase):
    """The cache lives beside the Python file being edited."""

    def test_uses_directory_of_the_edited_file(self):
        self.assertEqual(
            cache_dir_for('/home/me/proj/sub/weather.py', '/home/me/proj'),
            os.path.join('/home/me/proj/sub', CACHE_DIR_NAME))

    def test_falls_back_to_working_directory_when_no_file_path(self):
        self.assertEqual(
            cache_dir_for(None, '/home/me/proj'),
            os.path.join('/home/me/proj', CACHE_DIR_NAME))

    def test_falls_back_to_working_directory_when_file_path_is_blank(self):
        self.assertEqual(
            cache_dir_for('', '/home/me/proj'),
            os.path.join('/home/me/proj', CACHE_DIR_NAME))

    def test_ignores_a_bare_file_name_with_no_directory(self):
        self.assertEqual(
            cache_dir_for('weather.py', '/home/me/proj'),
            os.path.join('/home/me/proj', CACHE_DIR_NAME))


class TestCachingUrlopen(_CacheTestCase):
    """The wrapper fetches a URL once and serves every later read from disk."""

    def test_first_call_fetches_and_returns_the_body(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        urlopen = self.wrapper(real)

        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'hello')
        self.assertEqual(real.call_count, 1)

    def test_a_second_read_of_the_same_url_does_not_refetch(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'), _FakeResponse(b'CHANGED'))
        urlopen = self.wrapper(real)

        urlopen('https://example.com/a.txt')
        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'hello')
        self.assertEqual(real.call_count, 1)

    def test_cache_survives_across_processes(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        self.wrapper(real)('https://example.com/a.txt')

        # A fresh wrapper stands in for the next run's brand-new worker process.
        later = _FakeUrlopen(_FakeResponse(b'CHANGED'))
        self.assertEqual(self.wrapper(later)('https://example.com/a.txt').read(), b'hello')
        self.assertEqual(later.call_count, 0)

    def test_a_different_url_is_cached_separately(self):
        real = _FakeUrlopen(_FakeResponse(b'a'), _FakeResponse(b'b'))
        urlopen = self.wrapper(real)

        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'a')
        self.assertEqual(urlopen('https://example.com/b.txt').read(), b'b')
        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'a')
        self.assertEqual(real.call_count, 2)

    def test_every_read_of_one_url_shares_a_single_entry(self):
        # The URL is the whole key, so it does not matter how many lines read it
        # or how often they rerun: the network is touched once.
        real = _FakeUrlopen(_FakeResponse(b'first'), _FakeResponse(b'second'))
        urlopen = self.wrapper(real)

        for _ in range(4):
            self.assertEqual(urlopen('https://example.com/a.txt').read(), b'first')
        self.assertEqual(real.call_count, 1)
        self.assertEqual(
            len([f for f in os.listdir(self.cache_dir) if f.endswith('.body')]), 1)

    def test_writes_the_body_and_metadata_into_the_cache_dir(self):
        real = _FakeUrlopen(_FakeResponse(b'hello', status=201, headers={'Content-Type': 'text/csv'}))
        self.wrapper(real)('https://example.com/a.txt')

        bodies = sorted(f for f in os.listdir(self.cache_dir) if f.endswith('.body'))
        metas = sorted(f for f in os.listdir(self.cache_dir) if f.endswith('.json'))
        self.assertEqual(len(bodies), 1)
        self.assertEqual(len(metas), 1)

        with open(os.path.join(self.cache_dir, bodies[0]), 'rb') as f:
            self.assertEqual(f.read(), b'hello')
        with open(os.path.join(self.cache_dir, metas[0])) as f:
            meta = json.load(f)
        self.assertEqual(meta['url'], 'https://example.com/a.txt')
        self.assertEqual(meta['status'], 201)
        self.assertEqual(meta['headers']['Content-Type'], 'text/csv')


class TestCachedResponseShape(_CacheTestCase):
    """Cached responses stand in for HTTPResponse well enough for user code."""

    def _cached(self, body=b'line one\nline two\n', **kwargs):
        real = _FakeUrlopen(_FakeResponse(body, **kwargs))
        urlopen = self.wrapper(real)
        urlopen('https://example.com/a.txt')  # populate
        return urlopen('https://example.com/a.txt')

    def test_read_accepts_a_length(self):
        response = self._cached()
        self.assertEqual(response.read(4), b'line')
        self.assertEqual(response.read(), b' one\nline two\n')

    def test_works_as_a_context_manager(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        urlopen = self.wrapper(real)
        urlopen('https://example.com/a.txt')
        with urlopen('https://example.com/a.txt') as response:
            self.assertEqual(response.read(), b'hello')

    def test_exposes_status_in_both_spellings(self):
        response = self._cached(status=203)
        self.assertEqual(response.status, 203)
        self.assertEqual(response.getcode(), 203)

    def test_exposes_headers_case_insensitively(self):
        response = self._cached(headers={'Content-Type': 'text/plain; charset=utf-8'})
        self.assertEqual(response.headers['content-type'], 'text/plain; charset=utf-8')
        self.assertEqual(response.info()['Content-Type'], 'text/plain; charset=utf-8')

    def test_exposes_the_url(self):
        self.assertEqual(self._cached().geturl(), 'https://example.com/a.txt')

    def test_iterates_by_line(self):
        self.assertEqual(list(self._cached()), [b'line one\n', b'line two\n'])


class TestErrorCaching(_CacheTestCase):
    """Failures are cached too, so a broken URL is not retried every rerun."""

    def test_the_error_is_raised_to_the_caller(self):
        real = _FakeUrlopen(urllib.error.URLError('no such host'))
        with self.assertRaises(urllib.error.URLError):
            self.wrapper(real)('https://nope.example/a.txt')

    def test_a_repeat_run_reraises_without_refetching(self):
        real = _FakeUrlopen(urllib.error.URLError('no such host'))
        urlopen = self.wrapper(real)

        with self.assertRaises(urllib.error.URLError):
            urlopen('https://nope.example/a.txt')
        with self.assertRaises(urllib.error.URLError) as caught:
            urlopen('https://nope.example/a.txt')

        self.assertIn('no such host', str(caught.exception))
        self.assertEqual(real.call_count, 1)

    def test_the_reraised_message_matches_the_original(self):
        real = _FakeUrlopen(urllib.error.URLError('no such host'))
        urlopen = self.wrapper(real)

        with self.assertRaises(urllib.error.URLError) as first:
            urlopen('https://nope.example/a.txt')
        with self.assertRaises(urllib.error.URLError) as second:
            urlopen('https://nope.example/a.txt')

        self.assertEqual(str(second.exception), str(first.exception))

    def test_a_stale_failure_is_retried_so_transient_outages_recover(self):
        original_ttl = url_cache.ERROR_TTL_SECONDS
        url_cache.ERROR_TTL_SECONDS = 0
        self.addCleanup(lambda: setattr(url_cache, 'ERROR_TTL_SECONDS', original_ttl))

        real = _FakeUrlopen(urllib.error.URLError('offline'), _FakeResponse(b'back online'))
        urlopen = self.wrapper(real)

        with self.assertRaises(urllib.error.URLError):
            urlopen('https://example.com/a.txt')
        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'back online')

    def test_a_successful_entry_never_goes_stale(self):
        # Only failures carry a TTL; a body is kept until the cache dir is deleted.
        original_ttl = url_cache.ERROR_TTL_SECONDS
        url_cache.ERROR_TTL_SECONDS = 0
        self.addCleanup(lambda: setattr(url_cache, 'ERROR_TTL_SECONDS', original_ttl))

        real = _FakeUrlopen(_FakeResponse(b'hello'), _FakeResponse(b'CHANGED'))
        urlopen = self.wrapper(real)

        urlopen('https://example.com/a.txt')
        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'hello')
        self.assertEqual(real.call_count, 1)

    def test_failures_that_are_not_network_failures_are_not_cached(self):
        # A bad argument costs nothing to reproduce, and the exception type would
        # not survive a round trip through the cache.
        real = _FakeUrlopen(ValueError('unknown url type'))
        urlopen = self.wrapper(real)

        for _ in range(2):
            with self.assertRaises(ValueError):
                urlopen('https://example.com/a.txt')
        self.assertEqual(real.call_count, 2)

    def test_http_errors_keep_their_status_code(self):
        # HTTPError holds a file wrapper that complains if it's collected unclosed,
        # so each one this test creates gets closed rather than warned about.
        original = urllib.error.HTTPError('https://example.com/a.txt', 404, 'Not Found', {}, None)
        self.addCleanup(original.close)
        real = _FakeUrlopen(original)
        urlopen = self.wrapper(real)

        with self.assertRaises(urllib.error.HTTPError) as first:
            urlopen('https://example.com/a.txt')
        with self.assertRaises(urllib.error.HTTPError) as replayed:
            urlopen('https://example.com/a.txt')
        self.addCleanup(replayed.exception.close)

        self.assertIs(first.exception, original)
        self.assertEqual(replayed.exception.code, 404)
        self.assertEqual(real.call_count, 1)


class TestBypasses(_CacheTestCase):
    """Requests that are not cacheable pass straight through."""

    def test_posts_are_never_cached(self):
        real = _FakeUrlopen(_FakeResponse(b'a'), _FakeResponse(b'b'))
        urlopen = self.wrapper(real)

        self.assertEqual(urlopen('https://example.com/', data=b'x=1').read(), b'a')
        self.assertEqual(urlopen('https://example.com/', data=b'x=1').read(), b'b')
        self.assertEqual(real.call_count, 2)

    def test_non_http_schemes_are_never_cached(self):
        real = _FakeUrlopen(_FakeResponse(b'a'), _FakeResponse(b'b'))
        urlopen = self.wrapper(real)

        self.assertEqual(urlopen('file:///tmp/a.txt').read(), b'a')
        self.assertEqual(urlopen('file:///tmp/a.txt').read(), b'b')
        self.assertEqual(real.call_count, 2)

    def test_oversized_responses_stream_through_uncached(self):
        headers = {'Content-Length': str(url_cache.MAX_CACHE_BYTES + 1)}
        first = _FakeResponse(b'huge', headers=headers)
        real = _FakeUrlopen(first, _FakeResponse(b'huge', headers=headers))
        urlopen = self.wrapper(real)

        self.assertIs(urlopen('https://example.com/big.bin'), first)
        urlopen('https://example.com/big.bin')
        self.assertEqual(real.call_count, 2)
        self.assertFalse(os.path.isdir(self.cache_dir))

    def test_a_missing_cache_dir_is_not_fatal(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'), _FakeResponse(b'hello again'))
        urlopen = make_caching_urlopen(real, lambda: None)

        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'hello')
        self.assertEqual(urlopen('https://example.com/a.txt').read(), b'hello again')


class TestRequestObjects(_CacheTestCase):
    """urlopen also accepts a Request; its URL is what identifies the entry."""

    def test_request_objects_are_cached_by_their_url(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'), _FakeResponse(b'CHANGED'))
        urlopen = self.wrapper(real)

        urlopen(urllib.request.Request('https://example.com/a.txt'))
        response = urlopen(urllib.request.Request('https://example.com/a.txt'))
        self.assertEqual(response.read(), b'hello')
        self.assertEqual(real.call_count, 1)

    def test_a_request_with_a_body_is_not_cached(self):
        real = _FakeUrlopen(_FakeResponse(b'a'), _FakeResponse(b'b'))
        urlopen = self.wrapper(real)

        urlopen(urllib.request.Request('https://example.com/', data=b'x=1'))
        urlopen(urllib.request.Request('https://example.com/', data=b'x=1'))
        self.assertEqual(real.call_count, 2)


class TestTimeout(_CacheTestCase):
    """A hung host must not wedge the rerun pipeline."""

    def test_a_default_timeout_is_supplied(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        self.wrapper(real)('https://example.com/a.txt')

        self.assertEqual(real.calls[0][2]['timeout'], url_cache.DEFAULT_TIMEOUT)

    def test_an_explicit_timeout_wins(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        self.wrapper(real)('https://example.com/a.txt', timeout=42)

        self.assertEqual(real.calls[0][2]['timeout'], 42)

    def test_a_positional_timeout_is_left_alone(self):
        real = _FakeUrlopen(_FakeResponse(b'hello'))
        self.wrapper(real)('https://example.com/a.txt', None, 42)

        self.assertEqual(real.calls[0][1], (None, 42))
        self.assertNotIn('timeout', real.calls[0][2])


class TestInstall(unittest.TestCase):
    """Installing patches urllib.request.urlopen in place."""

    def test_install_patches_and_restores(self):
        original = urllib.request.urlopen
        restore = install(lambda: None)
        self.addCleanup(restore)

        self.assertIsNot(urllib.request.urlopen, original)
        restore()
        self.assertIs(urllib.request.urlopen, original)

    def test_installing_twice_does_not_double_wrap(self):
        original = urllib.request.urlopen
        restore = install(lambda: None)
        self.addCleanup(restore)
        patched = urllib.request.urlopen

        install(lambda: None)
        self.assertIs(urllib.request.urlopen, patched)

        restore()
        self.assertIs(urllib.request.urlopen, original)


if __name__ == '__main__':
    unittest.main()
