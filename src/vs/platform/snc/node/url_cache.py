"""
Disk cache for network reads made by the user's program.

Sculpt-n-Code reruns the whole file on a 100ms debounce, and every rerun is a
brand-new worker process, so a plain `urllib.request.urlopen(...)` in the source
would hit the network on every keystroke and block the visualization pipeline on
each round trip. This module patches `urlopen` so the body is fetched once and
then served from `.snc_url_cache/` next to the file being edited.

An entry stays valid only while the source line that made the call is unchanged,
so editing the line (the URL, or anything else on it) is how the user forces a
refetch. Each call site therefore gets its own entry: two lines reading the same
URL would otherwise invalidate each other's entry on every rerun. Failures are
cached the same way, so a half-typed URL is attempted once rather than once per
rerun.

The generated code stays ordinary Python: run outside Sculpt-n-Code it simply
fetches every time.
"""

import email.message
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
from typing import Any, Callable, Dict, Optional, Tuple

CACHE_DIR_NAME = '.snc_url_cache'

# Filename the runner compiles user code under; frames from that file are the
# user's own lines.
USER_CODE_FILENAME = '<string>'

# Bodies larger than this stream straight through to the caller instead of being
# buffered and written to disk.
MAX_CACHE_BYTES = 64 * 1024 * 1024

# Applied when the caller didn't ask for a timeout, so an unresponsive host can't
# wedge a rerun.
DEFAULT_TIMEOUT = 10.0

# A cached failure only holds for a moment: long enough that a half-typed URL
# isn't retried on every rerun, short enough that coming back online recovers
# without the user having to touch the line.
ERROR_TTL_SECONDS = 5.0

_CACHEABLE_SCHEMES = ('http://', 'https://')

# Stands in for the line hash in an entry key when the call didn't come from
# user code, so such a read still has a stable place on disk.
_UNKNOWN_LINE_KEY = 'unknownline'

_installed_urlopen: Optional[Callable[..., Any]] = None


def cache_dir_for(file_path: Optional[str], fallback_dir: Optional[str] = None) -> str:
    """Path of the cache directory for the file currently being edited."""
    directory = os.path.dirname(file_path) if file_path else ''
    if not directory:
        directory = fallback_dir or os.getcwd()
    return os.path.join(directory, CACHE_DIR_NAME)


def current_line_source(source_code: str) -> Optional[str]:
    """Source text of the innermost user line on the stack, stripped.

    Returns None when the call didn't come from user code, or when the runner's
    source snapshot doesn't cover the running line.
    """
    lines = source_code.splitlines()
    frame: Any = sys._getframe()
    while frame is not None:
        if frame.f_code.co_filename == USER_CODE_FILENAME:
            lineno = frame.f_lineno
            if 1 <= lineno <= len(lines):
                return lines[lineno - 1].strip()
            return None
        frame = frame.f_back
    return None


class CachedResponse:
    """Stands in for `http.client.HTTPResponse` over a cached body."""

    def __init__(self, body: bytes, status: int, headers: Dict[str, str], url: str):
        self._stream = io.BytesIO(body)
        self.status = status
        self.code = status
        self.url = url
        self.reason = ''
        message = email.message.Message()
        for name, value in headers.items():
            message[name] = value
        self.headers = message
        self.msg = message

    def read(self, amt: Optional[int] = None) -> bytes:
        return self._stream.read() if amt is None else self._stream.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._stream.readline(limit)

    def readlines(self, hint: int = -1):
        return self._stream.readlines(hint)

    def __iter__(self):
        return iter(self._stream)

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def info(self) -> email.message.Message:
        return self.headers

    def getheader(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.headers.get(name, default)

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> 'CachedResponse':
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()


def _url_of(url: Any) -> Optional[str]:
    """The URL string for a urlopen argument, or None if it isn't one we know."""
    if isinstance(url, str):
        return url
    full_url = getattr(url, 'full_url', None)
    return full_url if isinstance(full_url, str) else None


def _is_cacheable(url: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Optional[str]:
    """The URL to cache under, or None when the request must pass through."""
    url_str = _url_of(url)
    if not url_str or not url_str.lower().startswith(_CACHEABLE_SCHEMES):
        return None

    # A request body means this isn't a plain read.
    if kwargs.get('data') is not None or (args and args[0] is not None):
        return None
    if getattr(url, 'data', None) is not None:
        return None

    return url_str


def _url_key(url: str) -> str:
    """Filename prefix every entry for `url` shares."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16] + '-'


def _entry_paths(cache_dir: str, url: str, line_source: Optional[str]) -> Tuple[str, str]:
    """Body and metadata paths for the entry belonging to one call site.

    The calling line is part of the key because an entry is only valid while
    that line is unchanged: keyed on the URL alone, two lines reading the same
    URL would evict each other on every rerun. A call from outside user code has
    no line to key on, so all such calls share one entry per URL.
    """
    line_key = (hashlib.sha256(line_source.encode('utf-8')).hexdigest()[:16]
                if line_source is not None else _UNKNOWN_LINE_KEY)
    key = _url_key(url) + line_key
    return os.path.join(cache_dir, key + '.body'), os.path.join(cache_dir, key + '.json')


def _find_entry(cache_dir: str, url: str,
                line_source: Optional[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Body path and metadata of a still-valid entry for this read, or None."""
    body_path, meta_path = _entry_paths(cache_dir, url, line_source)
    meta = _read_meta(meta_path, url, line_source)
    if meta is not None:
        return body_path, meta
    if line_source is not None:
        return None

    # The call didn't come from user code, so there is no line to match on: any
    # entry for this URL, whichever line wrote it, will do.
    try:
        names = sorted(os.listdir(cache_dir))
    except OSError:
        return None
    prefix = _url_key(url)
    for name in names:
        if not name.startswith(prefix) or not name.endswith('.json'):
            continue
        candidate_path = os.path.join(cache_dir, name)
        meta = _read_meta(candidate_path, url, None)
        if meta is not None:
            return candidate_path[:-len('.json')] + '.body', meta
    return None


def _headers_to_dict(headers: Any) -> Dict[str, str]:
    try:
        return {str(name): str(value) for name, value in headers.items()}
    except Exception:
        return {}


def _read_meta(meta_path: str, url: str, line_source: Optional[str]) -> Optional[Dict[str, Any]]:
    """Metadata for a still-valid entry, or None if absent or superseded."""
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None

    if meta.get('url') != url:
        return None
    # An unknown line (call not made from user code) can't be checked, so trust
    # whatever was stored.
    if line_source is not None and meta.get('line_source') != line_source:
        return None
    if meta.get('error') and time.time() - (meta.get('fetched_at') or 0) > ERROR_TTL_SECONDS:
        return None
    return meta


def _error_from_meta(meta: Dict[str, Any], url: str) -> Exception:
    error = meta.get('error') or {}
    message = error.get('message') or 'cached failure'
    if error.get('type') == 'HTTPError':
        return urllib.error.HTTPError(url, error.get('status') or 0, message, email.message.Message(), None)
    return urllib.error.URLError(message)


def _write_entry(cache_dir: str, url: str, line_source: Optional[str], meta: Dict[str, Any],
                 body: Optional[bytes]) -> None:
    body_path, meta_path = _entry_paths(cache_dir, url, line_source)
    meta = {**meta, 'url': url, 'line_source': line_source, 'fetched_at': time.time()}
    try:
        os.makedirs(cache_dir, exist_ok=True)
        if body is None:
            if os.path.exists(body_path):
                os.remove(body_path)
        else:
            with open(body_path, 'wb') as f:
                f.write(body)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
    except OSError:
        # A cache we can't write is not a reason to fail the user's program.
        pass


def make_caching_urlopen(real_urlopen: Callable[..., Any],
                         cache_dir_provider: Callable[[], Optional[str]],
                         line_source_provider: Callable[[], Optional[str]]) -> Callable[..., Any]:
    """Wrap `real_urlopen` so plain reads are fetched once and reused."""

    def caching_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
        cache_dir = cache_dir_provider()
        cache_url = _is_cacheable(url, args, kwargs) if cache_dir else None

        if 'timeout' not in kwargs and len(args) < 2:
            kwargs['timeout'] = DEFAULT_TIMEOUT

        if not cache_url or cache_dir is None:
            return real_urlopen(url, *args, **kwargs)

        line_source = line_source_provider()
        entry = _find_entry(cache_dir, cache_url, line_source)
        if entry is not None:
            body_path, meta = entry
            if meta.get('error'):
                raise _error_from_meta(meta, cache_url)
            try:
                with open(body_path, 'rb') as f:
                    return CachedResponse(f.read(), meta.get('status') or 200,
                                          meta.get('headers') or {}, cache_url)
            except OSError:
                pass  # Body went missing; fall through and refetch.

        try:
            response = real_urlopen(url, *args, **kwargs)
        except urllib.error.HTTPError as e:
            _write_entry(cache_dir, cache_url, line_source,
                         {'error': {'type': 'HTTPError', 'status': e.code, 'message': str(e.reason or e)}}, None)
            raise
        except urllib.error.URLError as e:
            # `reason` is what URLError renders, so storing it keeps a replayed
            # failure textually identical to the original.
            _write_entry(cache_dir, cache_url, line_source,
                         {'error': {'type': 'URLError', 'message': str(e.reason)}}, None)
            raise
        # Anything else (a bad argument, say) isn't a network failure: it costs
        # nothing to reproduce and its type wouldn't survive the round trip.

        headers = _headers_to_dict(getattr(response, 'headers', None))
        try:
            declared_length = int(headers.get('Content-Length', ''))
        except ValueError:
            declared_length = -1
        if declared_length > MAX_CACHE_BYTES:
            return response

        body = response.read()
        if len(body) > MAX_CACHE_BYTES:
            return CachedResponse(body, getattr(response, 'status', 200) or 200, headers, cache_url)

        status = getattr(response, 'status', 200) or 200
        _write_entry(cache_dir, cache_url, line_source, {'status': status, 'headers': headers}, body)
        return CachedResponse(body, status, headers, cache_url)

    return caching_urlopen


def install(source_code_provider: Callable[[], str],
            cache_dir_provider: Callable[[], Optional[str]]) -> Callable[[], None]:
    """Patch `urllib.request.urlopen` to read through the cache.

    Must run before the user's imports so that `from urllib.request import
    urlopen` also binds the wrapper. Returns a function that undoes the patch.
    """
    global _installed_urlopen

    import urllib.request

    if _installed_urlopen is not None and urllib.request.urlopen is _installed_urlopen:
        return lambda: None

    original = urllib.request.urlopen
    _installed_urlopen = make_caching_urlopen(
        original,
        cache_dir_provider,
        lambda: current_line_source(source_code_provider()),
    )
    urllib.request.urlopen = _installed_urlopen  # type: ignore[assignment]

    def restore() -> None:
        global _installed_urlopen
        urllib.request.urlopen = original  # type: ignore[assignment]
        _installed_urlopen = None

    return restore
