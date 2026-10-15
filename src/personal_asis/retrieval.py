"""Local ranked retrieval and provider-scoped, fresh Context Bundles."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from .config import load_pa1_config
from .index import Index
from .semantic import LocalSemanticEncoder, semantic_scores
from .data_policy import exclusion_reason


def features(text):
    terms = re.findall(r"[a-z0-9_]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run if len(run) == 1 else [run[i:i+2] for i in range(len(run)-1)])
    return Counter(terms)


def cosine(a, b):
    if len(a) != len(b) or not a or not all(math.isfinite(v) for v in [*a, *b]):
        raise ValueError("invalid_embedding")
    denominator = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b))
    return sum(x*y for x,y in zip(a,b)) / denominator if denominator else 0.0


def context_excerpt(text, query, max_chars=600, window=None):
    """Prefer substantive evidence over a matching heading; retain exact offsets."""
    if window is not None:
        start, end = window
        selected = context_excerpt(text[start:end], query, max_chars)
        relative = sum(len(line) for line in text[start:end].splitlines(keepends=True)
                       [:selected['line_start']-1]) + selected['column_start']-1
        absolute = start + relative
        offset = 0
        for i, line in enumerate(text.splitlines(keepends=True)):
            if absolute < offset + len(line):
                return {**selected, 'line_start':i+1, 'line_end':i+1,
                        'column_start':absolute-offset+1}
            offset += len(line)
        raise ValueError('invalid_semantic_evidence_window')
    lines = text.splitlines() or ['']
    start = 0
    if lines[0].strip() == '---':
        start = len(lines)
        for i in range(1, len(lines)):
            if lines[i].strip() in {'---', '...'}:
                start = i + 1
                break
    candidates = [i for i in range(start, len(lines)) if lines[i].strip()]
    body = [i for i in candidates if not re.match(r'^\s{0,3}#{1,6}\s', lines[i])]
    candidates = body or candidates
    if not candidates:
        return {'line_start':1, 'line_end':1, 'excerpt':'', 'column_start':1}
    terms = [term.lower() for term in query.split()]
    best = max(candidates, key=lambda i:sum(term in lines[i].lower() for term in terms))
    line = lines[best]
    positions = [line.lower().find(term) for term in terms if term in line.lower()]
    offset = max(0, (min(positions) if positions else 0) - 60)
    return {'line_start':best+1, 'line_end':best+1,
            'excerpt':line[offset:offset+max_chars], 'column_start':offset+1}


def retrieve(index, query, limit=5, provider=None, encoder=None, source_ids=None, time_window=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 512 or not 1 <= limit <= 20:
        raise ValueError("invalid_retrieval_query")
    if provider and exclusion_reason('',query):
        raise ValueError('model_query_contains_credentials')
    if source_ids is not None and (not source_ids or set(source_ids)-{s.id for s in index.config.sources}):
        raise ValueError('retrieval_requires_known_source_ids')
    from .retrieval_time import note_date,question_window,in_window
    time_window=time_window or question_window(query)
    lexical = index.search(query, "local", 100)
    lexical_ids = [hit["document_id"] for group in lexical["results"] for hit in group["replicas"]]
    documents, denied, stale = [], 0, 0
    rows = index.db.execute("""SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id
        WHERE d.active=1 AND s.enabled=1 AND s.available=1 ORDER BY d.document_id""").fetchall()
    for row in rows:
        if source_ids is not None and row['source_id'] not in source_ids:
            continue
        source = next(s for s in index.config.sources if s.id == row["source_id"])
        if provider and not source.allows_model(provider, row["policy"] == "private", row["path"]):
            denied += 1
            continue
        current = index._current(row)
        if current is None:
            stale += 1
            continue
        source, path, text, private = current
        if provider and not source.allows_model(provider, private, row["path"]):
            denied += 1
            continue
        recorded,basis=note_date(row['path'],text)
        if not in_window(recorded,time_window):
            continue
        selection = context_excerpt(text, query)
        evidence = {"document_id":row["document_id"], "content_hash":row["content_hash"],
                    "node_id":index.config.node_id, "source_id":source.id, "path_hint":row["path"],
                    "title":row["title"], "index_version":row["index_version"],
                    "original_uri":path.as_uri(), **selection}
        evidence['sensitivity']='private' if private else 'normal'
        if recorded:
            evidence.update(record_date=recorded,record_date_basis=basis)
        documents.append((evidence, text))
    by_id = {e["document_id"]:e for e,_ in documents}
    lexical_ids = [doc for doc in lexical_ids if doc in by_id]
    scores, mode, degradation = {}, "lexical", None
    cache_status = {'hits':0, 'encoded':0, 'persistent':False}
    if encoder is not None:
        try:
            scores, windows, cache_status = semantic_scores(index, query, documents, encoder, provider, source_ids)
            for evidence, text in documents:
                if evidence['document_id'] in windows:
                    evidence.update(context_excerpt(text, query, window=windows[evidence['document_id']]))
            mode = 'hybrid_semantic'
        except (ImportError, OSError, ValueError, RuntimeError, TypeError, sqlite3.DatabaseError):
            degradation = 'semantic_inference_or_cache_unavailable'
            encoder = None
            scores = {}
            # Evidence must follow the branch actually used for ranking.
            for evidence, text in documents:
                evidence.update(context_excerpt(text, query))
    if documents:
        if encoder is None:
            counters = [features(text) for _,text in documents]
            frequency = Counter(term for counter in counters for term in counter)
            q = features(query)
            def vector(counter):
                return {term:(1+math.log(count))*(1+math.log((len(counters)+1)/(frequency[term]+1)))
                        for term,count in counter.items()}
            qv = vector(q)
            norm = lambda v:math.sqrt(sum(x*x for x in v.values()))
            for (e,_),counter in zip(documents,counters):
                dv = vector(counter)
                denominator = norm(qv)*norm(dv)
                scores[e["document_id"]] = sum(v*dv.get(t,0) for t,v in qv.items())/denominator if denominator else 0
    ranked = [doc for doc,_ in sorted(scores.items(), key=lambda p:(-p[1],p[0])) if scores[doc]>0]
    fused = Counter()
    for ranking in (lexical_ids, ranked):
        for position,doc in enumerate(ranking):
            fused[doc] += 1/(60+position+1)
    hits, versions = [], set()
    for doc,_ in sorted(fused.items(), key=lambda p:(-p[1],p[0])):
        hit = by_id[doc]
        if hit["content_hash"] not in versions:
            versions.add(hit["content_hash"])
            hits.append(hit)
        if len(hits) == limit:
            break
    return {"mode":mode, "evidence":hits, "policy_denied":denied,
            "stale_candidates_skipped":stale, "semantic_enabled":encoder is not None,
            "degradation":degradation, "vector_cache":cache_status,'time_window':time_window}


@dataclass
class ContextBundle:
    query: str
    provider: str
    evidence: list
    retrieval_mode: str
    degradation: str | None = None

    def cloud_input(self):
        return {"question":self.query, "evidence":[{"id":f"E{i+1}","title":e["title"],
            "text":e["excerpt"],**({'note_date':e['record_date']} if 'record_date' in e else {})}
            for i,e in enumerate(self.evidence)]}

    def fingerprint(self):
        return hashlib.sha256(json.dumps({"query":self.query,"provider":self.provider,
            "evidence":[(e['document_id'],e['content_hash'],e['excerpt']) for e in self.evidence]},
            sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def revalidate(self, home):
        config = load_pa1_config(Path(home))
        with Index(Path(home)/"index.sqlite3",config) as index:
            for evidence in self.evidence:
                row = index.db.execute("""SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id
                    WHERE d.document_id=? AND d.active=1 AND s.enabled=1 AND s.available=1""",
                    (evidence['document_id'],)).fetchone()
                if row is None or row['content_hash'] != evidence['content_hash']:
                    raise ValueError("context_evidence_stale")
                current = index._current(row)
                if current is None:
                    raise ValueError("context_evidence_stale")
                source,path,text,private = current
                if 'record_date' in evidence:
                    from .retrieval_time import note_date
                    recorded,basis=note_date(row['path'],text)
                    if (recorded!=evidence['record_date'] or basis!=evidence.get('record_date_basis')):
                        raise ValueError('context_note_date_mismatch')
                if not source.allows_model(self.provider,private,row['path']):
                    raise ValueError("context_permission_revoked")
                if (evidence['sensitivity']!=('private' if private else 'normal')
                        or evidence['source_id']!=source.id or evidence['node_id']!=config.node_id
                        or evidence['path_hint']!=row['path'] or evidence['original_uri']!=path.as_uri()):
                    raise ValueError('context_identity_or_sensitivity_mismatch')
                lines=text.splitlines() or ['']
                line,column=evidence['line_start']-1,evidence['column_start']-1
                if (not 0<=line<len(lines) or column<0 or evidence['line_end']!=line+1
                        or evidence['title']!=row['title'][:120]
                        or lines[line][column:column+len(evidence['excerpt'])]!=evidence['excerpt']):
                    raise ValueError("context_content_mismatch")


def build_bundle(home, query, provider="mimo", encoder=None, source_ids=None, time_window=None):
    config = load_pa1_config(Path(home))
    with Index(Path(home)/"index.sqlite3",config) as index:
        result = retrieve(index,query,3,provider,encoder,source_ids,time_window)
    if not result['evidence']:
        raise ValueError("no_current_provider_authorized_evidence")
    for evidence in result['evidence']:
        evidence['title'] = evidence['title'][:120]
    return ContextBundle(query,provider,result['evidence'],result['mode'],result['degradation'])
