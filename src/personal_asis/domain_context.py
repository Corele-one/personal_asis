"""Explicit owner-confirmed goals/constraints, isolated by domain and source roots.

No inferred memories, role spawning, scheduler, historical-note archive or grants.
"""

import json
from pathlib import Path
import time

from .config import load_pa1_config, root_identity
from .data_policy import exclusion_reason
from .work import ROLES, WorkStore, encoded, fingerprint


REVIEW_SECONDS=90*86400
HEADER='\n\n本人明确配置的本次领域目标和约束（不是个人事实推断，也不扩大来源或工具授权）：\n'


class DomainContexts:
    def __init__(self, home, clock=time.time):
        self.home=Path(home)
        self.clock=clock
        self.work=WorkStore(self.home/'work.sqlite3',clock)
        self.db=self.work.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS domain_contexts (
                domain TEXT PRIMARY KEY, revision INTEGER NOT NULL, goal TEXT,
                constraints_text TEXT, roots TEXT NOT NULL, model_allowed INTEGER NOT NULL,
                confirmed_at REAL NOT NULL, review_after REAL NOT NULL, deleted INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS domain_context_updates (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, domain TEXT NOT NULL,
                revision INTEGER NOT NULL);
        ''')

    def __enter__(self): return self
    def __exit__(self,*args): self.work.close()

    def _domain(self, domain):
        if domain not in ROLES:
            raise ValueError('domain_context_unknown_domain')

    def show(self, domain):
        self._domain(domain)
        row=self.db.execute('SELECT * FROM domain_contexts WHERE domain=?',(domain,)).fetchone()
        if row is None:
            raise ValueError('domain_context_not_found')
        return {'domain':row['domain'],'revision':row['revision'],'goal':row['goal'],
                'constraints':row['constraints_text'],'roots':json.loads(row['roots']),
                'model_allowed':bool(row['model_allowed']),'confirmed_at':row['confirmed_at'],
                'review_after':row['review_after'],'needs_review':self.clock()>=row['review_after'],
                'deleted':bool(row['deleted'])}

    def list(self):
        return [{k:v for k,v in self.show(row[0]).items() if k not in ('goal','constraints','roots')}
                for row in self.db.execute('SELECT domain FROM domain_contexts ORDER BY domain')]

    def _id(self, request_id):
        if not isinstance(request_id,str) or not 1<=len(request_id)<=96:
            raise ValueError('domain_context_request_id_required')

    def _duplicate(self, request_id, digest):
        old=self.db.execute('SELECT * FROM domain_context_updates WHERE id=?',(request_id,)).fetchone()
        if old:
            if old['fingerprint']!=digest:
                raise ValueError('domain_context_request_conflict')
            return True
        return False

    def _clear_sessions(self, domain):
        # No stale goal/constraint can survive as a paid-step transcript or result.
        rows=self.db.execute('SELECT run,payload FROM agent_sessions WHERE payload IS NOT NULL').fetchall()
        cleared=0
        for row in rows:
            state=json.loads(row['payload']);binding=state.get('domain_context')
            selected=state.get('role_contexts',{}).get(domain,{})
            if (binding and binding['domain']==domain) or 'binding' in selected:
                self.work.clean(self.work._run(row['run'])['delegation'])
                cleared+=1
        return cleared

    def set(self, domain, goal, constraints, source_ids, request_id, *, allow_model=False, expected_revision=None):
        self._domain(domain);self._id(request_id)
        if (not isinstance(goal,str) or not goal.strip() or len(goal)>2000
                or not isinstance(constraints,str) or len(constraints)>4000
                or exclusion_reason('',goal+'\n'+constraints) or type(allow_model) is not bool):
            raise ValueError('domain_context_invalid_or_credential_input')
        if (not isinstance(source_ids,list) or not source_ids
                or any(not isinstance(s,str) or not s for s in source_ids)):
            raise ValueError('domain_context_explicit_sources_required')
        sources={s.id:s for s in load_pa1_config(self.home).sources}
        if set(source_ids)-set(sources):
            raise ValueError('domain_context_source_not_configured')
        roots={sid:root_identity(sources[sid].root) for sid in sorted(set(source_ids))}
        if allow_model and any(not sources[sid].index or 'mimo' not in sources[sid].model_providers
                               or not (sources[sid].model_all_files or sources[sid].model_paths) for sid in roots):
            raise ValueError('domain_context_source_model_permission_denied')
        digest=fingerprint(['set',domain,goal,constraints,roots,allow_model])
        with self.work.transaction():
            if self._duplicate(request_id,digest):
                return {**self.show(domain),'replayed_update':True,'sessions_cleared':0}
            old=self.db.execute('SELECT revision FROM domain_contexts WHERE domain=?',(domain,)).fetchone()
            if expected_revision is not None and expected_revision!=(old[0] if old else 0):
                raise ValueError('domain_context_revision_conflict')
            revision=old[0]+1 if old else 1
            self.db.execute('INSERT OR REPLACE INTO domain_contexts VALUES(?,?,?,?,?,?,?,?,0)',
                (domain,revision,goal,constraints,encoded(roots),int(allow_model),self.clock(),self.clock()+REVIEW_SECONDS))
            self.db.execute('INSERT INTO domain_context_updates VALUES(?,?,?,?)',(request_id,digest,domain,revision))
        return {**self.show(domain),'replayed_update':False,'sessions_cleared':self._clear_sessions(domain)}

    def forget(self, domain, request_id, *, expected_revision=None):
        self._domain(domain);self._id(request_id)
        digest=fingerprint(['forget',domain])
        with self.work.transaction():
            if self._duplicate(request_id,digest):
                return {**self.show(domain),'replayed_update':True,'sessions_cleared':0}
            current=self.show(domain)
            if expected_revision is not None and expected_revision!=current['revision']:
                raise ValueError('domain_context_revision_conflict')
            revision=current['revision']+1
            self.db.execute('''UPDATE domain_contexts SET revision=?,goal=NULL,constraints_text=NULL,
                roots='{}',model_allowed=0,confirmed_at=?,review_after=?,deleted=1 WHERE domain=?''',
                (revision,self.clock(),self.clock(),domain))
            self.db.execute('INSERT INTO domain_context_updates VALUES(?,?,?,?)',(request_id,digest,domain,revision))
        return {**self.show(domain),'replayed_update':False,'sessions_cleared':self._clear_sessions(domain)}

    def for_model(self, domain, source_ids):
        value=self.show(domain)
        if value['deleted'] or not value['model_allowed'] or value['needs_review']:
            raise ValueError('domain_context_not_approved_or_needs_review')
        if not source_ids or not set(source_ids)<=set(value['roots']):
            raise ValueError('domain_context_source_scope_denied')
        sources={s.id:s for s in load_pa1_config(self.home).sources}
        for sid,identity in value['roots'].items():
            source=sources.get(sid)
            if (source is None or not source.root.is_dir() or root_identity(source.root)!=identity
                    or not source.index or 'mimo' not in source.model_providers
                    or not (source.model_all_files or source.model_paths)):
                raise ValueError('domain_context_source_permission_changed')
        return {k:v for k,v in value.items() if k!='needs_review'}


def validate_binding(home, binding, source_ids):
    with DomainContexts(home) as contexts:
        current=contexts.for_model(binding['domain'],source_ids)
    if fingerprint(current)!=fingerprint(binding):
        raise ValueError('domain_context_changed_or_revoked')
    return current


def prompt_context(prompt, binding):
    return prompt+HEADER+encoded({k:binding[k] for k in ('domain','goal','constraints')})
