"""Pinned Mem0 OSS pilot, synthetic facts only, single-shot existing Google embedding."""
import contextlib,io,json,logging,os,resource,sys,time
from pathlib import Path
os.umask(0o077)
root=Path.home()/'.local/share/personal-asis-memory-pilot'
root.mkdir(mode=0o700,exist_ok=True)
os.environ['MEM0_TELEMETRY']='false';os.environ['MEM0_DIR']=str(root/'sdk')
logging.disable(logging.CRITICAL)
phase=sys.argv[1];receipt=root/('pilot-'+phase+'.json')
if receipt.exists():print(receipt.read_text());raise SystemExit()
report=dict(phase=phase,status='running',sdk='mem0ai==2.2.1',synthetic_only=True,automatic_extraction=False,real_llm_generations=0)
receipt.write_text(json.dumps(report))
started=time.monotonic()
try:
 with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
  from mem0 import Memory
  from google import genai
  from google.genai import types
  cfg=json.loads((Path.home()/'astrbot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
  source=next(s for s in cfg['provider_sources'] if s.get('type')=='googlegenai_chat_completion' and s.get('enable',True))
  keys=source['key'];key=keys[0] if isinstance(keys,list) else keys
  memory=Memory.from_config(dict(vector_store=dict(provider='qdrant',config=dict(path=str(root/'qdrant'),collection_name='synthetic_personal',embedding_model_dims=768)),
    history_db_path=str(root/'history.sqlite3'),embedder=dict(provider='gemini',config=dict(model='gemini-embedding-001',embedding_dims=768,api_key=key)),
    llm=dict(provider='gemini',config=dict(model='gemini-3.5-flash-lite',api_key=key))))
  def forbidden(*args,**kwargs):raise AssertionError('pilot_llm_generation_forbidden')
  memory.llm.generate_response=forbidden
  client=genai.Client(api_key=key,http_options=types.HttpOptions(base_url=source.get('api_base') or None,timeout=15000,retry_options=types.HttpRetryOptions(attempts=1)))
  budget=root/'pilot-budget.json'
  def embed(text,memory_action=None):
   count=json.loads(budget.read_text())['requests'] if budget.exists() else 0
   if count>=6:raise RuntimeError('pilot_embedding_cap_reached')
   budget.write_text(json.dumps(dict(requests=count+1)))
   response=client.models.embed_content(model='gemini-embedding-001',contents=text,config=types.EmbedContentConfig(output_dimensionality=768))
   return response.embeddings[0].values
  memory.embedding_model.embed=embed
  memory.embedding_model.embed_batch=lambda texts,memory_action=None:[embed(t,memory_action) for t in texts]
  user='synthetic-owner'
  if phase=='write':
   added=memory.add([dict(role='user',content='我偏好用中文解释电路原理。')],user_id=user,
    metadata=dict(source_message='synthetic-message-1',client='chat',kind='stable_preference',scope='circuit_explanations',revision=1),infer=False)
   identifier=added['results'][0]['id']
   found=memory.search('讲解电路时使用什么语言？',filters=dict(user_id=user),top_k=3)
   assert any(r['id']==identifier for r in found['results'])
   assert memory.get_all(filters=dict(user_id='other-synthetic-owner'))['results']==[]
   memory.update(identifier,text='我现在偏好用英文解释电路原理。',metadata=dict(source_message='synthetic-message-2',revision=2))
   found=memory.search('讲解电路时使用什么语言？',filters=dict(user_id=user),top_k=3)
   assert any('英文' in r['memory'] for r in found['results'])
   assert all('中文' not in r['memory'] for r in found['results'])
   history=memory.history(identifier);assert len(history)>=2
   (root/'synthetic-id.json').write_text(json.dumps(dict(id=identifier)))
   report.update(add_search_update_history=True,identity_isolation=True,source_metadata_retained=any(r.get('metadata',{}).get('revision')==2 for r in found['results']))
  elif phase=='verify':
   identifier=json.loads((root/'synthetic-id.json').read_text())['id']
   found=memory.get_all(filters=dict(user_id=user))
   assert any(r['id']==identifier and '英文' in r['memory'] for r in found['results'])
   memory.delete(identifier)
   assert memory.get_all(filters=dict(user_id=user))['results']==[]
   assert len(memory.history(identifier))>=3
   report.update(process_restart_persistence=True,delete_and_history=True)
  else:raise ValueError('unknown_phase')
  memory.vector_store.client.close();client.close()
 report.update(status='success',seconds=round(time.monotonic()-started,2),peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),embedding_requests_total=json.loads(budget.read_text())['requests'])
except Exception as error:
 report.update(status='failed_or_unknown',error_type=type(error).__name__)
 code=getattr(error,'code',None)
 if isinstance(code,int):report['http']=code
report['automatic_capture_enabled']=False
receipt.write_text(json.dumps(report));print(json.dumps(report))
