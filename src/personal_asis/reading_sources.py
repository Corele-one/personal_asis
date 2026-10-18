"""Read-only reading-source protocols. No platform mutation or model calls."""

from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .credentials import CredentialStore
from .data_policy import exclusion_reason


MAX_RESPONSE = 4 * 1024 * 1024
REGIONS = {'cn': 'https://api.wucai.site', 'eu': 'https://eu.wucainote.com',
           'us': 'https://us.wucainote.com'}


class SourceError(ValueError):
    """Only fixed error identifiers, never remote text, tokens or payloads."""


def identity(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise SourceError('reading_invalid_item_identity')
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', value) or value.startswith('-'):
        raise SourceError('reading_invalid_item_identity')
    return value


def origin_url(value):
    if not isinstance(value, str) or len(value) > 4000:
        return ''
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('https', 'http') or not parts.hostname or
                parts.username or parts.password or exclusion_reason('', value)):
            return ''
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                           parts.query, ''))
    except ValueError:
        return ''


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'blockquote'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li', 'blockquote'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def text(value):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 1024 * 1024:
        raise SourceError('reading_invalid_text')
    parser = TextHTML()
    parser.feed(value)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines()
                     if line.strip())


@dataclass
class Article:
    item_id: str
    title: str
    url: str = ''
    author: str = ''
    published_at: str = ''
    author_text: str = ''
    user_note: str = ''
    highlights: list = field(default_factory=list)
    content_kind: str = 'metadata_only'
    media_urls: list = field(default_factory=list)


@dataclass
class Page:
    articles: list
    cursor: str | None
    more: bool | None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('reading_redirect_denied')


class Wucai:
    READS = {'list_articles', 'search_articles', 'get_article_details'}

    def __init__(self, region='cn', store=None, opener=None):
        if region not in REGIONS:
            raise SourceError('reading_invalid_region')
        self.region = region
        self.store = store or CredentialStore('wucai:' + region, 'local.personal-asis.reading')
        self.opener = opener or build_opener(NoRedirect())

    def call(self, endpoint, params):
        if endpoint not in self.READS:
            raise SourceError('reading_write_or_unknown_operation_denied')
        token = self.store.get()
        if not token.startswith('wct-') or any(c.isspace() for c in token):
            raise SourceError('reading_wucai_token_required')
        request = Request(REGIONS[self.region] + '/apix/openapi/aiagent/' + endpoint,
                          data=json.dumps(params).encode(), method='POST', headers={
                              'Authorization': token, 'X-Client-ID': '56',
                              'Content-Type': 'application/json; charset=utf-8',
                              'User-Agent': 'PersonalAsis-Reading/1'})
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            raise SourceError('reading_wucai_http_' + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise SourceError('reading_wucai_network_failed') from None
        if len(raw) > MAX_RESPONSE:
            raise SourceError('reading_response_too_large')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SourceError('reading_invalid_json') from None
        if not isinstance(result, dict) or type(result.get('code')) is not int:
            raise SourceError('reading_wucai_response_schema_unverified')
        if result['code'] != 1:
            code = result['code']
            raise SourceError('reading_wucai_code_' + str(code))
        return result.get('data')

    @staticmethod
    def article(row):
        if not isinstance(row, dict):
            raise SourceError('reading_wucai_article_schema_unverified')
        # Public documentation does not promise clipped full text. Never infer it.
        if 'note_idx' not in row and 'noteIdx' not in row:
            raise SourceError('reading_wucai_article_schema_unverified')
        item_id = identity(row.get('note_idx', row.get('noteIdx')))
        highlights = row.get('highlights', [])
        if highlights is None:
            highlights = []
        if not isinstance(highlights, list):
            raise SourceError('reading_wucai_highlights_schema_unverified')
        parts = []
        for highlight in highlights:
            if not isinstance(highlight, dict):
                raise SourceError('reading_wucai_highlights_schema_unverified')
            quote = text(highlight.get('text', highlight.get('content', '')))
            note = text(highlight.get('annonation', highlight.get('note', '')))
            if quote or note:
                parts.append({'quote': quote, 'note': note})
        page_note = text(row.get('page_note', row.get('note', '')))
        media = [url for highlight in highlights if isinstance(highlight, dict)
                 if (url := origin_url(highlight.get('image_url', ''))) and not urlsplit(url).query]
        return Article(item_id, text(row.get('page_title', row.get('title', ''))) or item_id,
                       origin_url(row.get('page_url', row.get('url', ''))), text(row.get('author', '')),
                       str(row.get('published_at') or ''), user_note=page_note,
                       highlights=parts, content_kind='highlights_only' if parts else
                       'annotations_only' if page_note else 'metadata_only', media_urls=media)

    def page(self, stream, since, until, cursor='', limit=20):
        if stream != 'selections':
            raise SourceError('reading_wucai_only_article_selections_supported')
        first, last = date.fromisoformat(since), date.fromisoformat(until)
        if not 0 <= (last - first).days <= 13:
            raise SourceError('reading_wucai_range_max_14_days')
        data = self.call('list_articles', {'range': since + ':' + until, 'status': 'all',
                                         'cursor': cursor, 'page_size': limit, 'with_highlights': True})
        if not isinstance(data, dict):
            raise SourceError('reading_wucai_page_schema_unverified')
        rows = data.get('articles', data.get('list', data.get('items')))
        if not isinstance(rows, list):
            raise SourceError('reading_wucai_page_schema_unverified')
        next_cursor = data.get('next_cursor', data.get('nextCursor'))
        more = data.get('has_more', data.get('hasMore', data.get('hasNext')))
        if more is not None and type(more) is not bool:
            raise SourceError('reading_wucai_pagination_schema_unverified')
        # Unknown pagination stays unknown, including a short page.
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise SourceError('reading_wucai_pagination_schema_unverified')
        if more is None and ('next_cursor' in data or 'nextCursor' in data) and isinstance(next_cursor, str):
            # Verified live protocol: next_cursor alone drives continuation.
            # Exhaustion is scoped to this query, never proof of complete history.
            more = bool(next_cursor)
        return Page([self.article(row) for row in rows], next_cursor, more)

    def detail(self, item_id):
        data = self.call('get_article_details', {'note_idx': identity(item_id)})
        if not isinstance(data, dict):
            raise SourceError('reading_wucai_article_schema_unverified')
        return self.article(data.get('detail', data))


class Folo:
    def __init__(self, executable, store=None, runner=subprocess.run):
        path = Path(executable)
        if not path.is_absolute() or not path.is_file():
            raise SourceError('reading_folo_cli_not_installed')
        self.executable = str(path)
        self.store = store or CredentialStore('folo', 'local.personal-asis.reading')
        self.runner = runner

    def call(self, operation, **values):
        # Build argv from operations, never accept an arbitrary command or flags.
        if operation in ('timeline', 'collections'):
            args = ['timeline'] if operation == 'timeline' else ['collection', 'list']
            args += ['--limit', str(values['limit'])]
            if values.get('cursor'):
                cursor = values['cursor']
                if not isinstance(cursor, str) or len(cursor) > 128 or cursor.startswith('-'):
                    raise SourceError('reading_invalid_cursor')
                args += ['--cursor', cursor]
        elif operation in ('detail', 'readability'):
            args = ['entry', 'get' if operation == 'detail' else 'read', identity(values['item_id'])]
        elif operation == 'subscriptions':
            args = ['subscription', 'list']
        else:
            raise SourceError('reading_write_or_unknown_operation_denied')
        env = {k: v for k, v in os.environ.items() if k in (
            'PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT', 'HTTPS_PROXY', 'HTTP_PROXY',
            'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy', 'SSL_CERT_FILE')}
        env['FOLO_TOKEN'] = self.store.get()
        try:
            result = self.runner([self.executable, '--format', 'json', '--api-url',
                                  'https://api.folo.is', *args], env=env,
                                 capture_output=True, timeout=40, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            raise SourceError('reading_folo_execution_failed') from None
        if len(result.stdout) > MAX_RESPONSE:
            raise SourceError('reading_response_too_large')
        try:
            payload = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise SourceError('reading_folo_invalid_json') from None
        if not isinstance(payload, dict):
            raise SourceError('reading_folo_response_schema_unverified')
        if result.returncode or payload.get('ok') is not True:
            error = payload.get('error')
            code = error.get('code', '') if isinstance(error, dict) else ''
            known = code if code in ('UNAUTHORIZED', 'INVALID_ARGUMENT') else 'request_failed'
            raise SourceError('reading_folo_' + known)
        return payload.get('data')

    @staticmethod
    def article(row, include_body=False):
        if not isinstance(row, dict) or not isinstance(row.get('entries'), dict):
            raise SourceError('reading_folo_article_schema_unverified')
        entry = row['entries']
        content = text(entry.get('content', '')) if include_body else ''
        return Article(identity(entry.get('id')), text(entry.get('title', '')),
                       origin_url(entry.get('url', '')), text(entry.get('author', '')),
                       str(entry.get('publishedAt') or ''), author_text=content,
                       content_kind='feed_content' if content else 'metadata_only')

    def page(self, stream, since='', until='', cursor='', limit=20):
        if stream not in ('subscriptions', 'selections'):
            raise SourceError('reading_invalid_stream')
        data = self.call('collections' if stream == 'selections' else 'timeline',
                         cursor=cursor, limit=limit)
        if (not isinstance(data, dict) or not isinstance(data.get('entries'), list)
                or type(data.get('hasNext')) is not bool
                or data.get('nextCursor') is not None and not isinstance(data['nextCursor'], str)):
            raise SourceError('reading_folo_page_schema_unverified')
        # Subscription discovery persists metadata only; bodies are fetched on demand.
        return Page([self.article(row, stream == 'selections') for row in data['entries']],
                    data.get('nextCursor'), data['hasNext'])

    def detail(self, item_id):
        data = self.call('detail', item_id=item_id)
        # The SDK detail may be an entry wrapper or the direct entries object.
        if isinstance(data, dict) and 'entries' not in data:
            data = {'entries': data}
        return self.article(data, True)
