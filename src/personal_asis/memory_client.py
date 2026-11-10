"""Thin no-cache/no-retry client contract; not yet installed into Chat or Work."""
import json
import re
from urllib.error import HTTPError,URLError
from urllib.request import HTTPRedirectHandler,Request,build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise URLError('redirect_denied')


class MemoryClient:
    def __init__(self,token,*,timeout=60,opener=None):
        self.token,self.timeout=token,timeout
        self.opener=opener or build_opener(NoRedirect())

    def call(self,action,arguments=None):
        request=Request('http://127.0.0.1:23101/v1/memory',method='POST',
            data=json.dumps(dict(action=action,arguments=arguments or {}),ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                value=json.loads(response.read(1024*1024+1))
            return dict(available=True,ok=True,result=value)
        except HTTPError as error:
            with error:
                try:value=json.loads(error.read(2048))
                except Exception:value={}
            code=value.get('error')
            return dict(available=True,ok=False,error=code if isinstance(code,str) and re.fullmatch('memory_[a-z0-9_]+',code)
                else 'memory_request_failed')
        except (OSError,URLError,ValueError,TypeError):
            return dict(available=False,ok=False,error='memory_unavailable_or_unknown_no_retry',
                mutation_result_unknown=action in ('capture','withdraw','preview'))
