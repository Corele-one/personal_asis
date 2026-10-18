import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.config import load_pa1_config
from personal_asis.index import Index
from personal_asis.retrieval import build_bundle
from personal_asis.retrieval_eval import fixture, cases, evaluate
from personal_asis.retrieval_v2 import (RetrievalV2, build_bundle_v2, canonical_url, encoded,
                                        location, passages)


class Encoder:
    def __init__(self, broken=False):
        self.seen = []
        self.broken = broken

    def encode_query(self, query):
        if self.broken:
            raise RuntimeError('synthetic_failure')
        return [1., 0.]

    def encode_documents(self, texts):
        self.seen.extend(texts)
        return [[1., 0.] if '副本' in t else [0., 1.] for t in texts]


class RetrievalV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        fixture(self.home)

    def config(self, edit):
        path = self.home / 'sources.yaml'
        data = json.loads(path.read_text())
        edit(data)
        path.write_text(json.dumps(data))

    def search(self, query, **kwargs):
        with Index(self.home / 'index.sqlite3', load_pa1_config(self.home)) as index, RetrievalV2(index) as v2:
            return v2.search(query, **{'mode': 'lexical', 'provider': 'mimo', **kwargs})

    def reconcile(self):
        with Index(self.home / 'index.sqlite3', load_pa1_config(self.home)) as index:
            index.reconcile()

    def expand(self, e, **kwargs):
        with Index(self.home / 'index.sqlite3', load_pa1_config(self.home)) as index, RetrievalV2(index) as v2:
            return v2.expand(e['chunk_id'], e['document_id'], e['content_hash'], provider='mimo', **kwargs)

    def test_chinese_question_uses_keyword_components(self):
        result = self.search('多个处理器如何维护缓存副本一致性')
        self.assertIn('缓存一致性协议', result['evidence'][0]['excerpt'])
        self.assertIsNotNone(result['evidence'][0]['ranking']['lexical_rank'])

    def test_english_exact_name_and_title(self):
        for query, expected in [('cache invalidation', 'english.md'), ('Ada Lovelace', 'person.md'),
                                ('精确标题青铜计划', 'title.md')]:
            result = self.search(query)
            self.assertEqual(result['evidence'][0]['path_hint'], expected)
            self.assertTrue(result['evidence'][0]['ranking']['exact_original'])

    def test_multiple_same_document_passages_are_candidates(self):
        evidence = self.search('协议甲与协议乙对比')['evidence']
        hits = [e for e in evidence if e['path_hint'] == 'protocols.md']
        self.assertEqual(len(hits), 2)
        self.assertEqual(len({e['chunk_id'] for e in hits}), 2)
        self.assertEqual(len({e['document_id'] for e in hits}), 1)

    def test_tail_and_neighbor_offsets_round_trip(self):
        hit = self.search('长文尾部尾声结论')['evidence'][0]
        expanded = self.expand(hit, max_bytes=10000)
        self.assertTrue(any('窗口边界' in e['excerpt'] for e in expanded))
        text = (self.home / 'source/long.md').read_text()
        self.assertGreater(hit['char_start'], 6000)
        for e in expanded:
            self.assertEqual(text[e['char_start']:e['char_end']], e['excerpt'])
            self.assertEqual(e['section_path'], ['长文', '尾部'] if '尾声' in e['excerpt'] or '窗口边界' in e['excerpt'] else ['长文'])

    def test_multiline_crlf_unicode_and_long_window_positions(self):
        text = '---\r\nsensitivity: normal\r\n---\r\n# 一级\r\n\r\n第一行😀\r\n第二行证据。\r\n\r\n## 二级\r\n' + '长行汉字😀' * 180
        found = list(passages(text))
        self.assertGreater(len(found), 2)
        self.assertIn('\r\n', found[0][1])
        self.assertEqual(found[0][3], ['一级'])
        for start, fragment, _, _ in found:
            self.assertEqual(fragment, text[start:start + len(fragment)])
            self.assertLessEqual(len(fragment), 400)
            loc = location(text, start, start + len(fragment))
            self.assertEqual(loc['line_start'], text.count('\n', 0, start) + 1)
        self.assertEqual(found[-1][0] + len(found[-1][1]), len(text))

    def test_native_office_paragraph_locations_survive_chunk_retrieval(self):
        from test_formats import word
        (self.home / 'source/native.docx').write_bytes(word('native paragraph locator evidence'))
        self.config(lambda d: d['sources'][0].update(
            formats=['md', 'docx'], model_paths=d['sources'][0]['model_paths'] + ['native.docx']))
        self.reconcile()
        hit = self.search('native paragraph locator')['evidence'][0]
        self.assertEqual(hit['format'], 'docx')
        self.assertTrue(any(unit.get('paragraph') == 2 for unit in hit['original_locations']))
        self.assertEqual(hit['content_completeness'], 'partial')
        bundle = build_bundle_v2(self.home, 'native paragraph locator', mode='lexical')
        self.assertTrue(bundle.cloud_input(self.home)['evidence'])

    def test_semantic_retains_chunk_scores_and_separate_mode(self):
        encoder = Encoder()
        result = self.search('没有词项重合的改写', mode='semantic', encoder=encoder)
        self.assertEqual(result['mode'], 'semantic')
        self.assertTrue(result['evidence'])
        self.assertIsNone(result['evidence'][0]['ranking']['lexical_rank'])
        self.assertIsNotNone(result['evidence'][0]['ranking']['semantic_rank'])

    def test_hybrid_fusion_is_explainable(self):
        result = self.search('缓存一致性', mode='hybrid', encoder=Encoder())
        hit = result['evidence'][0]
        self.assertTrue(hit['ranking']['exact_original'])
        self.assertAlmostEqual(hit['ranking']['rrf_score'],
            1 / (60 + hit['ranking']['lexical_rank']) + 1 / (60 + hit['ranking']['semantic_rank']) + 1 / 61)

    def test_semantic_failure_degrades_to_independent_lexical(self):
        for encoder in [None, Encoder(broken=True)]:
            result = self.search('流水线', mode='semantic', encoder=encoder)
            self.assertEqual(result['mode'], 'lexical')
            self.assertTrue(result['degradation'])
            self.assertIn('流水线', result['evidence'][0]['excerpt'])

    def test_malformed_embedding_degrades_without_partial_semantic_ranks(self):
        encoder = Encoder()
        encoder.encode_documents = lambda texts: [[float('nan')]] * len(texts)
        result = self.search('流水线', mode='hybrid', encoder=encoder)
        self.assertEqual(result['mode'], 'lexical')
        self.assertEqual(result['diagnostics']['semantic_candidates'], 0)

    def test_no_provider_denied_text_is_encoded(self):
        encoder = Encoder()
        result = self.search('副本', mode='hybrid', encoder=encoder)
        self.assertFalse(any('紫色猎鹰' in t for t in encoder.seen))
        self.assertFalse(any(e['path_hint'] == 'denied.md' for e in result['evidence']))
        self.assertFalse((self.home / 'semantic.sqlite3').exists())

    def test_no_channel_denied_text_is_encoded(self):
        encoder = Encoder()
        result = self.search('副本', mode='hybrid', encoder=encoder, channel='feishu')
        self.assertFalse(result['evidence'])
        self.assertEqual(encoder.seen, [])

    def test_source_scope_precedes_semantic_encoding(self):
        encoder = Encoder()
        self.search('延迟', mode='hybrid', encoder=encoder, source_ids=['reading_folo'])
        self.assertTrue(encoder.seen)
        self.assertFalse(any('睡前记录' in t for t in encoder.seen))
        with self.assertRaisesRegex(ValueError, 'known_source'):
            self.search('延迟', source_ids=['unknown'])

    def test_metadata_only_is_not_body_evidence(self):
        self.assertEqual(self.search('量子香蕉缺少正文')['evidence'], [])
        # Metadata discovery stays a separate future API; the chunk index has no fake bodies.
        self.assertEqual(self.search('量子香蕉缺少正文', provider=None)['evidence'], [])

    def test_external_duplicate_arrivals_are_one_passage(self):
        evidence = self.search('互连延迟')['evidence']
        hits = [e for e in evidence if e['content_kind'] == 'author_original']
        self.assertEqual(len(hits), 1)
        self.assertEqual(len(hits[0]['arrivals']), 2)
        self.assertEqual(hits[0]['content_completeness'], 'partial')

    def test_author_and_annotation_have_distinct_addresses_and_authority(self):
        original = next(e for e in self.search('互连延迟')['evidence'] if e['content_kind'] == 'author_original')
        annotation = next(e for e in self.search('我的批注')['evidence'] if e['content_kind'] == 'user_annotation')
        self.assertNotEqual(original['chunk_id'], annotation['chunk_id'])
        self.assertEqual(original['work_key'], annotation['work_key'])
        self.assertNotIn('我的批注', original['excerpt'])
        self.assertNotIn('互连延迟', annotation['excerpt'])
        self.assertEqual(annotation['authority'], 'attributed_source_not_confirmed_user_fact')

    def test_conservative_canonical_identity(self):
        self.assertEqual(canonical_url('https://example.org/a?id=2&utm_source=folo#top'), 'https://example.org/a?id=2')
        self.assertNotEqual(canonical_url('https://example.org/a?id=2'), canonical_url('https://example.org/a?id=3'))
        self.assertIsNone(canonical_url('https://user:pass@example.org/a'))

    def test_deleted_or_changed_text_rejected_before_reconcile(self):
        bundle = build_bundle_v2(self.home, '缓存一致性', mode='lexical')
        (self.home / 'source/coherence.md').unlink()
        with self.assertRaises(ValueError):
            bundle.cloud_input(self.home)
        evidence = self.search('缓存一致性')['evidence']
        self.assertFalse(any(e['path_hint'] == 'coherence.md' for e in evidence))
        with sqlite3.connect(self.home / 'retrieval-v2.sqlite3') as db:
            self.assertFalse(db.execute('SELECT 1 FROM chunks WHERE document_id=?', (bundle.evidence[0]['document_id'],)).fetchone())

    def test_model_revocation_after_bundle_stops_export(self):
        bundle = build_bundle_v2(self.home, '流水线', mode='lexical')
        self.config(lambda d: d['sources'][0].update(model_providers=[]))
        with self.assertRaisesRegex(ValueError, 'permission_revoked'):
            bundle.cloud_input(self.home)
        self.assertEqual(self.search('流水线')['evidence'], [])
        self.assertTrue(self.search('流水线', provider=None)['evidence'])

    def test_index_revocation_purges_sidecar(self):
        self.search('流水线')
        self.config(lambda d: d['sources'][0].update(index=False))
        self.assertEqual(self.search('流水线')['evidence'], [])
        with sqlite3.connect(self.home / 'retrieval-v2.sqlite3') as db:
            self.assertFalse(any('流水线' in r[0] for r in db.execute('SELECT text FROM chunks')))

    def test_expired_reading_manifest_invalidates_existing_bundle(self):
        from personal_asis.reading import ReadingCache
        bundle = build_bundle_v2(self.home, '互连延迟', mode='lexical')
        for name in ['folo', 'wucai']:
            with ReadingCache(self.home, name) as cache, cache.db:
                cache.db.execute('UPDATE items SET selected=0,expires_at=0')
        with self.assertRaises(ValueError):
            bundle.cloud_input(self.home)
        self.assertFalse(any(e['source_type'] == 'reading_cache' for e in self.search('互连延迟')['evidence']))

    def test_rebuild_after_edit_changes_chunk_version_address(self):
        old = self.search('流水线')['evidence'][0]
        path = self.home / 'source/pipeline.md'
        path.write_text(path.read_text() + '\n新段落。\n')
        self.reconcile()
        new = self.search('流水线')['evidence'][0]
        self.assertEqual(new['document_id'], old['document_id'])
        self.assertNotEqual(new['chunk_id'], old['chunk_id'])
        with self.assertRaisesRegex(ValueError, 'stale_or_denied'):
            self.expand(old)

    def test_expansion_identity_scope_and_budget(self):
        hit = self.search('协议甲')['evidence'][0]
        self.assertEqual(len(self.expand(hit, neighbors=0)), 1)
        self.assertEqual(len(self.expand(hit, neighbors=1, max_bytes=10000)), 2)
        with self.assertRaisesRegex(ValueError, 'stale_or_denied'):
            self.expand(hit, source_ids=['reading_folo'])
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.expand(hit, max_bytes=256)
        with self.assertRaises(ValueError):
            self.expand(hit, neighbors=3)

    def test_bundle_selects_more_than_three_distinct_passages_within_budget(self):
        bundle = build_bundle_v2(self.home, '缓存 NUMA TLB 流水线 动态功耗', max_bytes=6144, mode='lexical')
        self.assertGreater(len(bundle.evidence), 3)
        self.assertLessEqual(len(encoded(bundle.cloud_input(self.home)).encode()), 6144)
        self.assertFalse(bundle.coverage['semantic_coverage_verified'])
        self.assertFalse(bundle.coverage['follow_up_performed'])

    def test_bundle_includes_two_related_paragraphs_from_one_document(self):
        bundle = build_bundle_v2(self.home, '协议甲与协议乙对比', mode='lexical')
        self.assertEqual(len([e for e in bundle.evidence if e['path_hint'] == 'protocols.md']), 2)
        self.assertEqual(len({e['work_key'] for e in bundle.evidence if e['path_hint'] == 'protocols.md'}), 1)

    def test_cloud_payload_has_attribution_but_no_local_paths(self):
        bundle = build_bundle_v2(self.home, '互连延迟 我的批注', mode='lexical')
        cloud = encoded(bundle.cloud_input(self.home))
        self.assertNotIn(str(self.home), cloud)
        self.assertNotIn('file:', cloud)
        self.assertIn('author_original', cloud)
        self.assertIn('user_annotation', cloud)
        self.assertIn('partial', cloud)

    def test_bundle_tampering_and_root_rebinding_fail_closed(self):
        for field, value in [('char_start', 0), ('excerpt', '伪造'), ('content_kind', 'user_confirmed'),
                             ('published_at', '2026-01-01'), ('root_identity', 'wrong')]:
            bundle = build_bundle_v2(self.home, '流水线', mode='lexical')
            bundle.evidence[0][field] = value
            with self.assertRaises(ValueError):
                bundle.cloud_input(self.home)

    def test_remote_export_is_independently_checked(self):
        bundle = build_bundle_v2(self.home, '流水线', mode='lexical')
        with self.assertRaisesRegex(ValueError, 'permission_revoked'):
            bundle.cloud_input(self.home, 'pwa')

    def test_time_range_excludes_unknown_and_old_dates(self):
        window = {'start': '2026-10-01', 'end': '2026-10-01', 'basis': 'test', 'unknown_dates': 'excluded'}
        result = self.search('研究偏好', time_window=window)
        self.assertEqual(len(result['evidence']), 1)
        self.assertEqual(result['evidence'][0]['path_hint'], '2026-10-01.md')
        with self.assertRaises(ValueError):
            self.search('研究偏好', time_window={'start': 'bad'})

    def test_sidecar_is_private_disposable_and_legacy_results_unchanged(self):
        before = build_bundle(self.home, 'cache').fingerprint()
        self.search('cache')
        path = self.home / 'retrieval-v2.sqlite3'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(build_bundle(self.home, 'cache').fingerprint(), before)
        with sqlite3.connect(self.home / 'index.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        path.unlink()
        self.assertTrue(self.search('cache')['evidence'])
        self.assertFalse((self.home / 'work.sqlite3').exists())

    def test_no_v2_fields_added_to_paid_agent_protocol_or_pa1_settings(self):
        from personal_asis.agent_model import TOOLS
        from personal_asis.pa1 import DEFAULTS
        self.assertEqual([t['name'] for t in TOOLS], ['search_notes'])
        self.assertFalse(any('retrieval_v2' in k for k in DEFAULTS))

    def test_bad_query_channel_and_index_versions(self):
        for kwargs in [{'query': ''}, {'query': 'x', 'limit': 0}, {'query': 'x', 'mode': 'unknown'},
                       {'query': 'x', 'channel': 'public'}]:
            with self.assertRaises(ValueError):
                self.search(**kwargs)
        self.search('cache')
        with sqlite3.connect(self.home / 'retrieval-v2.sqlite3') as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(ValueError, 'unsupported_index_version'):
            self.search('cache')

    def test_diagnostics_have_only_counts_and_no_query_or_text(self):
        diagnostics = self.search('紫色猎鹰')['diagnostics']
        self.assertFalse(any(isinstance(v, str) for v in diagnostics.values()))
        self.assertNotIn('紫色猎鹰', encoded(diagnostics))

    def test_existing_clean_entry_clears_deleted_v2_chunks(self):
        from personal_asis.pa1_maintenance import clean
        self.search('流水线')
        (self.home / 'source/pipeline.md').unlink()
        report = clean(self.home)
        self.assertGreaterEqual(report['retrieval_v2_cleanup']['removed'], 1)
        with sqlite3.connect(self.home / 'retrieval-v2.sqlite3') as db:
            self.assertFalse(any('流水线' in r[0] for r in db.execute('SELECT text FROM chunks')))

    def test_fenced_code_is_preserved_and_not_mistaken_for_section(self):
        text = '# 标题\n\n```python\n# comment with evidence\nprint(42)\n```\n'
        found = list(passages(text))
        self.assertIn('# comment with evidence', found[0][1])
        self.assertEqual(found[0][3], ['标题'])

    def test_root_change_and_private_reclassification_deny_old_evidence(self):
        bundle = build_bundle_v2(self.home, '流水线', mode='lexical')
        path = self.home / 'source/pipeline.md'
        path.write_text('---\nsensitivity: private\n---\n' + path.read_text())
        self.reconcile()
        self.assertFalse(self.search('流水线')['evidence'])
        with self.assertRaises(ValueError):
            bundle.cloud_input(self.home)
        new_root = self.home / 'replacement'
        new_root.mkdir()
        self.config(lambda d: d['sources'][0].update(root=str(new_root)))
        with self.assertRaises(ValueError):
            bundle.cloud_input(self.home)

    def test_query_credentials_and_sidecar_symlinks_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'credentials'):
            self.search('Authorization: Bearer SYNTHETIC_SECRET_VALUE')
        target = self.home / 'other.sqlite3'
        target.touch()
        (self.home / 'retrieval-v2.sqlite3').unlink(missing_ok=True)
        (self.home / 'retrieval-v2.sqlite3').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.search('流水线')

    def test_offline_eval_has_at_least_thirty_cases_and_no_paid_calls(self):
        self.assertGreaterEqual(len(cases()), 30)
        report = evaluate(self.home, 'v2')
        self.assertEqual(report['questions'], 39)
        self.assertEqual(report['model_generation_calls'], 0)
        self.assertGreater(report['evidence_recall_at_k'], .9)

    def test_cli_diagnostics_do_not_emit_body(self):
        from personal_asis.cli import main
        import io
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main(['--home', str(self.home), 'retrieval-v2', 'search', '--query', '流水线', '--diagnostics-only'])
        self.assertEqual(code, 0)
        self.assertNotIn('流水线', output.getvalue())
        self.assertNotIn(str(self.home), output.getvalue())


if __name__ == '__main__':
    unittest.main()
