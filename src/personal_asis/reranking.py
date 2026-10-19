"""Optional, offline-only passage reranking. Never selects a cloud provider."""

import hashlib
import json
import math
from pathlib import Path
import re


class LocalCrossEncoder:
    """Load a standard local Safetensors classifier; downloading is a setup task."""

    def __init__(self, directory):
        path = Path(directory).expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise ValueError('local_reranker_missing')
        required = ('config.json', 'model.safetensors', 'tokenizer_config.json', 'tokenizer.json')
        if any(not (path / name).is_file() or (path / name).is_symlink() for name in required):
            raise ValueError('local_reranker_files_missing_or_unsafe')
        config = json.loads((path / 'config.json').read_text())
        tokenizer_config = json.loads((path / 'tokenizer_config.json').read_text())
        if (config.get('model_type') not in ('bert', 'xlm-roberta') or config.get('auto_map')
                or tokenizer_config.get('auto_map') or config.get('num_labels', 1) != 1
                or len(config.get('id2label', {'0': 'score'})) != 1):
            raise ValueError('unsupported_local_reranker')
        digest = hashlib.sha256()
        for name in (*required, 'special_tokens_map.json', 'sentencepiece.bpe.model'):
            item = path / name
            if not item.exists():
                continue
            if item.is_symlink():
                raise ValueError('unsafe_local_reranker_file')
            digest.update(name.encode())
            with item.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
        from importlib.metadata import version
        digest.update(json.dumps([version('transformers'), version('torch'),
                                  'raw-logit-query128-pair512-v1']).encode())
        self.cache_key = digest.hexdigest()
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True,
                                                           trust_remote_code=False, token=False)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                str(path), local_files_only=True, trust_remote_code=False, use_safetensors=True, token=False)
            self.model.to('cpu').eval()
        except (ImportError, OSError, ValueError, RuntimeError, TypeError):
            raise ValueError('local_reranker_unavailable') from None

    def score(self, query, passages):
        try:
            return self._score(query, passages)
        except (ImportError, OSError, ValueError, RuntimeError, TypeError):
            raise ValueError('local_reranker_scoring_failed') from None

    def _score(self, query, passages):
        if (not isinstance(query, str) or not query.strip() or len(query) > 512
                or not isinstance(passages, list) or len(passages) > 100
                or any(not isinstance(p, str) or not p or len(p) > 800 for p in passages)):
            raise ValueError('rerank_input_budget')
        if len(self.tokenizer.encode(query, add_special_tokens=False)) > 128:
            raise ValueError('rerank_query_token_budget')
        import torch
        values = []
        with torch.inference_mode():
            for start in range(0, len(passages), 8):
                batch = passages[start:start + 8]
                inputs = self.tokenizer([query] * len(batch), batch, padding=True,
                                        truncation='only_second', max_length=512, return_tensors='pt')
                scores = self.model(**inputs).logits
                if scores.shape != (len(batch), 1):
                    raise ValueError('invalid_reranker_output')
                values.extend(scores[:, 0].tolist())
        if any(not math.isfinite(v) for v in values):
            raise ValueError('invalid_reranker_output')
        return values


def validate_policy(scorer, min_score, max_candidates):
    if (type(min_score) not in (int, float) or not math.isfinite(min_score)
            or type(max_candidates) is not int or not 1 <= max_candidates <= 100
            or not callable(getattr(scorer, 'score', None))
            or not isinstance(getattr(scorer, 'cache_key', None), str)
            or not re.fullmatch('[0-9a-f]{64}', scorer.cache_key)):
        raise ValueError('invalid_reranking_policy')


def rerank(query, evidence, scorer, min_score, max_candidates):
    """A score is a model-specific relevance logit, never a truth probability."""
    validate_policy(scorer, min_score, max_candidates)
    pool = evidence[:max_candidates]
    scores = scorer.score(query, [e['title'] + '\n' + e['excerpt'] for e in pool]) if pool else []
    if (not isinstance(scores, (list, tuple)) or len(scores) != len(pool)
            or any(type(s) not in (int, float) or not math.isfinite(s) for s in scores)):
        raise ValueError('invalid_reranker_output')
    # Literal original queries are bounded discovery anchors, not an answer-quality assertion.
    ranked = sorted(zip(pool, scores), key=lambda item: (
        not item[0]['ranking']['exact_original'], -item[1], item[0]['chunk_id']))
    kept = [{**e, 'ranking': {**e['ranking'], 'reranker_score': s,
                              'reranking_basis': 'exact_original' if e['ranking']['exact_original'] else 'model_score'}}
            for e, s in ranked if s >= min_score or e['ranking']['exact_original']]
    return kept, {'method': 'local_cross_encoder_exact_anchor_v1', 'model_fingerprint': scorer.cache_key,
                  'min_score': min_score, 'max_candidates': max_candidates, 'scored': len(pool),
                  'unscored': len(evidence) - len(pool), 'rejected': len(pool) - len(kept),
                  'protected_exact_anchors': sum(e['ranking']['exact_original'] for e in kept),
                  'state': 'candidates_only' if kept else 'no_relevant_evidence',
                  'answer_sufficiency_verified': False}
