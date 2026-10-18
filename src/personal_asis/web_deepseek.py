"""Opt-in DeepSeek Search with deferred public body snapshots; MiMo unchanged.

The remote arbitrary-URL Fetch API is deliberately not exposed. Body content
comes from the explicit public search, then a local DNS-pinned GET verifies
the target/redirect path before any numbered evidence is released.
"""
from datetime import datetime,timezone,timedelta
import json
import re
from urllib.parse import urlsplit

from .credentials import CredentialStore
from .web_search import PublicHTTP,WebError,public_query,url_shape,utcnow,InertHTML


class DeepSeekProvider:
    name='deepseek-search-body+local-verified-v1'

    def __init__(self,http=None,store=None,pages=None):
        self.http=http or PublicHTTP()
        self.store=store or CredentialStore('deepseek','local.personal-asis.web')
        self.pages=pages if pages is not None else {}

    def search_web(self,query,max_results=5,recency_days=None):
        public_query(query)
        if len(query)>128 or type(max_results) is not int or not 1<=max_results<=5:
            raise WebError('web_invalid_search_limit')
        if recency_days is not None and (type(recency_days) is not int or not 1<=recency_days<=365):
            raise WebError('web_invalid_recency')
        # No ori_question, localization, personal context, or chat-model call.
        request={'query':query,'count':max_results,'need_content':True}
        _,raw,_=self.http.request('https://api.deepseek.com/v1/tools/search',
            body=json.dumps(request).encode(),credential=self.store.get())
        data=json.loads(raw)
        if not isinstance(data,dict) or not isinstance(data.get('results'),list):
            raise WebError('web_search_schema_unsupported')
        results,pages,gaps=[],{},[]
        now=datetime.now(timezone.utc)
        for row in data['results'][:max_results]:
            try:
                original_url=row['url']
                # Discovery may advertise an HTTP canonical. Never visit it;
                # try only its HTTPS form and use the locally fetched body.
                candidate='https://'+original_url[7:] if isinstance(original_url,str) and original_url.startswith('http://') else original_url
                if isinstance(candidate,str):candidate=urlsplit(candidate)._replace(fragment='').geturl()
                try:url=url_shape(candidate)
                except WebError:gaps.append('result_target_denied');continue
                date=row.get('date')
                try:parsed=datetime.fromisoformat(date.replace('Z','+00:00')) if date else None
                except (ValueError,AttributeError):
                    parsed=None;date=None;gaps.append('publication_date_invalid_treated_as_unknown')
                if parsed and parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
                if recency_days and (not parsed or not now-timedelta(days=recency_days)<=parsed<=now):
                    gaps.append('unknown_or_outside_reported_publication_window');continue
                result={'url':url,'title':str(row.get('title') or '')[:160],
                    'excerpt':str(row.get('snippet') or row.get('summary') or '')[:600],
                    'source_type':'public_web','content_kind':'search_snippet','content_completeness':'summary',
                    'published_at':date,'publication_date_status':'provider_reported_unverified' if date else 'unknown',
                    'fetched_at':utcnow(),'author':None}
                results.append(result)
                if isinstance(original_url,str) and urlsplit(original_url)._replace(fragment='').geturl()==url and isinstance(row.get('content'),str) and len(row['content'].strip())>=40:
                    pages[url]={**result,'content':row['content'][:6000]}
            except (ValueError,KeyError,TypeError,AttributeError):
                gaps.append('result_metadata_invalid_or_target_denied')
        self.pages.update(pages)
        return {'status':'ok' if results else 'no_results','results':results,'pages':pages,
                'gaps':sorted(set(gaps)),'provider':self.name,'billing':'provider_cost_unknown',
                'recency_policy':'local_filter_reported_dates_only'}

    def fetch_web(self,url,max_chars=2400):
        if type(max_chars) is not int or not 200<=max_chars<=2400:
            raise WebError('web_invalid_read_limit')
        # Strict local preflight includes response size, DNS pinning and every
        # redirect. A remote search body cannot authorize a different target.
        final,raw,kind=self.http.request(url)
        saved=self.pages.get(url)
        if saved and final==url and 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(saved['fetched_at'])).total_seconds()<=3600:
            text=saved['content'];title=saved['title'];reader='deepseek_search_body_local_target_verified'
            published=saved['published_at'];date_status=saved['publication_date_status'];fetched=saved['fetched_at']
        else:
            text=raw.decode('utf-8','replace');parser=InertHTML()
            if 'html' in kind:parser.feed(text);text=''.join(parser.parts)
            title=''.join(parser.title_parts).strip()[:160] or final
            reader='local_static_no_matching_provider_body';published=None;date_status='unknown';fetched=utcnow()
        text=re.sub(r'\n[ \t]*\n+', '\n\n',text).strip()
        if len(text)<40:raise WebError('web_body_unavailable_or_incomplete')
        return {'status':'ok','url':final,'requested_url':url,'title':title,'excerpt':text[:max_chars],
                'source_type':'public_web','content_kind':'web_body','content_completeness':'partial',
                'published_at':published,'publication_date_status':date_status,'fetched_at':fetched,
                'author':None,'reader':reader,'billing':'provider_cost_unknown',
                'limitations':'provider search snapshot or bounded static body; local URL path verified; no original character offsets'}
