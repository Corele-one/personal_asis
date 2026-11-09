from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from personal_asis.overview import snapshot
from personal_asis.dashboard import ASSETS
from datetime import datetime,timezone
stamp=datetime.now(timezone.utc).isoformat()
data=snapshot(Path('/nonexistent-synthetic'))
data.update(chat=dict(state='running',version='2.13.0',observed_at=stamp,source='AstrBot插件心跳'),
    router=dict(state='observed',total_requests=7,last_model='gemini-3.5-flash-lite',last_status='completed',label='本地调用观测，不是官方剩余额度',observed_at=stamp,source='Router本地调用账本'),
    mac=dict(state='stale',observed_at='2026-11-06T11:00:00+08:00',source='Mac最近同步检查'),
    pending=dict(journal=4,journal_observed_at='2026-11-06T11:00:00+08:00',feedback=1,feedback_unknown=0),
    recent=[dict(day='2026-11-09',source='主动随记原话',text='今天复习了加法器的进位结构。对并行前缀的连接方式还有一个问题，明天继续核对。<script>合成安全检查</script>',observed_at=stamp)])
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path.startswith('/api/session'):value=dict(authenticated=True,csrf='synthetic');body=json.dumps(value).encode();mime='application/json'
  elif self.path.startswith('/api/dashboard'):
   value=dict(astrbot=dict(records=[],reminders={}),mac=None,mac_content=None,life_baseline=None,tracking=dict(habits=[],learning=[]),attention=dict(goals=[],reports=[]),learning_history=dict(rows=[],available=False),learning_live=[])
   body=json.dumps(value).encode();mime='application/json'
  elif self.path.startswith('/api/overview'):body=json.dumps(data,ensure_ascii=False).encode();mime='application/json'
  elif self.path in ('/','/overview','/dashboard'):body=(ASSETS/'dashboard.html').read_bytes();mime='text/html; charset=utf-8'
  elif self.path=='/sw.js':body=b'';mime='application/javascript'
  else:
   file=ASSETS/Path(self.path).name
   if not file.is_file():self.send_error(404);return
   body=file.read_bytes();mime='text/css' if file.suffix=='.css' else 'application/javascript'
  self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(body)
server=HTTPServer(('127.0.0.1',0),Handler)
print(server.server_port,flush=True)
server.serve_forever()
