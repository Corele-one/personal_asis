"""Read-only Zhihu CLI, selected XiaoHongShu MCP tools and WeChat share links."""

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

from .credentials import CredentialStore
from .data_policy import exclusion_reason
from .reading_sources import Article, MAX_RESPONSE, NoRedirect, Page, SourceError, identity, origin_url, text


def process_env():
    return {k: v for k, v in os.environ.items() if k in (
        'PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT', 'HTTPS_PROXY', 'HTTP_PROXY',
        'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy', 'SSL_CERT_FILE')}


def timestamp(value, milliseconds=False):
    if type(value) is not int or value <= 0:
        return ''
    try:
        return datetime.fromtimestamp(value / (1000 if milliseconds else 1), timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return ''


def zhihu_url(url):
    clean = origin_url(url)
    p = urlsplit(clean)
    if (p.scheme != 'https' or p.hostname not in ('www.zhihu.com', 'zhuanlan.zhihu.com')
            or p.port not in (None, 443) or p.query
            or not re.fullmatch(r'/(?:question/\d+(?:/answer/\d+)?|answer/\d+|p/\d+|zvideo/\d+|pin/\d+)', p.path)):
        raise SourceError('reading_invalid_zhihu_content_url')
    return clean


class Zhihu:
    def __init__(self, executable, collection_id=None, store=None, runner=subprocess.run):
        path = Path(executable)
        if not path.is_absolute() or not path.is_file():
            raise SourceError('reading_zhihu_cli_not_installed')
        self.executable, self.collection_id = str(path), collection_id
        self.store = store or CredentialStore('zhihu', 'local.personal-asis.reading')
        self.runner = runner

    def call(self, operation, *, cursor='', limit=20, url=None):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise SourceError('reading_zhihu_limit_1_to_50')
        if cursor and (not isinstance(cursor, str) or not re.fullmatch(r'\d{1,19}', cursor)
                       or int(cursor) > 2**63 - 1):
            raise SourceError('reading_invalid_zhihu_offset')
        if operation == 'collections':
            if self.collection_id is None:
                if cursor:
                    raise SourceError('reading_zhihu_recent_has_no_pagination')
                args = ['me', 'favorites', 'recent', '--limit', str(limit)]
            else:
                token = str(self.collection_id)
                if not re.fullmatch(r'[1-9]\d{0,18}', token) or int(token) > 2**63 - 1:
                    raise SourceError('reading_invalid_zhihu_collection_id')
                args = ['me', 'favorites', 'items', '--url-token', token,
                        '--offset', cursor or '0', '--limit', str(limit)]
        elif operation in ('followees', 'contents'):
            args = ['me', operation, '--offset', cursor or '0', '--limit', str(limit)]
        elif operation == 'collection-lists':
            args = ['me', 'favorites', 'lists', '--limit', str(limit)]
        elif operation == 'own-content':
            args = ['me', 'content', '--content-url', zhihu_url(url)]
        else:
            raise SourceError('reading_write_or_unknown_operation_denied')
        env = process_env()
        env['ZHIHU_ACCESS_SECRET'] = self.store.get()
        try:
            response = self.runner([self.executable, '--timeout', '20s', *args], env=env,
                                   capture_output=True, stdin=subprocess.DEVNULL, timeout=25)
        except (OSError, subprocess.SubprocessError):
            raise SourceError('reading_zhihu_execution_failed') from None
        if len(response.stdout) > MAX_RESPONSE:
            raise SourceError('reading_response_too_large')
        try:
            payload = json.loads(response.stdout)
        except (ValueError, UnicodeError):
            raise SourceError('reading_zhihu_invalid_json') from None
        if (not isinstance(payload, dict) or response.returncode
                or type(payload.get('Code')) is not int or payload['Code'] != 0):
            raise SourceError('reading_zhihu_request_failed')
        if not isinstance(payload.get('Data'), dict):
            raise SourceError('reading_zhihu_response_schema_unverified')
        return payload['Data']

    @staticmethod
    def article(row):
        if not isinstance(row, dict):
            raise SourceError('reading_zhihu_article_schema_unverified')
        url = zhihu_url(row.get('Url'))
        author = row.get('Author') or {}
        if not isinstance(author, dict):
            raise SourceError('reading_zhihu_article_schema_unverified')
        summary = text(row.get('Summary', ''))
        return Article(hashlib.sha256(url.encode()).hexdigest(), text(row.get('Title', '')),
                       url, text(author.get('Name', '')), timestamp(row.get('CreatedAt')),
                       author_text=summary, content_kind='summary_only' if summary else 'metadata_only')

    def page(self, stream, since='', until='', cursor='', limit=20):
        if stream != 'selections':
            raise SourceError('reading_zhihu_follow_timeline_not_supported')
        data = self.call('collections', cursor=cursor, limit=limit)
        if not isinstance(data.get('Items'), list):
            raise SourceError('reading_zhihu_page_schema_unverified')
        paging = data.get('Paging')
        if self.collection_id is None:
            # The recent endpoint has no paging contract: never invent history.
            return Page([self.article(row) for row in data['Items']], None, None)
        if not isinstance(paging, dict) or type(paging.get('IsEnd')) is not bool:
            raise SourceError('reading_zhihu_pagination_schema_unverified')
        next_cursor = paging.get('NextOffset')
        if not paging['IsEnd']:
            if (not isinstance(next_cursor, str) or not re.fullmatch(r'\d{1,19}', next_cursor)
                    or not int(cursor or '0') < int(next_cursor) <= 2**63-1):
                raise SourceError('reading_zhihu_pagination_schema_unverified')
        return Page([self.article(row) for row in data['Items']], next_cursor, not paging['IsEnd'])

    def detail(self, item_id):
        # Official full text is owner-only; a favorite ID is insufficient proof.
        raise SourceError('reading_zhihu_fulltext_requires_explicit_owner_content_url')


def xhs_endpoint(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'http' or p.hostname != '127.0.0.1' or not p.port
                or p.path != '/mcp' or p.username or p.password or p.query or p.fragment):
            raise ValueError()
    except (ValueError, TypeError):
        raise SourceError('reading_xhs_loopback_mcp_required') from None
    return value


class XiaoHongShu:
    READS = {'list_feeds', 'search_feeds', 'get_feed_detail', 'get_my_profile'}

    def __init__(self, endpoint, store=None, opener=None, access_store=None):
        self.endpoint = xhs_endpoint(endpoint)
        self.store = store or CredentialStore('xiaohongshu-mcp', 'local.personal-asis.reading')
        self.access_store = access_store or (lambda item: CredentialStore(
            'note:' + identity(item), 'local.personal-asis.reading-access'))
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())
        self.session, self.protocol, self.sequence = None, '2024-11-05', 0
        self.initialized = False

    def _rpc(self, method, params, notification=False):
        self.sequence += 1
        data = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            data['id'] = self.sequence
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self.protocol, 'Authorization': 'Bearer ' + self.store.get()}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        req = Request(self.endpoint, json.dumps(data).encode(), headers, method='POST')
        try:
            with self.opener.open(req, timeout=40) as response:
                raw = response.read(MAX_RESPONSE + 1)
                session = response.headers.get('Mcp-Session-Id')
                if session:
                    self.session = session
        except (HTTPError, URLError, TimeoutError, OSError):
            raise SourceError('reading_xhs_transport_failed') from None
        if len(raw) > MAX_RESPONSE:
            raise SourceError('reading_response_too_large')
        if notification:
            return None
        try:
            decoded = raw.decode()
            if decoded.lstrip().startswith('{'):
                payload = json.loads(decoded)
            else:
                events = [json.loads(line[5:].strip()) for line in decoded.splitlines()
                          if line.startswith('data:') and line[5:].strip()]
                payload = next(e for e in events if isinstance(e, dict) and e.get('id') == data['id'])
        except (ValueError, UnicodeError, StopIteration, TypeError):
            raise SourceError('reading_xhs_protocol_invalid') from None
        if (not isinstance(payload, dict) or payload.get('id') != data['id']
                or payload.get('error') or not isinstance(payload.get('result'), dict)):
            raise SourceError('reading_xhs_protocol_invalid')
        return payload['result']

    def call(self, operation, arguments):
        if operation not in self.READS:
            raise SourceError('reading_write_or_unknown_operation_denied')
        if operation == 'get_my_profile' and arguments != {'tab': 'fav'}:
            raise SourceError('reading_xhs_only_visible_favorites_supported')
        if operation == 'list_feeds' and arguments:
            raise SourceError('reading_xhs_invalid_arguments')
        if operation == 'search_feeds':
            if (set(arguments) - {'keyword', 'filters'} or not isinstance(arguments.get('keyword'), str)
                    or not 1 <= len(arguments['keyword'].strip()) <= 200
                    or exclusion_reason('', arguments['keyword'])
                    or arguments.get('filters', {}) not in ({}, {'search_scope': '已关注'})):
                raise SourceError('reading_xhs_invalid_arguments')
        if operation == 'get_feed_detail':
            if (set(arguments) != {'feed_id', 'xsec_token', 'load_all_comments'}
                    or arguments['load_all_comments'] is not False
                    or not isinstance(arguments['xsec_token'], str) or not arguments['xsec_token']):
                raise SourceError('reading_xhs_invalid_arguments')
            identity(arguments['feed_id'])
        if not self.initialized:
            init = self._rpc('initialize', {'protocolVersion': self.protocol, 'capabilities': {},
                             'clientInfo': {'name': 'personal-asis-reading', 'version': '1'}})
            if init.get('protocolVersion') not in ('2024-11-05', '2025-03-26', '2025-06-18'):
                raise SourceError('reading_xhs_protocol_version_unsupported')
            self.protocol = init['protocolVersion']
            self._rpc('notifications/initialized', {}, notification=True)
            self.initialized = True
        result = self._rpc('tools/call', {'name': operation, 'arguments': arguments})
        if result.get('isError'):
            raise SourceError('reading_xhs_tool_failed')
        content = result.get('content')
        try:
            if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
                raise ValueError()
            blocks = [b for b in content if b.get('type') == 'text']
            if len(blocks) != 1:
                raise ValueError()
            result = json.loads(blocks[0]['text'])
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError, KeyError):
            raise SourceError('reading_xhs_result_schema_unverified') from None

    def _articles(self, data, limit):
        if not isinstance(data.get('feeds'), list):
            raise SourceError('reading_xhs_feed_schema_unverified')
        articles = []
        for row in data['feeds'][:limit]:
            if not isinstance(row, dict) or not isinstance(row.get('noteCard'), dict):
                raise SourceError('reading_xhs_feed_schema_unverified')
            item_id = identity(row.get('id'))
            token = row.get('xsecToken')
            if isinstance(token, str) and token:
                self.access_store(item_id).set(token)
            card = row['noteCard']
            user = card.get('user') or {}
            articles.append(Article(item_id, text(card.get('displayTitle', '')),
                'https://www.xiaohongshu.com/explore/' + item_id, text(user.get('nickname', ''))))
        return Page(articles, None, None)  # Current browser implementation exposes a visible page.

    def page(self, stream, since='', until='', cursor='', limit=20):
        if cursor:
            raise SourceError('reading_xhs_history_pagination_unavailable')
        if stream not in ('subscriptions', 'selections'):
            raise SourceError('reading_invalid_stream')
        data = self.call('get_my_profile', {'tab': 'fav'}) if stream == 'selections' else self.call('list_feeds', {})
        return self._articles(data, limit)

    def search(self, query, followed_only=False, limit=20):
        filters = {'search_scope': '已关注'} if followed_only else {}
        return self._articles(self.call('search_feeds', {'keyword': query, 'filters': filters}), limit)

    def detail(self, item_id):
        item_id = identity(item_id)
        result = self.call('get_feed_detail', {'feed_id': item_id,
            'xsec_token': self.access_store(item_id).get(), 'load_all_comments': False})
        try:
            note = result['data']['note']
            if identity(note['noteId']) != item_id:
                raise ValueError()
            description = text(note.get('desc', ''))
            # Keep public media locators separate; never retain signed access URLs.
            candidates = [image.get('urlDefault', '') for image in (note.get('imageList') or [])
                          if isinstance(image, dict)]
            streams = ((note.get('video') or {}).get('media') or {}).get('stream') or {}
            if isinstance(streams, dict):
                for variants in streams.values():
                    if isinstance(variants, list):
                        candidates += [url for variant in variants if isinstance(variant, dict)
                                       for url in variant.get('backupUrls', [])]
            media = list(dict.fromkeys(url for value in candidates if (url := origin_url(value))
                                       and not urlsplit(url).query))[:100]
            return Article(item_id, text(note.get('title', '')),
                'https://www.xiaohongshu.com/explore/' + item_id,
                text((note.get('user') or {}).get('nickname', '')),
                timestamp(note.get('time'), milliseconds=True), author_text=description,
                content_kind='note_text' if description else 'metadata_only', media_urls=media)
        except (KeyError, TypeError, ValueError):
            raise SourceError('reading_xhs_detail_schema_unverified') from None


class XiaoHongShuOpenCLI:
    """Existing owner-controlled Chrome session; never import browser cookies."""

    def __init__(self, executable, node, runner=subprocess.run, access_store=None):
        self.entry, self.node = Path(executable).resolve(), Path(node).resolve()
        if (not self.entry.is_file() or not self.node.is_file()
                or not str(self.entry).endswith('/dist/src/main.js')):
            raise SourceError('reading_opencli_not_installed')
        self.runner = runner
        self.access_store = access_store or (lambda item: CredentialStore(
            'opencli-note:' + identity(item), 'local.personal-asis.reading-access'))

    def call(self, operation, *, limit=20, value=None):
        if operation not in ('feed', 'saved', 'search', 'note'):
            raise SourceError('reading_write_or_unknown_operation_denied')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise SourceError('reading_opencli_limit_1_to_20')
        request = {'entry': str(self.entry), 'operation': operation, 'limit': limit, 'value': value}
        try:
            result = self.runner([str(self.node), str(Path(__file__).with_name('opencli_read.mjs'))],
                input=json.dumps(request).encode(), env=process_env(), capture_output=True, timeout=75)
        except (OSError, subprocess.SubprocessError):
            raise SourceError('reading_opencli_execution_failed') from None
        if result.returncode or len(result.stdout) > MAX_RESPONSE:
            raise SourceError('reading_opencli_read_failed')
        try:
            data = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise SourceError('reading_opencli_invalid_json') from None
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise SourceError('reading_opencli_schema_unverified')
        return data

    def articles(self, rows, limit):
        articles = []
        for row in rows[:limit]:
            try:
                url = urlsplit(row['url'])
                match = re.fullmatch(r'/(?:explore|discovery/item|search_result|note)/([a-f0-9]{24})'
                                     r'|/user/profile/[a-f0-9]{24}/([a-f0-9]{24})', url.path)
                if (url.scheme != 'https' or url.hostname not in ('xiaohongshu.com', 'www.xiaohongshu.com')
                        or url.username or url.password or url.port not in (None, 443) or not match
                        or url.fragment or set(parse_qs(url.query)) - {'xsec_token', 'xsec_source'}):
                    raise ValueError()
                item_id = match[1] or match[2]
                if row.get('id', item_id) != item_id:
                    raise ValueError()
                tokens = parse_qs(url.query).get('xsec_token', [])
                if len(tokens) == 1 and 0 < len(tokens[0]) <= 2048 and not any(c.isspace() for c in tokens[0]):
                    # Preserve the platform-provided path and source, not only its signature.
                    self.access_store(item_id).set(row['url'])
                articles.append(Article(item_id, text(row.get('title', '')),
                    'https://www.xiaohongshu.com/explore/' + item_id, text(row.get('author', ''))))
            except (ValueError, KeyError, TypeError):
                raise SourceError('reading_opencli_note_schema_unverified') from None
        return Page(articles, None, None)

    def page(self, stream, since='', until='', cursor='', limit=20):
        if stream not in ('subscriptions', 'selections') or cursor:
            raise SourceError('reading_opencli_visible_window_only')
        return self.articles(self.call('saved' if stream == 'selections' else 'feed', limit=limit), limit)

    def search(self, query, followed_only=False, limit=20):
        if followed_only:
            raise SourceError('reading_opencli_followed_search_not_supported')
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 200
                or exclusion_reason('', query)):
            raise SourceError('reading_xhs_invalid_arguments')
        return self.articles(self.call('search', limit=limit, value=query), limit)

    def detail(self, item_id):
        item_id = identity(item_id)
        if not re.fullmatch(r'[a-f0-9]{24}', item_id):
            raise SourceError('reading_invalid_item_identity')
        url = self.access_store(item_id).get()
        if not isinstance(url, str) or not 0 < len(url) <= 4096:
            raise SourceError('reading_xhs_invalid_arguments')
        # Revalidate keychain values; never let them turn the bridge into a URL opener.
        class ReadOnlyStore:
            def set(self, value): pass
        validator = XiaoHongShuOpenCLI(self.entry, self.node, access_store=lambda item: ReadOnlyStore())
        validator.articles([{'id': item_id, 'url': url}], 1)
        if not parse_qs(urlsplit(url).query).get('xsec_token'):
            raise SourceError('reading_xhs_invalid_arguments')
        rows = self.call('note', value=url)
        fields = {}
        for row in rows:
            if not isinstance(row.get('field'), str) or not isinstance(row.get('value'), str):
                raise SourceError('reading_opencli_note_schema_unverified')
            if row['field'] in fields:
                raise SourceError('reading_opencli_note_schema_unverified')
            fields[row['field']] = row['value']
        if not {'title', 'author', 'content'} <= fields.keys():
            raise SourceError('reading_opencli_note_schema_unverified')
        body = text(fields['content'])
        return Article(item_id, text(fields['title']),
            'https://www.xiaohongshu.com/explore/' + item_id, text(fields['author']),
            author_text=body, content_kind='note_text' if body else 'metadata_only')


def wechat_url(value):
    try:
        p = urlsplit(value)
        params = parse_qs(p.query, keep_blank_values=True)
        if (p.scheme != 'https' or p.hostname != 'mp.weixin.qq.com' or p.port not in (None, 443)
                or p.username or p.password or p.fragment or len(value) > 4000
                or exclusion_reason('', value)):
            raise ValueError()
        if re.fullmatch(r'/s/[A-Za-z0-9_-]{5,200}', p.path):
            allowed = {'scene', 'from', 'isappinstalled', 'clicktime', 'enterid'}
            if set(params) - allowed:
                raise ValueError()
            return urlunsplit(('https', 'mp.weixin.qq.com', p.path, '', ''))
        keys = {'__biz', 'mid', 'idx', 'sn'}
        if p.path != '/s' or not keys <= set(params) or set(params) - keys - {'scene', 'from', 'isappinstalled', 'chksm'}:
            raise ValueError()
        if any(len(params[k]) != 1 or not params[k][0] for k in keys):
            raise ValueError()
        return 'https://mp.weixin.qq.com/s?' + urlencode({k: params[k][0] for k in sorted(keys)})
    except (ValueError, TypeError):
        raise SourceError('reading_wechat_public_share_link_required') from None


class WeChatHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.content_depth, self.hidden = 0, None, 0
        self.parts, self.title = [], ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property') == 'og:title':
            self.title = attrs.get('content', '')
        if tag in ('meta', 'img', 'br', 'input', 'link', 'hr', 'source', 'wbr'):
            if tag == 'br' and self.content_depth is not None:
                self.parts.append('\n')
            return
        self.depth += 1
        if attrs.get('id') == 'js_content':
            self.content_depth = self.depth
        if tag in ('script', 'style'):
            self.hidden += 1
        if self.content_depth is not None and tag in ('p', 'section', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('meta', 'img', 'br', 'input', 'link', 'hr', 'source', 'wbr'):
            return
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if self.content_depth is not None and tag in ('p', 'section', 'div', 'li'):
            self.parts.append('\n')
        if self.depth == self.content_depth:
            self.content_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.content_depth is not None and not self.hidden:
            self.parts.append(data)


class WeChat:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(NoRedirect())

    @staticmethod
    def article(url, html):
        url = wechat_url(url)
        parser = WeChatHTML()
        parser.feed(html)
        body = '\n'.join(s.strip() for s in ''.join(parser.parts).splitlines() if s.strip())
        if not body:
            raise SourceError('reading_wechat_content_unavailable_or_requires_login')
        return Article(hashlib.sha256(url.encode()).hexdigest(), text(parser.title) or '公众号分享文章',
                       url, author_text=body, content_kind='page_text')

    def share(self, url):
        url = wechat_url(url)
        request = Request(url, headers={'Accept': 'text/html', 'User-Agent': 'PersonalAsis-Reading/1'})
        try:
            with self.opener.open(request, timeout=25) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise SourceError('reading_wechat_read_failed') from None
        if len(raw) > MAX_RESPONSE:
            raise SourceError('reading_response_too_large')
        try:
            return self.article(url, raw.decode('utf-8-sig'))
        except UnicodeError:
            raise SourceError('reading_wechat_invalid_encoding') from None
