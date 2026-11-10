"""Authenticated loopback authority. M1 accepts synthetic input only."""
import argparse
import contextlib
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading

from .memory_authority import MemoryAuthority, MemoryFault


class MemoryHTTPServer(ThreadingHTTPServer):
    daemon_threads=False
    block_on_close=True
    allow_reuse_address=True

    def __init__(self,address,authority,tokens,ledger):
        self.authority,self.tokens,self.ledger=authority,tokens,ledger
        self.slots=threading.BoundedSemaphore(4)
        super().__init__(address,MemoryHandler)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request,address)

    def process_request_thread(self,request,address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()

    def handle_error(self,*args):
        pass


class MemoryHandler(BaseHTTPRequestHandler):
    server_version='PersonalMemory/1'
    sys_version=''

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self,*args):
        pass

    def respond(self,status,value):
        raw=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        client=None
        token=self.headers.get('Authorization','')
        for name,key in self.server.tokens.items():
            if hmac.compare_digest(token,'Bearer '+key):
                client=name
        if not client:
            self.respond(401,dict(error='memory_client_denied'))
            return
        try:
            if self.path!='/v1/memory' or self.headers.get('Origin'):
                raise MemoryFault('memory_request_denied')
            size=int(self.headers.get('Content-Length','0'))
            if not 1<=size<=16384 or self.headers.get('Transfer-Encoding'):
                raise MemoryFault('memory_invalid_request')
            request=json.loads(self.rfile.read(size))
            if not isinstance(request,dict) or set(request)!={'action','arguments'}:
                raise MemoryFault('memory_invalid_request')
            value=self.server.authority.dispatch(client,request['action'],request['arguments'])
            if request['action']=='status':
                value['calls']=self.server.ledger.status()
            self.respond(200,value)
        except MemoryFault as error:
            self.respond(409,dict(error=str(error)))
        except (ValueError,TypeError,KeyError):
            self.respond(400,dict(error='memory_invalid_request'))
        except Exception:
            self.respond(503,dict(error='memory_upstream_unknown_no_retry'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=Path('/var/lib/personal-asis-memory'))
    parser.add_argument('--port',type=int,default=23101)
    args=parser.parse_args()
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    home=args.home
    if home.is_symlink() or home.stat().st_mode & 0o777 != 0o700:
        raise MemoryFault('memory_private_directory_required')
    private=home/'config.json'
    if private.is_symlink() or private.stat().st_mode & 0o777 != 0o600 or private.stat().st_uid!=os.getuid():
        raise MemoryFault('memory_private_configuration_required')
    config=json.loads(private.read_text())
    if config.get('mode')!='synthetic_only':
        raise MemoryFault('memory_m1_synthetic_mode_required')
    with (home/'.holder.lock').open('a+b') as holder:
        fcntl.flock(holder,fcntl.LOCK_EX|fcntl.LOCK_NB)
        engine=home/'engine';engine.mkdir(mode=0o700,exist_ok=True)
        # Some SDK notices print directly. No body/credential/error text leaves
        # this dedicated process through either stdout or stderr.
        with open(os.devnull,'w') as quiet, contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
            from .memory_sdk import Mem0Backend,Extractor,CallLedger
            ledger=CallLedger(home/'calls.sqlite3')
            extractor=Extractor(config['extraction'],ledger)
            backend=Mem0Backend(engine,config,ledger)
            authority=MemoryAuthority(home/'barriers.sqlite3',backend,extractor)
            server=MemoryHTTPServer(('127.0.0.1',args.port),authority,config['tokens'],ledger)
            def stop(*_):
                threading.Thread(target=server.shutdown,daemon=True).start()
            signal.signal(signal.SIGTERM,stop)
            signal.signal(signal.SIGINT,stop)
            try:
                server.serve_forever(poll_interval=.2)
            finally:
                server.server_close()
                authority.close();extractor.close();ledger.close()


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('memory_startup_failed:'+type(error).__name__,file=sys.stderr)
        raise SystemExit(1) from None
