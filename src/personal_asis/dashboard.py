"""Read-only dashboard for the two agents. No legacy search or execution routes."""
import argparse
import json
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, parse_qs
from .http_errors import ProtocolError
from .web_auth import WebAuth
from .life_store import LifeStore
from .life_status import validate as validate_status

ASSETS = Path(__file__).parent / 'web'


def snapshot(home, day=None):
    store = LifeStore(Path(home) / 'life.sqlite3')
    try:
        records = store.recent(100)
        reminders = dict(store.db.execute('SELECT state,count(*) FROM reminders GROUP BY state'))
        records = [{k:r[k] for k in ('id','day','kind','text','summary','occurred_at','due_at','task_status')} for r in records]
        from .life_tracking import LifeTracking
        from .life_attention import LifeAttention
        tracking = LifeTracking(store).day(day)
        attention = LifeAttention(store).dashboard()
    finally:
        store.close()
    status = Path(home) / 'mac-status.json'
    mac = validate_status(json.loads(status.read_text())) if status.exists() else None
    content_path=Path(home)/'mac-content.json'
    content=json.loads(content_path.read_text()) if content_path.exists() else None
    if content:
        from .mac_content import validate as validate_content
        validate_content({k:content[k] for k in ('request_id','title','content')})
        content={k:content[k] for k in ('title','content','updated_at')}
    from .bootstrap_context import load as load_bootstrap
    baseline=load_bootstrap(Path(home)/'bootstrap.json')
    return dict(version=2, astrbot={'records': records, 'reminders': reminders}, mac=mac,
                mac_content=content, life_baseline=baseline, tracking=tracking, attention=attention)


def server(home, origin, port=8766):
    host = urlsplit(origin).netloc
    if urlsplit(origin).scheme != 'https' or not host or urlsplit(origin).path:
        raise ValueError('dashboard_https_origin_required')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def check(self, post=False):
            if self.headers.get('Host') != host or self.headers.get('X-Forwarded-Proto') != 'https':
                raise ProtocolError('invalid_proxy_origin',403)
            if post and self.headers.get('Origin') != origin:
                raise ProtocolError('origin_rejected',403)

        def token(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie',''))
                return cookie['asis_dashboard'].value if 'asis_dashboard' in cookie else ''
            except Exception:
                return ''

        def write(self, value, code=200, cookie=None, mime='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if cookie is not None:
                self.send_header('Set-Cookie', f'asis_dashboard={cookie}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age={43200 if cookie else 0}')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self.check()
                route = urlsplit(self.path).path
                with WebAuth(home,otp_required=False) as auth:
                    if route == '/api/session':
                        try:
                            info = auth.session(self.token())
                        except ProtocolError:
                            info = {'authenticated':False}
                        return self.write(dict(initialized=auth.initialized(),**info))
                    if route == '/api/dashboard':
                        auth.session(self.token())
                        day = parse_qs(urlsplit(self.path).query).get('day', [None])[0]
                        if day:
                            from datetime import date
                            try:
                                if date.fromisoformat(day).isoformat() != day:
                                    raise ValueError()
                            except ValueError:
                                raise ProtocolError('invalid_day', 400)
                        return self.write(snapshot(home, day))
                files = {'/':('dashboard.html','text/html'), '/dashboard.js':('dashboard.js','application/javascript'),
                         '/dashboard.css':('dashboard.css','text/css'), '/sw.js':('dashboard-sw.js','application/javascript'),
                         '/manifest.webmanifest':('dashboard.webmanifest','application/manifest+json'),
                         '/icon.svg':('dashboard-icon.svg','image/svg+xml')}
                if route not in files:
                    raise ProtocolError('not_found',404)
                name, mime = files[route]
                self.write((ASSETS/name).read_bytes(),mime=mime)
            except ProtocolError as error:
                self.write({'error':str(error)},error.status)
            except Exception:
                self.write({'error':'dashboard_unavailable'},503)

        def do_POST(self):
            try:
                self.check(True)
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[])) != 1:
                    raise ProtocolError('invalid_body')
                length=int(self.headers['Content-Length'])
                if not 0 < length <= 4096:
                    raise ProtocolError('body_size')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict):
                    raise ProtocolError('invalid_body')
                with WebAuth(home,otp_required=False) as auth:
                    if self.path == '/auth/login':
                        session = auth.login(data.get('password',''), '', self.headers.get('X-Real-IP', self.client_address[0]))
                        return self.write({'authenticated':True,'csrf':session['csrf']},cookie=session['token'])
                    if self.path == '/auth/logout':
                        auth.session(self.token(),self.headers.get('X-CSRF-Token',''))
                        auth.logout(self.token())
                        return self.write({'authenticated':False},cookie='')
                    raise ProtocolError('not_found',404)
            except ProtocolError as error:
                self.write({'error':str(error)},error.status)
            except (ValueError,TypeError):
                self.write({'error':'invalid_body'},400)
            except Exception:
                self.write({'error':'dashboard_unavailable'},503)

    http=HTTPServer(('127.0.0.1',port),Handler)
    http.timeout=15
    return http


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=Path.home()/'.local/share/personal-asis-life')
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    import os
    os.umask(0o077)
    with server(args.home,args.origin,args.port) as http:
        http.serve_forever()


if __name__=='__main__':
    main()
