"""Opt-in local chunk retrieval. No model calls, legacy protocol or work DB changes."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import load_pa1_config, root_identity
from .data_policy import exclusion_reason
from .extractors import EXTRACTOR_VERSION
from .index import Index
from .retrieval import cosine, features
from .retrieval_time import in_window, note_date, question_window
from .semantic import body_start, checked_vectors


PROTOCOL = 'retrieval-v2.1'
RERANK_PROTOCOL = 'retrieval-v2.2'
QUALITY_PROTOCOL = 'retrieval-v2.3'
PIPELINE = 'paragraph-attribution-char400-overlap80-v1'
MAX_CANDIDATES = 200
MAX_SEMANTIC_CHUNKS = 10000


def literal_support(query, evidence):
    """Conservative lexical-only filter; never requires overlap for semantic retrieval."""
    terms = set(features(query))
    han = {t for t in terms if re.fullmatch(r'[\u3400-\u9fff]{2}', t)}
    if len(han) < 6:
        return True
    context = evidence['title'] + '\n' + ' '.join(evidence.get('section_path', [])) + '\n' + evidence['excerpt']
    if query.strip().casefold() in context.casefold():
        return True
    found = set(features(context))
    identifiers = {t for t in terms if re.fullmatch(r'[a-z][a-z0-9_]{1,}', t)} - {
        'the', 'of', 'in', 'on', 'at', 'to', 'and', 'or', 'is', 'are', 'for', 'how', 'what', 'does'}
    return len(han & found) >= 2 or bool(identifiers & found)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_url(url):
    """Conservative URL identity; keep meaningful queries, remove known tracking only."""
    from .reading_sources import origin_url
    url = origin_url(url)
    if not url:
        return None
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(sorted(query)), ''))


def attribution(line, reading=False):
    if not reading:
        return 'local_source_text'
    for prefix, kind in [('[作者原文', 'author_original'), ('[用户划线', 'user_highlight_of_author'),
                         ('[用户批注', 'user_annotation'), ('[用户页面笔记', 'user_annotation')]:
        if line.startswith(prefix):
            return kind
    return 'source_metadata'


def passages(text, reading=False):
    """Original Unicode character offsets; never mix author text with an annotation."""
    offset = 0
    section = []
    start = body_start(text)
    pending, beginning, kind, section_path = [], None, None, []
    fence = None

    def flush():
        if beginning is None:
            return []
        value = ''.join(pending).rstrip('\r\n')
        # Retain complete short paragraphs, bounded overlapping windows for long ones.
        return [(p, text[p:min(p + 400, beginning + len(value))], kind, list(section_path))
                for p in range(beginning, beginning + len(value), 320)]

    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        if line_start < start:
            continue
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker and fence is None:
            fence = marker[1][0]
        elif marker and marker[1][0] == fence:
            fence = None
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*$', line) if fence is None else None
        current_kind = attribution(line, reading)
        separator = (not line.strip() or heading or
                     reading and (current_kind == 'source_metadata' or current_kind != kind))
        if separator:
            yield from flush()
            pending, beginning = [], None
        if heading:
            level = len(heading[1])
            section = [(depth, name) for depth, name in section if depth < level]
            section.append((level, heading[2]))
            continue
        if not line.strip() or reading and current_kind == 'source_metadata':
            continue
        if beginning is None:
            beginning, kind, section_path = line_start, current_kind, [name for _, name in section]
        pending.append(line)
    yield from flush()


def location(text, start, end):
    return {'char_start': start, 'char_end': end, 'line_start': text.count('\n', 0, start) + 1,
            'line_end': text.count('\n', 0, max(start, end - 1)) + 1,
            'column_start': start - text.rfind('\n', 0, start)}


def _documents(index):
    result = {}
    rows = index.db.execute('''SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id
        WHERE d.active=1 AND s.enabled=1 AND s.available=1 ORDER BY d.document_id''').fetchall()
    for row in rows:
        current = index._current(row)
        if current is None:
            continue
        source, path, text, private = current
        provenance = None
        if source.reading_cache:
            from .reading import cache_metadata
            provenance = cache_metadata(source.root, row['path'])
            if provenance is None:
                continue
        recorded, basis = note_date(row['path'], text)
        extraction = index.db.execute('SELECT format,extractor_version FROM extractions WHERE document_id=?',
                                      (row['document_id'],)).fetchone()
        url = canonical_url(provenance['url']) if provenance else None
        kind = provenance['content_kind'] if provenance else 'local_text'
        completeness = ('metadata' if kind == 'metadata_only' else
                        'partial' if provenance or path.suffix.lower() != '.md' else 'full')
        base = {'protocol': PROTOCOL, 'document_id': row['document_id'],
                'content_hash': row['content_hash'], 'source_id': source.id,
                'source_type': 'reading_cache' if provenance else 'local_file',
                'source_item_id': provenance['item_id'] if provenance else row['document_id'],
                'node_id': index.config.node_id, 'root_identity': root_identity(source.root),
                'path_hint': row['path'], 'original_uri': path.as_uri(), 'title': row['title'][:120],
                'index_version': row['index_version'],
                'extraction_version': extraction['extractor_version'] if extraction else EXTRACTOR_VERSION,
                'format': extraction['format'] if extraction else path.suffix.lower().lstrip('.'),
                'chunk_version': PIPELINE, 'sensitivity': 'private' if private else 'normal',
                'canonical_url': url, 'source_url': provenance['url'] if provenance else None,
                'author': provenance['author'] or None if provenance else None,
                'original_publisher': None, 'created_at': None, 'updated_at': None,
                'published_at': provenance['published_at'] or None if provenance else None,
                'fetched_at': datetime.fromtimestamp(provenance['fetched_at'], timezone.utc).isoformat() if provenance else None,
                'record_date': recorded, 'record_date_basis': basis,
                'content_completeness': completeness, 'source_content_kind': kind,
                'selection_kind': ('personal_selection' if provenance['selected'] else 'subscription_arrival') if provenance else None,
                'authority': 'attributed_source_not_confirmed_user_fact',
                'availability': 'current_local', 'work_key': 'url:' + digest(url) if url else 'content:' + row['content_hash']}
        result[row['document_id']] = (base, text, source, private)
    return result


def _chunk_evidence(index, base, text, start, fragment, kind, section):
    end = start + len(fragment)
    positions = location(text, start, end)
    original = []
    extraction = index.db.execute('SELECT locations FROM extractions WHERE document_id=?',
                                  (base['document_id'],)).fetchone()
    if base['format'] != 'md' and extraction:
        original = [unit for unit in json.loads(extraction[0])
                    if unit['line_start'] <= positions['line_end'] and unit['line_end'] >= positions['line_start']]
    return {**base, 'chunk_id': digest(encoded([base['document_id'], base['content_hash'], PIPELINE, start, end])),
            **positions, 'section_path': section, 'content_kind': kind, 'excerpt': fragment,
            'attribution_actor': 'owner_annotation' if kind == 'user_annotation' else
                'original_author' if kind in ('author_original', 'user_highlight_of_author') else 'source_unspecified',
            'original_locations': original}


class RetrievalV2:
    """Disposable private sidecar. Base PA0 DB schema and reconciliation stay intact."""

    def __init__(self, index):
        self.index = index
        self.path = index.path.parent / 'retrieval-v2.sqlite3'
        if self.path.is_symlink():
            raise ValueError('v2_symlink_index_denied')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError('v2_unsupported_index_version')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS docs(document_id TEXT PRIMARY KEY, signature TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks(
                rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE NOT NULL,
                document_id TEXT NOT NULL, evidence TEXT NOT NULL, text TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunk_doc ON chunks(document_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(title, terms, tokenize='unicode61');
            PRAGMA user_version=1;
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def sync(self):
        """Rebuild changed chunks; remove stale/deleted/expired/index-revoked content."""
        documents = _documents(self.index)
        old = dict(self.db.execute('SELECT document_id,signature FROM docs'))
        changed = removed = 0
        with self.db:
            for doc in set(old) - set(documents):
                self._remove(doc)
                removed += 1
            for doc, (base, text, _, _) in documents.items():
                signature = digest(encoded(base))
                if old.get(doc) == signature:
                    continue
                self._remove(doc)
                for start, fragment, kind, section in passages(text, base['source_type'] == 'reading_cache'):
                    evidence = _chunk_evidence(self.index, base, text, start, fragment, kind, section)
                    chunk = evidence['chunk_id']
                    rowid = self.db.execute('INSERT INTO chunks(chunk_id,document_id,evidence,text) VALUES(?,?,?,?)',
                        (chunk, doc, encoded(evidence), fragment)).lastrowid
                    title = ' '.join(features(base['title'] + ' ' + ' '.join(section)).elements())
                    terms = ' '.join(features(fragment).elements())
                    self.db.execute('INSERT INTO lexical(rowid,title,terms) VALUES(?,?,?)', (rowid, title, terms))
                self.db.execute('INSERT INTO docs VALUES(?,?)', (doc, signature))
                changed += 1
        self.documents = documents
        return {'protocol': PROTOCOL, 'documents': len(documents), 'changed': changed, 'removed': removed,
                'chunks': self.db.execute('SELECT count(*) FROM chunks').fetchone()[0]}

    def _remove(self, doc):
        self.db.execute('DELETE FROM lexical WHERE rowid IN (SELECT rowid FROM chunks WHERE document_id=?)', (doc,))
        self.db.execute('DELETE FROM chunks WHERE document_id=?', (doc,))
        self.db.execute('DELETE FROM docs WHERE document_id=?', (doc,))

    def _allowed(self, provider, source_ids, channel, time_window=None):
        known = {s.id for s in self.index.config.sources}
        if source_ids is not None and (not source_ids or set(source_ids) - known):
            raise ValueError('v2_requires_known_source_ids')
        if channel not in ('local', 'pwa', 'feishu'):
            raise ValueError('v2_invalid_channel')
        # Fail closed on malformed windows even with an empty corpus.
        in_window(None, time_window)
        allowed = set()
        for doc, (e, _, source, private) in self.documents.items():
            if source_ids is not None and source.id not in source_ids:
                continue
            if not in_window(e['record_date'], time_window):
                continue
            if provider and (not source.allows_model(provider, private, e['path_hint'])
                             or e['content_completeness'] == 'metadata'):
                continue
            # V2 does not introduce a remote transport: strict existing reader grants gate exports.
            if channel != 'local' and not source.allows_remote_evidence(private, e['path_hint']):
                continue
            allowed.add(doc)
        return allowed

    def search(self, query, *, mode='hybrid', limit=20, provider=None, source_ids=None,
               encoder=None, channel='local', time_window=None, reranker=None,
               min_score=None, max_rerank_candidates=40, infer_time_window=True,
               quality_profile=None):
        if (not isinstance(query, str) or not query.strip() or len(query) > 512
                or type(limit) is not int or not 1 <= limit <= 100 or mode not in ('lexical', 'semantic', 'hybrid')):
            raise ValueError('v2_invalid_query')
        if provider and exclusion_reason('', query):
            raise ValueError('model_query_contains_credentials')
        if reranker is not None:
            from .reranking import validate_policy
            validate_policy(reranker, min_score, max_rerank_candidates)
        elif min_score is not None:
            raise ValueError('reranking_requires_local_model')
        if (type(infer_time_window) is not bool or quality_profile not in (None, 'strict-lexical-v1')
                or quality_profile is not None and reranker is None):
            raise ValueError('invalid_v2_quality_policy')
        self.sync()
        time_window = time_window if time_window is not None or not infer_time_window else question_window(query)
        allowed = self._allowed(provider, source_ids, channel, time_window)
        chunks = {r['chunk_id']: json.loads(r['evidence']) for r in self.db.execute('SELECT * FROM chunks')
                  if r['document_id'] in allowed}
        lex, sem, lexical_scores, semantic_scores = [], [], {}, {}
        if mode != 'semantic' or encoder is None:
            lex, lexical_scores = self._lexical(query, chunks)
        degradation = None
        effective = mode
        if mode in ('semantic', 'hybrid'):
            if encoder is None:
                degradation, effective = 'semantic_backend_unavailable', 'lexical'
            else:
                try:
                    if len(chunks) > MAX_SEMANTIC_CHUNKS:
                        raise ValueError('semantic_chunk_budget')
                    q = encoder.encode_query(query) if hasattr(encoder, 'encode_query') else encoder.encode([query])[0]
                    checked_vectors([q], 1)
                    ids = sorted(chunks)
                    for start in range(0, len(ids), 16):
                        batch = ids[start:start + 16]
                        texts = [chunks[c]['excerpt'] for c in batch]
                        values = encoder.encode_documents(texts) if hasattr(encoder, 'encode_documents') else encoder.encode(texts)
                        checked_vectors(values, len(batch), len(q))
                        semantic_scores.update((c, cosine(q, v)) for c, v in zip(batch, values))
                    sem = [c for c, score in sorted(semantic_scores.items(), key=lambda p: (-p[1], p[0])) if score > 0][:MAX_CANDIDATES]
                except (ImportError, OSError, RuntimeError, ValueError, TypeError, sqlite3.DatabaseError):
                    degradation, effective = 'semantic_inference_unavailable', 'lexical'
                    sem, semantic_scores = [], {}
                    lex, lexical_scores = self._lexical(query, chunks)
        filtered = 0
        if quality_profile is not None and effective == 'lexical':
            supported = [c for c in lex if literal_support(query, chunks[c])]
            filtered = len(lex) - len(supported)
            lex = supported
        rankings = [lex] if effective == 'lexical' else [sem] if effective == 'semantic' else [lex, sem]
        score = Counter()
        for ranking in rankings:
            for rank, chunk in enumerate(ranking, 1):
                score[chunk] += 1 / (60 + rank)
        # Exact original text remains a visible, bounded bonus; expansion never replaces it.
        exact = {c for c in score if query.casefold().strip() in
                 (chunks[c]['title'] + '\n' + chunks[c]['excerpt']).casefold()}
        if effective != 'semantic':
            for c in exact:
                score[c] += 1 / 61
        ranks = [{c: i for i, c in enumerate(ranking, 1)} for ranking in [lex, sem]]
        evidence, seen = [], {}
        for c in sorted(score, key=lambda c: (-score[c], c)):
            e = chunks[c]
            body = re.sub(r'^\[[^\]\n]+\]\s*', '', e['excerpt'], flags=re.M).strip()
            identity = (e['work_key'], e['content_kind'], digest(body))
            arrival = {k: e[k] for k in ('source_id', 'source_item_id', 'document_id', 'content_hash')}
            if identity in seen:
                seen[identity]['arrivals'].append(arrival)
                continue
            hit = {**e, 'arrivals': [arrival], 'ranking': {
                'lexical_rank': ranks[0].get(c), 'semantic_rank': ranks[1].get(c),
                'lexical_score': lexical_scores.get(c), 'semantic_score': semantic_scores.get(c),
                'exact_original': c in exact, 'rrf_score': score[c]}}
            seen[identity] = hit
            evidence.append(hit)
        quality = None
        if reranker is not None:
            from .reranking import rerank
            evidence, quality = rerank(query, evidence, reranker, min_score, max_rerank_candidates)
        policy = None
        if quality_profile is not None or not infer_time_window:
            policy = {'profile': quality_profile or 'legacy', 'infer_time_window': infer_time_window,
                      'lexical_support_filter_applied': quality_profile is not None and effective == 'lexical',
                      'weak_lexical_candidates_removed': filtered, 'semantic_sufficiency_verified': False}
        result = {'protocol': QUALITY_PROTOCOL if policy is not None else RERANK_PROTOCOL if quality is not None else PROTOCOL, 'mode': effective, 'requested_mode': mode,
                  'degradation': degradation, 'evidence': evidence[:limit], 'time_window': time_window,
                  'diagnostics': {'eligible_documents': len(allowed), 'eligible_chunks': len(chunks),
                                  'lexical_candidates': len(lex), 'semantic_candidates': len(sem),
                                  'fused_candidates': len(score), 'unique_passages': len(evidence),
                                  'candidate_limit': MAX_CANDIDATES, 'semantic_vectors_persisted': False}}
        if quality is not None:
            result['reranking'] = quality
        if policy is not None:
            result['retrieval_policy'] = policy
        return result

    def _lexical(self, query, chunks):
        tokens = list(features(query))[:128]
        if not tokens:
            return [], {}
        expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in tokens)
        # Permissions are checked before a candidate can enter any ranking or encoder.
        rows = self.db.execute('''SELECT c.chunk_id,bm25(lexical,3,1) AS score FROM lexical
            JOIN chunks c ON c.rowid=lexical.rowid WHERE lexical MATCH ? ORDER BY score,c.chunk_id''',
            (expression,)).fetchall()
        found = [(r['chunk_id'], -r['score']) for r in rows if r['chunk_id'] in chunks][:MAX_CANDIDATES]
        return [c for c, _ in found], dict(found)

    def expand(self, chunk_id, document_id, content_hash, *, neighbors=1, max_bytes=4096,
               provider=None, source_ids=None, channel='local'):
        if type(neighbors) is not int or not 0 <= neighbors <= 2 or type(max_bytes) is not int or not 256 <= max_bytes <= 16384:
            raise ValueError('v2_invalid_expansion_budget')
        self.sync()
        allowed = self._allowed(provider, source_ids, channel)
        rows = [json.loads(r[0]) for r in self.db.execute('SELECT evidence FROM chunks WHERE document_id=?', (document_id,))]
        rows.sort(key=lambda e: e['char_start'])
        position = next((i for i, e in enumerate(rows) if e['chunk_id'] == chunk_id and e['content_hash'] == content_hash), None)
        if document_id not in allowed or position is None:
            raise ValueError('v2_missing_stale_or_denied')
        selected = [rows[position]]
        if len(encoded(selected).encode()) > max_bytes:
            raise ValueError('v2_expansion_anchor_exceeds_budget')
        for delta in range(1, neighbors + 1):
            for i in (position - delta, position + delta):
                if 0 <= i < len(rows) and len(encoded(selected + [rows[i]]).encode()) <= max_bytes:
                    selected.append(rows[i])
        return sorted(selected, key=lambda e: e['char_start'])


def validate_evidence(index, evidence, provider, channel='local'):
    """Re-derive exact spans and provenance from fresh, permitted source bytes."""
    documents = _documents(index)
    for e in evidence:
        value = documents.get(e.get('document_id'))
        if value is None:
            raise ValueError('v2_context_stale')
        base, text, source, private = value
        if (provider is not None and not source.allows_model(provider, private, base['path_hint'])
                or base['content_completeness'] == 'metadata'
                or channel != 'local' and not source.allows_remote_evidence(private, base['path_hint'])):
            raise ValueError('v2_context_permission_revoked')
        expected = None
        for start, fragment, kind, section in passages(text, source.reading_cache):
            end = start + len(fragment)
            chunk = digest(encoded([base['document_id'], base['content_hash'], PIPELINE, start, end]))
            if chunk == e.get('chunk_id'):
                expected = _chunk_evidence(index, base, text, start, fragment, kind, section)
                break
        if expected is None or any(e.get(k) != v for k, v in expected.items()):
            raise ValueError('v2_context_identity_position_or_provenance_mismatch')


def cloud_evidence(evidence):
    return [{'id': 'E' + str(i + 1), 'title': e['title'], 'text': e['excerpt'],
             'content_kind': e['content_kind'], 'content_completeness': e['content_completeness'],
             'attribution_actor': e['attribution_actor'],
             'author': e['author'], 'url': e['canonical_url'], 'published_at': e['published_at'],
             'record_date': e['record_date'], 'authority': e['authority']} for i, e in enumerate(evidence)]


@dataclass
class ContextBundleV2:
    query: str
    provider: str
    evidence: list
    retrieval_mode: str
    max_bytes: int
    coverage: dict
    protocol: str = PROTOCOL
    reranking: dict | None = None
    retrieval_policy: dict | None = None

    def fingerprint(self):
        value = [self.protocol, self.query, self.provider, self.evidence, self.max_bytes]
        if self.reranking is not None:
            value.append(self.reranking)
        if self.retrieval_policy is not None:
            value.append(self.retrieval_policy)
        return digest(encoded(value))

    def cloud_input(self, home, channel='local'):
        if channel not in ('local', 'pwa', 'feishu'):
            raise ValueError('v2_invalid_channel')
        with Index(Path(home) / 'index.sqlite3', load_pa1_config(Path(home))) as index:
            validate_evidence(index, self.evidence, self.provider, channel)
        payload = _bundle_payload(self.protocol, self.query, self.evidence, self.reranking, self.retrieval_policy)
        if len(encoded(payload).encode()) > self.max_bytes:
            raise ValueError('v2_context_exceeds_budget')
        return payload


def _bundle_payload(protocol, query, evidence, reranking=None, retrieval_policy=None):
    payload = {'protocol': protocol, 'question': query, 'evidence': cloud_evidence(evidence)}
    if reranking is not None:
        payload['reranking'] = reranking
    if retrieval_policy is not None:
        payload['retrieval_policy'] = retrieval_policy
    return payload


def build_bundle_v2(home, query, *, provider='mimo', encoder=None, source_ids=None, mode='hybrid',
                    max_bytes=6144, channel='local', time_window=None, reranker=None,
                    min_score=None, max_rerank_candidates=40, infer_time_window=True,
                    quality_profile=None):
    if type(max_bytes) is not int or not 512 <= max_bytes <= 16384:
        raise ValueError('v2_invalid_context_budget')
    home = Path(home)
    with Index(home / 'index.sqlite3', load_pa1_config(home)) as index, RetrievalV2(index) as v2:
        result = v2.search(query, mode=mode, provider=provider, encoder=encoder,
                           source_ids=source_ids, channel=channel, limit=100, time_window=time_window,
                           reranker=reranker, min_score=min_score, max_rerank_candidates=max_rerank_candidates,
                           infer_time_window=infer_time_window, quality_profile=quality_profile)
    selected, works, covered = [], set(), set()
    candidates = list(result['evidence'])
    terms = set(features(query))
    while candidates and len(selected) < 20:
        # Prefer a new work and then uncovered query terms; deterministic rank breaks ties.
        position = 0 if reranker is not None else max(range(len(candidates)), key=lambda i: (
            candidates[i]['work_key'] not in works,
            len((set(features(candidates[i]['excerpt'])) & terms) - covered), -i))
        e = candidates.pop(position)
        payload = _bundle_payload(result['protocol'], query, selected + [e], result.get('reranking'), result.get('retrieval_policy'))
        if len(encoded(payload).encode()) > max_bytes:
            continue
        # Suppress strongly overlapping windows, while keeping distinct same-document paragraphs.
        if any(e['document_id'] == old['document_id'] and
               max(0, min(e['char_end'], old['char_end']) - max(e['char_start'], old['char_start']))
               > .5 * min(e['char_end'] - e['char_start'], old['char_end'] - old['char_start']) for old in selected):
            continue
        selected.append(e)
        works.add(e['work_key'])
        covered.update(set(features(e['excerpt'])) & terms)
    if not selected:
        raise ValueError('v2_no_evidence_within_authorized_budget')
    coverage = {'method': 'lexical_term_and_work_diversity_heuristic', 'independent_works': len(works),
                'covered_query_terms': len(covered), 'query_terms': len(terms),
                'semantic_coverage_verified': False, 'follow_up_performed': False,
                'degradation': result['degradation'], 'candidates': result['diagnostics']}
    if reranker is not None:
        coverage['method'] = 'local_cross_encoder_rank_then_byte_budget'
        coverage['reranking'] = result['reranking']
    if result.get('retrieval_policy') is not None:
        coverage['retrieval_policy'] = result['retrieval_policy']
    bundle = ContextBundleV2(query, provider, selected, result['mode'], max_bytes, coverage,
                             result['protocol'], result.get('reranking'), result.get('retrieval_policy'))
    bundle.cloud_input(home, channel)
    return bundle
