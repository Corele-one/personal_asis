"""Loopback-only web client for the local Conversation Core."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

from . import conversation as core
from .conversation_api import ConversationAPI


ASSETS = {'/chat': ('conversation.html', 'text/html; charset=utf-8'),
          '/': ('conversation.html', 'text/html; charset=utf-8'),
          '/conversation.js': ('conversation.js', 'text/javascript; charset=utf-8'),
          '/conversation.css': ('conversation.css', 'text/css; charset=utf-8')}


def server(home, port=0):
    home = Path(home)
    web_root = Path(__file__).with_name('web')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def valid_origin(self, post=False):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            origin = f'http://{expected_host}'
            if self.headers.get('Host') != expected_host:
                raise ValueError('local_chat_host_rejected')
            supplied = self.headers.get('Origin')
            if (post and supplied != origin) or (supplied and supplied != origin):
                raise ValueError('local_chat_origin_rejected')

        def write(self, value, status=200, mime='application/json; charset=utf-8'):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def body(self):
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                raise ValueError('local_chat_invalid_body')
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 8192:
                raise ValueError('local_chat_invalid_body_size')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError('local_chat_invalid_body')
            return value

        def do_GET(self):
            try:
                self.valid_origin()
                parsed = urlsplit(self.path)
                if parsed.path in ASSETS:
                    name, mime = ASSETS[parsed.path]
                    return self.write((web_root/name).read_bytes(), mime=mime)
                params = parse_qs(parsed.query, strict_parsing=True) if parsed.query else {}
                if parsed.path == '/api/sessions':
                    return self.write(ConversationAPI(home).sessions())
                if parsed.path == '/api/budget':
                    return self.write(ConversationAPI(home).budget())
                if parsed.path == '/api/session':
                    sid = params.get('id', [''])[0]
                    return self.write(ConversationAPI(home).history(sid))
                if parsed.path == '/api/events':
                    sid = params.get('id', [''])[0]
                    after = int(params.get('after', ['0'])[0])
                    event_id=self.headers.get('Last-Event-ID')
                    if event_id is not None:
                        after=int(event_id)
                    ConversationAPI(home).status(sid)
                    self.send_response(200)
                    self.send_header('Content-Type','text/event-stream; charset=utf-8')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
                    self.send_header('Connection','close')
                    self.end_headers()
                    deadline=time.monotonic()+25
                    while time.monotonic()<deadline:
                        events=ConversationAPI(home).events(sid,after)['events']
                        for event in events:
                            after=event['sequence']
                            self.wfile.write(('id: %d\nevent: asis\ndata: %s\n\n' %
                                (after,json.dumps(event,ensure_ascii=False))).encode())
                        if events:
                            self.wfile.flush()
                            break
                        else:
                            self.wfile.write(b': keepalive\n\n');self.wfile.flush()
                            time.sleep(0.75)
                    self.close_connection=True
                    return
                raise ValueError('not_found')
            except (ValueError, OSError, TypeError, json.JSONDecodeError) as error:
                code = str(error)
                rejected=code in ('local_chat_host_rejected','local_chat_origin_rejected')
                self.write({'error': code if rejected else 'invalid_request'}, 403 if rejected else 400)

        def do_POST(self):
            try:
                self.valid_origin(post=True)
                data = self.body()
                action = urlsplit(self.path).path
                if action == '/api/session/new':
                    if data:
                        raise ValueError('invalid_fields')
                    return self.write(ConversationAPI(home).create())
                if action == '/api/send':
                    if set(data) != {'session_id','message','turn_id'}:
                        raise ValueError('invalid_fields')
                    return self.write(ConversationAPI(home).send(data['session_id'],data['message'],data['turn_id']))
                if action == '/api/control':
                    if set(data) != {'session_id','action','turn_id'} or data['action'] not in ('resume','cancel','approve','deny','forget'):
                        raise ValueError('invalid_fields')
                    return self.write(ConversationAPI(home).control(data['session_id'],data['action'],data['turn_id']))
                raise ValueError('not_found')
            except (ValueError, OSError, TypeError, json.JSONDecodeError) as error:
                code = str(error)
                rejected=code in ('local_chat_host_rejected','local_chat_origin_rejected')
                self.write({'error': code if rejected or code.startswith('chat_') else 'invalid_request'},
                           403 if rejected else 409 if 'busy' in code or 'unfinished' in code else 400)

    http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    http.daemon_threads = True
    return http
