"""Offline encoders and a disposable, local-only embedding cache."""

import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import sqlite3


PIPELINE = 'body-paragraph-char400-overlap80-v3'


def checked_vectors(vectors, count, dimension=None):
    if len(vectors) != count:
        raise ValueError('invalid_embedding_count')
    for vector in vectors:
        if (not vector or (dimension is not None and len(vector) != dimension)
                or not all(type(v) in (int, float) and math.isfinite(v) for v in vector)
                or not any(vector)):
            raise ValueError('invalid_embedding')
        dimension = len(vector)
    return vectors


def body_start(text):
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == '---':
        offset = len(lines[0])
        for line in lines[1:]:
            offset += len(line)
            if line.strip() in {'---', '...'}:
                return offset
        return len(text)
    return 0


def chunks(text):
    """Bounded overlapping windows cover the entire body, with original offsets."""
    start = body_start(text)
    boundaries = [*re.finditer(r'\r?\n[ \t]*\r?\n', text[start:]), None]
    paragraph_start = start
    for boundary in boundaries:
        end = start + boundary.start() if boundary else len(text)
        paragraph = text[paragraph_start:end]
        positions = () if re.fullmatch(r'\s{0,3}#{1,6}\s+[^\r\n]*(?:\r?\n)?', paragraph) else range(paragraph_start, end, 320)
        for position in positions:
            fragment = text[position:min(position + 400, end)]
            if fragment.strip():
                yield position, fragment
        paragraph_start = start + boundary.end() if boundary else len(text)


class LocalSemanticEncoder:
    """Never download during retrieval; accept only standard local ST modules."""

    def __init__(self, directory, query_prefix='', document_prefix=''):
        path = Path(directory).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('local_semantic_model_missing')
        modules = json.loads((path / 'modules.json').read_text())
        allowed = {'sentence_transformers.models.' + name
                   for name in ('Transformer', 'Pooling', 'Normalize', 'Dense')}
        if not isinstance(modules, list) or not modules or any(
                not isinstance(module,dict) or module.get('type') not in allowed for module in modules):
            raise ValueError('unsupported_semantic_model_modules')
        # Include weights, tokenizer, pooling, and encoding options. Replacing a
        # model in the same directory must not reuse vectors from its old version.
        digest = hashlib.sha256()
        for item in sorted(path.rglob('*')):
            if item.is_file() and '.cache' not in item.relative_to(path).parts:
                digest.update(str(item.relative_to(path)).encode())
                with item.open('rb') as file:
                    for block in iter(lambda: file.read(1024 * 1024), b''):
                        digest.update(block)
        runtime = [version(name) for name in ('sentence-transformers', 'transformers', 'torch')]
        digest.update(json.dumps([PIPELINE, query_prefix, document_prefix, runtime]).encode())
        self.cache_key = digest.hexdigest()
        self.query_prefix, self.document_prefix = query_prefix, document_prefix
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(str(path), device='cpu', local_files_only=True,
                                         trust_remote_code=False,
                                         model_kwargs={'use_safetensors': True})
        # No inference request can silently exceed the model's documented limit.
        self.model.max_seq_length = min(self.model.max_seq_length, 512)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False,
                                 batch_size=16).tolist()

    def encode_query(self, query):
        return self.encode([self.query_prefix + query])[0]

    def encode_documents(self, texts):
        return self.encode([self.document_prefix + text for text in texts])


class VectorCache:
    """No source text, title, path, or query is persisted in this cache."""

    def __init__(self, path):
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=30)
        try:
            self.db.execute('PRAGMA secure_delete=ON')
            self.db.execute('''CREATE TABLE IF NOT EXISTS vectors (
                scope TEXT NOT NULL, model TEXT NOT NULL, document TEXT NOT NULL,
                content_hash TEXT NOT NULL, position INTEGER NOT NULL,
                input_hash TEXT NOT NULL, vector TEXT NOT NULL,
                PRIMARY KEY(scope, model, document, position))''')
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def prune(self, scope, model, documents):
        current = {e['document_id']: e['content_hash'] for e, _ in documents}
        # Snapshot before mutation; other scopes have their own permission view.
        rows = self.db.execute('SELECT model,document,content_hash FROM vectors WHERE scope=?',
                               (scope,)).fetchall()
        with self.db:
            for old_model, doc, content_hash in rows:
                if old_model != model or current.get(doc) != content_hash:
                    self.db.execute('DELETE FROM vectors WHERE scope=? AND model=? AND document=?',
                                    (scope, old_model, doc))

    def get(self, scope, model, evidence, position, text):
        row = self.db.execute('''SELECT input_hash,vector FROM vectors
            WHERE scope=? AND model=? AND document=? AND content_hash=? AND position=?''',
            (scope, model, evidence['document_id'], evidence['content_hash'], position)).fetchone()
        if row is None or row[0] != hashlib.sha256(text.encode()).hexdigest():
            return None
        try:
            return checked_vectors([json.loads(row[1])], 1)[0]
        except (ValueError, TypeError):
            return None

    def put(self, scope, model, evidence, position, text, vector):
        self.db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?,?,?)',
                        (scope, model, evidence['document_id'], evidence['content_hash'], position,
                         hashlib.sha256(text.encode()).hexdigest(), json.dumps(vector)))


def semantic_scores(index, query, documents, encoder, provider, source_ids=None):
    """Filter permissions before this function; cached vectors never grant access."""
    scope = 'provider:' + provider if provider else 'local'
    if source_ids is not None:
        scope += ':sources:' + hashlib.sha256(json.dumps(sorted(set(source_ids))).encode()).hexdigest()
    model = getattr(encoder, 'cache_key', None)
    cache = VectorCache(index.path.parent / 'semantic.sqlite3') if model else None
    hits, misses = 0, 0
    try:
        if cache:
            cache.prune(scope, model, documents)
        query_vector = (encoder.encode_query(query) if hasattr(encoder, 'encode_query')
                        else checked_vectors(encoder.encode([query]), 1)[0])
        checked_vectors([query_vector], 1)
        passages, vectors = [], []
        for evidence, text in documents:
            for position, fragment in chunks(text):
                passages.append((evidence, position, fragment))
                vector = cache.get(scope, model, evidence, position, fragment) if cache else None
                if vector is not None and len(vector) != len(query_vector):
                    vector = None
                hits += vector is not None
                vectors.append(vector)
        missing = [i for i, vector in enumerate(vectors) if vector is None]
        # Bound inference memory; persist only after every batch is validated.
        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            texts = [passages[i][2] for i in batch]
            encoded = (encoder.encode_documents(texts) if hasattr(encoder, 'encode_documents')
                       else encoder.encode(texts))
            checked_vectors(encoded, len(batch), len(query_vector))
            for i, vector in zip(batch, encoded):
                vectors[i] = vector
        misses = len(missing)
        if cache:
            with cache.db:
                for i in missing:
                    evidence, position, text = passages[i]
                    cache.put(scope, model, evidence, position, text, vectors[i])
        scores, windows = {}, {}
        qnorm = math.sqrt(sum(v*v for v in query_vector))
        for (evidence, position, fragment), vector in zip(passages, vectors):
            score = sum(a*b for a,b in zip(query_vector, vector)) / (
                qnorm * math.sqrt(sum(v*v for v in vector)))
            doc = evidence['document_id']
            if doc not in scores or score > scores[doc]:
                scores[doc], windows[doc] = score, (position, position + len(fragment))
        return scores, windows, {'hits': hits, 'encoded': misses, 'persistent': cache is not None}
    finally:
        if cache:
            cache.close()
