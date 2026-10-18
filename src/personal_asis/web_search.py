"""Bounded public search/read adapter. Never receives account credentials or notes.

No retries. Origin DNS is resolved once per hop and the TLS socket is pinned to
that public address. Jina receives inert HTML, never a URL to navigate remotely.
"""
from datetime import datetime, timezone, timedelta
from html import escape
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import selectors
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit, urljoin, parse_qsl


MAX_RESPONSE = 262144


class WebError(ValueError):
    """Allowlisted diagnostic; no remote response, query or URL in exceptions."""


class WebProvider(Protocol):
    def search_web(self, query, max_results=5, recency_days=None): ...
    def fetch_web(self, url, max_chars=2400): ...


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def public_query(value):
    # Explicit caller approval is also required by the Agent host. This is a
    # deterministic deny gate, not a claim that automatic PII detection is total.
    from .data_policy import exclusion_reason
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 240
            or value != ' '.join(value.split()) or exclusion_reason('', value)
            or re.search(r'我|本人|日记|病历|健康记录|私人|私密|my\s|\bI\b|@|https?://|[\\/]|'
                         r'(?i:cookie|token|password|secret|api.?key)|\d{7,}', value)):
        raise WebError('web_query_privacy_denied')
    return value


def url_shape(url):
    try:
        p = urlsplit(url)
        if (not isinstance(url, str) or len(url) > 2000 or not url.isascii()
                or any(ord(c) < 33 or ord(c) == 127 for c in url) or '\\' in url
                or p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or p.fragment or '%' in p.netloc
                or '.' not in p.hostname or p.hostname.endswith(('.', '.local', '.internal', '.localhost', '.lan', '.home'))
                or any(re.search(r'(?i)token|auth|key|secret|session|cookie|password', k)
                       for k, _ in parse_qsl(p.query))):
            raise ValueError()
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise WebError('web_public_https_required') from None
    return url


def bounded_process(argv, timeout=25, limit=MAX_RESPONSE):
    """Bound both subprocess streams while running, rather than capture then check."""
    started = time.monotonic()
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        out = bytearray()
        size = 0
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            selector.register(proc.stderr, selectors.EVENT_READ)
            try:
                while selector.get_map():
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise WebError('web_timeout_unknown_no_retry')
                    for key, _ in selector.select(min(remaining, .2)):
                        chunk = key.fileobj.read1(8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(chunk)
                        if size > limit:
                            raise WebError('web_response_too_large_unknown_no_retry')
                        if key.fileobj is proc.stdout:
                            out.extend(chunk)
                if proc.wait(timeout=max(.01, timeout - (time.monotonic() - started))):
                    raise WebError('web_backend_failed_unknown_no_retry')
            except BaseException:
                proc.kill()
                proc.wait()
                raise
    return bytes(out)


def resolve(host):
    # libc DNS has no portable deadline; isolate it in a disposable child.
    raw = bounded_process([sys.executable, '-c',
        'import socket,json,sys; print(json.dumps(sorted({a[4][0] for a in socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)})))',
        host], timeout=4, limit=8192)
    return json.loads(raw)


def public_addresses(url, resolver=None):
    url_shape(url)
    try:
        values = (resolver or resolve)(urlsplit(url).hostname)
        if not values or len(values) > 64 or any(not ipaddress.ip_address(a).is_global for a in values):
            raise ValueError()
        return values
    except (ValueError, OSError):
        raise WebError('web_dns_nonpublic_or_unavailable') from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        self._deadline_socket = sock
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            self._deadline_socket = self.sock
        except BaseException:
            sock.close()
            raise


class PublicHTTP:
    def __init__(self, resolver=resolve, connection=PinnedHTTPS):
        self.resolver, self.connection = resolver, connection

    def request(self, url, *, body=None, timeout=12):
        deadline = time.monotonic() + timeout
        current = [None]
        def interrupt():
            # Inactivity timeouts alone do not stop trickled response headers.
            # Keep the underlying socket even when HTTP/1.0 hands its file to
            # the response and clears connection.sock.
            connection = current[0]
            sock = getattr(connection, '_deadline_socket', None) or getattr(connection, 'sock', None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        timer = threading.Timer(timeout, interrupt)
        timer.daemon = True
        timer.start()
        try:
            return self._request(url, body, deadline, current)
        finally:
            timer.cancel()

    def _request(self, url, body, deadline, current):
        for hop in range(4):
            addresses = public_addresses(url, self.resolver)
            p = urlsplit(url)
            left = deadline - time.monotonic()
            if left <= 0:
                raise WebError('web_timeout_unknown_no_retry')
            connection = self.connection(p.hostname, addresses[0], left)
            current[0] = connection
            try:
                if time.monotonic() >= deadline:
                    raise WebError('web_timeout_unknown_no_retry')
                headers = {'Accept': 'application/json' if body else 'text/html,text/plain',
                           'Accept-Encoding': 'identity', 'User-Agent': 'PersonalAsis-PublicReader/1'}
                if body is not None:
                    if len(body) > MAX_RESPONSE:
                        raise WebError('web_request_too_large')
                    headers['Content-Type'] = 'application/json'
                connection.request('POST' if body is not None else 'GET',
                                   p.path or '/' if not p.query else (p.path or '/') + '?' + p.query,
                                   body=body, headers=headers)
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    if body is not None or hop == 3:
                        raise WebError('web_redirect_denied')
                    url = urljoin(url, response.getheader('Location', ''))
                    # Validate before the next request, including DNS for every hop.
                    public_addresses(url, self.resolver)
                    continue
                if response.status == 429:
                    raise WebError('web_rate_limited_no_retry')
                if response.status != 200:
                    raise WebError('web_http_unavailable_no_retry')
                if response.getheader('Content-Encoding', 'identity') not in ('identity', ''):
                    raise WebError('web_compressed_response_denied')
                content_type = response.getheader('Content-Type', '').lower()
                if not any(t in content_type for t in ('text/html', 'text/plain', 'application/json', 'application/xhtml+xml')):
                    raise WebError('web_content_type_unsupported')
                raw = bytearray()
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise WebError('web_timeout_unknown_no_retry')
                    if connection.sock:
                        connection.sock.settimeout(left)
                    chunk = response.read1(min(8192, MAX_RESPONSE + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE:
                        raise WebError('web_response_too_large_unknown_no_retry')
                return url, bytes(raw), content_type
            except (OSError, http.client.HTTPException):
                raise WebError('web_transport_unknown_no_retry') from None
            finally:
                connection.close()


class InertHTML(HTMLParser):
    """Only text and structural tags survive; no URLs, scripts or subresources."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template', 'noscript'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if not self.skip and tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'section', 'article'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3') and not self.skip:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.in_title:
                self.title_parts.append(data)


def parse_exa(value):
    """Structured JSON first; legacy MCP labelled records only, never URL scan."""
    if isinstance(value, dict):
        if value.get('isError') or value.get('error'):
            raise WebError('web_search_unavailable_or_rate_limited')
        if 'structuredContent' in value:
            return parse_exa(value['structuredContent'])
        if isinstance(value.get('results'), list):
            return value['results']
        if isinstance(value.get('content'), list):
            result = []
            for block in value['content']:
                if block.get('type') == 'text':
                    result.extend(parse_exa(block.get('text', '')))
            return result
    if isinstance(value, str):
        try:
            return parse_exa(json.loads(value))
        except json.JSONDecodeError:
            result = []
            for record in re.split(r'(?m)(?=^Title: )', value):
                head, _, body = record.partition('\nText:')
                fields = dict(re.findall(r'(?m)^(Title|URL|Published Date|Author):\s*([^\n]+)$', head))
                if fields.get('Title') and fields.get('URL'):
                    result.append({'title': fields['Title'], 'url': fields['URL'],
                                   'publishedDate': fields.get('Published Date'), 'text': body.strip()})
            if result:
                return result
    raise WebError('web_search_schema_unsupported')


class ExaJinaProvider:
    name = 'exa-mcporter+jina-inert-html-v1'

    def __init__(self, runner=bounded_process, http=None):
        self.runner, self.http = runner, http or PublicHTTP()

    def search_web(self, query, max_results=5, recency_days=None):
        public_query(query)
        if type(max_results) is not int or not 1 <= max_results <= 5:
            raise WebError('web_invalid_search_limit')
        if recency_days is not None and (type(recency_days) is not int or not 1 <= recency_days <= 365):
            raise WebError('web_invalid_recency')
        command = shutil.which('mcporter')
        if not command:
            raise WebError('web_search_backend_unavailable')
        args = {'query': query, 'objective': 'Find public primary sources relevant to this public query; return source URLs and reported publication dates.',
                'numResults': max_results}
        raw = self.runner([command, 'call', 'exa.web_search_exa', '--args', json.dumps(args), '--output', 'json'])
        rows = parse_exa(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
        results, seen, gaps = [], set(), []
        now = datetime.now(timezone.utc)
        for row in rows[:20]:
            try:
                url = url_shape(row['url'])
                if url in seen:
                    continue
                date = row.get('publishedDate') or row.get('published_at')
                parsed = datetime.fromisoformat(date.replace('Z', '+00:00')) if date else None
                if parsed and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if recency_days and (not parsed or not now - timedelta(days=recency_days) <= parsed <= now):
                    gaps.append('unknown_or_outside_reported_publication_window')
                    continue
                results.append({'url': url, 'title': str(row.get('title', ''))[:160],
                    'excerpt': str(row.get('text') or row.get('snippet') or '')[:600],
                    'source_type': 'public_web', 'content_kind': 'search_snippet', 'content_completeness': 'summary',
                    'published_at': date, 'publication_date_status': 'provider_reported_unverified' if date else 'unknown',
                    'fetched_at': utcnow(), 'author': str(row.get('author') or '')[:160] or None})
                seen.add(url)
            except (ValueError, KeyError, TypeError, AttributeError):
                gaps.append('result_metadata_invalid_or_target_denied')
        return {'status': 'ok' if results else 'no_results', 'results': results[:max_results],
                'gaps': sorted(set(gaps)), 'recency_policy': 'local_filter_reported_dates_only',
                'provider': self.name, 'billing': 'provider_cost_unknown'}

    def fetch_web(self, url, max_chars=2400):
        if type(max_chars) is not int or not 200 <= max_chars <= 4000:
            raise WebError('web_invalid_read_limit')
        final, raw, kind = self.http.request(url)
        parser = InertHTML()
        text = raw.decode('utf-8', 'replace')
        if 'html' in kind:
            parser.feed(text)
            text = ''.join(parser.parts).strip()
        title = ''.join(parser.title_parts).strip()[:160] or urlsplit(final).hostname
        if len(text.strip()) < 40:
            raise WebError('web_body_unavailable_or_incomplete')
        # Post a bounded inert document, without a base URL, to prevent remote
        # navigation/redirects and subresource loads at the Reader service.
        inert = '<html><body><pre>' + escape(text[:12000]) + '</pre></body></html>'
        body = json.dumps({'html': inert}).encode()
        reader_status = 'jina_inert_html'
        try:
            _, output, _ = self.http.request('https://r.jina.ai/', body=body)
            value = json.loads(output)
            converted = value['data']['content']
            if not isinstance(converted, str) or len(converted.strip()) < 40:
                raise ValueError()
            text = converted
        except (WebError, ValueError, KeyError, TypeError):
            reader_status = 'local_text_fallback_jina_unavailable_no_retry'
        return {'status': 'ok', 'url': final, 'requested_url': url, 'title': title,
                'excerpt': text[:max_chars], 'source_type': 'public_web',
                'content_kind': 'web_body', 'content_completeness': 'partial',
                'published_at': None, 'publication_date_status': 'unknown', 'author': None,
                'fetched_at': utcnow(), 'reader': reader_status,
                'billing': 'provider_cost_unknown', 'http_request_bound': 6,
                'limitations': 'bounded static extraction; not a verified complete article'}
