import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import life_sync as sync, life_journal as journal, life_review as review
from personal_asis.life_layout import Editor, LayoutUnavailable
from personal_asis.life_projection import plan as activities
from personal_asis.model_provider import MiMo, ProviderUnknown


class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home, self.profile, self.vault = [self.root/name for name in ('home','profile','vault')]
        for path in (self.home,self.profile,self.vault): path.mkdir()
        (self.home/'sources.yaml').write_text(json.dumps(dict(node_id='synthetic',sources=[
            dict(id='life',root=str(self.vault),policy='private',index=True)])))
        (self.profile/'settings.json').write_text(json.dumps(dict(defaultProvider='xiaomi',defaultModel='mimo-v2.6-flash')))
        (self.profile/'life-sync.json').write_text(json.dumps(dict(enabled=True,host='owner@example.test',daily_directory='.')))
        self.note = self.vault/'2026-10-29.md'
        self.template = ('### 📕Freewrite\n\n手写的生活感受。\n\n---\n'
                         '--- start-multi-column: daily_habits_learning\n'
                         '### ⚛️Habits\n\n- [x] reading\n\n--- end-column ---\n'
                         '### 📖Learning\n\n#### 手写主题\n\n手写的学习笔记。\n\n'
                         '--- end-multi-column ---\n![[On This Day.base]]\n')
        self.note.write_text(self.template)
        rid = 'a'*64
        self.state = dict(cursor=1,applied={},records={rid:dict(id=rid,revision=1,day='2026-10-29',
            occurred_at='2026-10-29T20:45:00+08:00',kind='journal',capture_source='life_command',deleted=False,
            text='有点难受，昨天忘记给奶奶打电话。\n\n学习数字集成电路 Datapath以及Memory的内容 21:00-23:00\n\n也许需要一个个人主页。',summary='')})
        self.editor = Editor(self.home,self.profile)

    def batch(self):
        files,changes = sync.plan(self.state,self.vault,'.')
        files,activity = activities(self.state,self.vault,'.',files)
        journal.seal(files,changes,self.vault)
        return files,changes,activity

    def answer(self, document, *, title='数字集成电路'):
        groups = []
        for p in document['paragraphs']:
            name = 'learning' if 'Datapath' in p['text'] else 'freewrite'
            day = next(d for d in document['days'] if d['day'] == p['day'])
            groups.append(dict(day=p['day'],section=name,slot=len(day['slots'][name])-1,
                               title=title if name == 'learning' else '',paragraphs=[p['id']]))
        return dict(groups=groups)

    def revised(self, batch=None):
        batch = batch or self.batch()
        with patch.object(self.editor,'request',side_effect=lambda doc,system,check:self.checked(doc,check)):
            return review.revise(self.editor,*batch,self.state,self.vault,'数字集成电路放到 Learning')

    def checked(self, document, check):
        value = self.answer(document)
        check(value)
        return value

    def test_mixed_message_moves_only_learning_paragraph_preserves_manual_and_is_idempotent(self):
        raw = copy.deepcopy(self.state['records'])
        files,changes,activity = self.revised()
        after = files[0]['after']
        self.assertLess(after.index('忘记给奶奶'),after.index('\n---\n'))
        self.assertLess(after.index('个人主页'),after.index('\n---\n'))
        self.assertGreater(after.index('Datapath'),after.index('### 📖Learning'))
        for value in ('手写的生活感受。','手写的学习笔记。','- [x] reading','![[On This Day.base]]'):
            self.assertIn(value,after)
        for value in ('忘记给奶奶','Datapath','个人主页'):
            self.assertEqual(after.count(value),1)
        self.assertEqual(self.state['records'],raw)
        self.assertEqual(self.note.read_text(),self.template)
        sync.apply(files)
        self.state['applied'].update(changes)
        self.state['activity_applied'] = activity
        self.assertEqual(sync.plan(self.state,self.vault,'.',editor=self.editor),([],[]))
        self.assertEqual(activities(self.state,self.vault,'.')[0],[])
        next(iter(self.state['records'].values())).update(deleted=True,revision=2)
        removed,_ = sync.plan(self.state,self.vault,'.',editor=self.editor)
        self.assertNotIn('Datapath',removed[0]['after'])
        self.assertNotIn('#### 数字集成电路',removed[0]['after'])
        self.assertNotIn('忘记给奶奶',removed[0]['after'])
        self.assertIn('手写的学习笔记。',removed[0]['after'])

    def test_review_normalizes_new_heading_to_safe_topic_end(self):
        self.template=self.template.replace('手写的生活感受。',
            '#### 旧主题\n\n手写的生活感受。\n\n第二段手写补充。')
        self.note.write_text(self.template)
        batch=self.batch()
        def respond(document,system,check):
            value=self.answer(document)
            day=document['days'][0]
            unsafe=next(a for a in day['slots']['freewrite'] if not a['new_heading'])
            value['groups'][0].update(slot=unsafe['id'],title='新的感受')
            check(value)
            return value
        with patch.object(self.editor,'request',side_effect=respond):
            files,_,_=review.revise(self.editor,*batch,self.state,self.vault,'调整主题和排版')
        self.assertLess(files[0]['after'].index('第二段手写补充。'),files[0]['after'].index('#### 新的感受'))
        self.assertEqual(self.note.read_text(),self.template)

    def test_second_review_uses_original_paragraphs_and_updates_titles(self):
        first = self.revised()
        def response(doc,system,check):
            self.assertEqual(len(doc['paragraphs']),3)
            self.assertNotIn('#### 数字集成电路',[p['text'] for p in doc['paragraphs']])
            result = self.answer(doc,title='数集复习')
            check(result)
            return result
        with patch.object(self.editor,'request',side_effect=response):
            second = review.revise(self.editor,*first,self.state,self.vault,'标题改成数集复习')
        self.assertIn('#### 数集复习',second[0][0]['after'])
        self.assertNotIn('#### 数字集成电路',second[0][0]['after'])

    def test_invalid_missing_duplicate_cross_day_or_injected_heading_never_changes_draft(self):
        batch = self.batch()
        original = copy.deepcopy(batch)
        for kind in ('missing','duplicate','day','heading'):
            def response(doc,system,check):
                value = self.answer(doc)
                if kind == 'missing': value['groups'].pop()
                if kind == 'duplicate': value['groups'].append(value['groups'][0])
                if kind == 'day': value['groups'][0]['day'] = '2026-10-30'
                if kind == 'heading': value['groups'][0]['title'] = '# 逃逸'
                check(value)
                return value
            with patch.object(self.editor,'request',side_effect=response),self.assertRaises(LayoutUnavailable):
                review.revise(self.editor,*batch,self.state,self.vault,'调整排版')
            self.assertEqual(batch,original)
            self.assertEqual(self.note.read_text(),self.template)

    def test_skip_restores_review_without_model_and_confirm_writes_once(self):
        def fetch(config,state): state['records'] = copy.deepcopy(self.state['records'])
        def complete(payload,secret):
            doc = json.loads(payload['messages'][1]['content'])
            return dict(content=json.dumps(self.answer(doc)),finish_reason='stop',tool_calls=None)
        output = io.StringIO()
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),\
             patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',side_effect=complete) as call,\
             contextlib.redirect_stdout(output):
            with patch('builtins.input',side_effect=['数字集成电路放到 Learning','d','']):
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True,layout_mode='plain'),'skipped')
            self.assertEqual(self.note.read_text(),self.template)
            self.assertEqual((self.profile/'journal-review-draft.json').stat().st_mode & 0o777,0o600)
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'applied')
            with patch('builtins.input') as ask:
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'up_to_date')
                ask.assert_not_called()
            self.assertEqual(call.call_count,0)
        self.assertIn('已按建议调整',output.getvalue())
        self.assertIn('已恢复上次',output.getvalue())
        self.assertEqual(self.note.read_text().count('Datapath'),1)
        self.assertFalse((self.profile/'journal-review-draft.json').exists())

    def test_failure_keeps_previous_preview_and_request_not_automatically_retried(self):
        def fetch(config,state): state['records'] = copy.deepcopy(self.state['records'])
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),\
             patch.object(MiMo,'credential',return_value='synthetic'),\
             patch.object(MiMo,'complete',side_effect=ProviderUnknown('synthetic')) as call,\
             patch('builtins.input',side_effect=['调整排版','调整排版','']),contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(sync.startup(self.home,self.profile,interactive=True,layout_mode='plain'),'skipped')
            self.assertEqual(call.call_count,1)
        self.assertIn('保留当前草稿',shown.getvalue())
        self.assertEqual(self.note.read_text(),self.template)

    def test_frozen_review_invalidated_by_source_or_file_change_and_exclusion_checked(self):
        batch = self.revised()
        review.save(self.profile,self.state,self.vault,'.',*batch)
        self.assertIsNotNone(review.load(self.profile,self.state,self.vault,'.',lambda p:True))
        with self.assertRaisesRegex(ValueError,'daily_target_excluded'):
            review.load(self.profile,self.state,self.vault,'.',lambda p:False)
        changed = copy.deepcopy(self.state)
        next(iter(changed['records'].values()))['revision'] = 2
        self.assertIsNone(review.load(self.profile,changed,self.vault,'.',lambda p:True))
        self.assertFalse((self.profile/'journal-review-draft.json').exists())
        review.save(self.profile,self.state,self.vault,'.',*batch)
        self.note.write_text(self.template+'手写新内容。\n')
        self.assertIsNone(review.load(self.profile,self.state,self.vault,'.',lambda p:True))

    def test_interrupted_multi_file_write_preserves_all_paragraph_receipts(self):
        files,changes,activity = self.revised()
        self.state['pending_projection'] = journal.pending(self.state,files,changes,activity,self.vault)
        sync.apply(files)
        self.assertTrue(journal.recover(self.state,self.vault))
        self.assertGreaterEqual(len(next(iter(self.state['applied'].values()))['locations']),2)
        self.assertEqual(sync.plan(self.state,self.vault,'.',editor=self.editor),([],[]))

    def test_code_block_is_an_indivisible_source_paragraph(self):
        body = '第一段\n\n```python\nprint(1)\n\nprint(2)\n```\n\n最后一段\n'
        self.assertEqual(len(review.paragraphs(body)),3)
        self.assertIn('print(1)\n\nprint(2)',review.paragraphs(body)[1])

    def test_two_days_partial_write_then_revision_removes_every_old_piece(self):
        rid = 'b'*64
        self.state['records'][rid] = dict(next(iter(self.state['records'].values())),id=rid,
            day='2026-10-28',occurred_at='2026-10-28T21:00:00+08:00',text='另一天的学习感受。')
        files,changes,activity = self.revised()
        self.state['pending_projection'] = journal.pending(self.state,files,changes,activity,self.vault)
        sync.apply([next(f for f in files if f['path'] == self.note)])
        journal.recover(self.state,self.vault)
        record = self.state['records']['a'*64]
        record.update(revision=2,text='新修订的生活感受。')
        self.assertGreaterEqual(len(self.state['applied']['a'*64]['locations']),2)
        files,changes = sync.plan(self.state,self.vault,'.')
        changed = next(f for f in files if f['path'] == self.note)
        self.assertNotIn('Datapath',changed['after'])
        self.assertNotIn('忘记给奶奶',changed['after'])
        self.assertNotIn('个人主页',changed['after'])
        self.assertIn('新修订的生活感受',changed['after'])
        self.assertIn('手写的学习笔记',changed['after'])

    def test_existing_activity_offsets_survive_review_and_next_sync(self):
        r = next(iter(self.state['records'].values()))
        r['tracking'] = dict(habits=[],learning=[dict(phase='progress',topic='数集',
            content='学习数字集成电路',evidence='学习数字集成电路',blocker='',next_step='')])
        files,changes,activity = self.revised()
        for loc in activity['2026-10-29']['locations'].values():
            start,end = journal.locate(files[0]['after'],loc)
            self.assertEqual(files[0]['after'][start:end],loc['text'])
        sync.apply(files)
        self.state['applied'].update(changes)
        self.state['activity_applied'] = activity
        self.assertEqual(activities(self.state,self.vault,'.')[0],[])

    def test_review_uses_shared_call_budget_and_never_sends_paths_or_tools(self):
        batch = self.batch()
        def complete(payload,secret):
            self.assertNotIn(str(self.vault),json.dumps(payload))
            self.assertNotIn('tools',payload)
            doc = json.loads(payload['messages'][1]['content'])
            return dict(content=json.dumps(self.answer(doc)),finish_reason='stop',tool_calls=None)
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',side_effect=complete) as call:
            self.editor.calls = 3
            review.revise(self.editor,*batch,self.state,self.vault,'移动学习段落')
            with self.assertRaisesRegex(LayoutUnavailable,'layout_call_limit'):
                review.revise(self.editor,*batch,self.state,self.vault,'再换个标题')
            self.assertEqual(call.call_count,1)

    def test_source_revoked_during_preview_stops_before_review_model(self):
        def fetch(config,state): state['records'] = copy.deepcopy(self.state['records'])
        def answer(prompt):
            (self.home/'sources.yaml').write_text(json.dumps(dict(node_id='synthetic',sources=[
                dict(id='life',root=str(self.vault),policy='private',index=False)])))
            return '修改标题'
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),\
             patch.object(MiMo,'complete') as call,patch('builtins.input',side_effect=answer),\
             contextlib.redirect_stdout(io.StringIO()),\
             self.assertRaisesRegex(ValueError,'life_source_changed_reconfirmation_required'):
            sync.startup(self.home,self.profile,interactive=True,layout_mode='plain')
        call.assert_not_called()
        self.assertEqual(self.note.read_text(),self.template)

    def test_both_screenshot_requests_work_without_model_even_with_budget_exhausted(self):
        batch = self.batch()
        self.editor.calls = 4
        for feedback in ('10-29 数字集成电路放到 Learning',
                         '10-29 数字集成电路的学习内容放到 Learning模块中'):
            with patch.object(self.editor,'request',side_effect=AssertionError('must not call model')):
                files,changes,activity = review.revise(self.editor,*batch,self.state,self.vault,feedback)
            after = files[0]['after']
            self.assertGreater(after.index('Datapath'),after.index('### 📖Learning'))
            self.assertLess(after.index('个人主页'),after.index('\n---\n'))
            self.assertEqual(after.count('Datapath'),1)
            self.assertEqual(self.note.read_text(),self.template)

    def test_explicit_move_uses_date_and_preserves_unselected_generated_headings(self):
        rid = 'b'*64
        self.state['records'][rid] = dict(next(iter(self.state['records'].values())),id=rid,
            day='2026-10-28',occurred_at='2026-10-28T21:00:00+08:00',text='学习数字集成电路的另一天。')
        batch = self.batch()
        with patch.object(self.editor,'request',side_effect=AssertionError('must not call model')):
            with self.assertRaisesRegex(LayoutUnavailable,'review_target_ambiguous'):
                review.revise(self.editor,*batch,self.state,self.vault,'数字集成电路放到 Learning')
            files,_,_ = review.revise(self.editor,*batch,self.state,self.vault,'10-29 数字集成电路放到 Learning')
        other = next(f for f in files if f['path'].stem == '2026-10-28')
        self.assertEqual(other['after'],next(f for f in batch[0] if f['path'].stem == '2026-10-28')['after'])

    def test_unknown_explicit_topic_requests_clarification_without_model(self):
        with patch.object(self.editor,'request',side_effect=AssertionError('must not call model')):
            with self.assertRaisesRegex(LayoutUnavailable,'review_target_missing') as caught:
                review.revise(self.editor,*self.batch(),self.state,self.vault,'不存在的主题放到 Learning')
        self.assertIn('未找到',review.failure_message(caught.exception))

    def test_compound_or_question_is_not_partially_executed_as_a_local_move(self):
        days,parts = review.prepare(self.batch()[0],self.state)
        for feedback in ('数字集成电路放到 Learning，个人主页放到 Freewrite',
                         '不要把数字集成电路放到 Learning',
                         '是否把数字集成电路放到 Learning'):
            self.assertIsNone(review.explicit_move(feedback,days,parts))

    def test_model_section_case_and_short_date_are_normalized(self):
        def response(document,system,check):
            value = self.answer(document)
            for group in value['groups']:
                group['day'] = '10-29'
                group['section'] = group['section'].title()
            check(value)
            return value
        with patch.object(self.editor,'request',side_effect=response):
            files,_,_ = review.revise(self.editor,*self.batch(),self.state,self.vault,'请重新整理学习和生活主题')
        self.assertGreater(files[0]['after'].index('Datapath'),files[0]['after'].index('### 📖Learning'))

    def test_model_failures_preserve_sanitized_reason_in_cache_and_prompt(self):
        diagnostic = dict(http_status=429,category='quota_signal',retry_after_seconds=60)
        with patch.object(MiMo,'credential',return_value='synthetic'),\
             patch.object(MiMo,'complete',side_effect=ProviderUnknown('private provider detail',diagnostic)) as call:
            for _ in range(2):
                with self.assertRaises(LayoutUnavailable) as caught:
                    review.revise(self.editor,*self.batch(),self.state,self.vault,'请重新整理主题')
                message = review.failure_message(caught.exception)
                self.assertIn('额度限制',message)
                self.assertIn('429',message)
                self.assertNotIn('private provider detail',message)
            self.assertEqual(call.call_count,1)
        cached = (self.profile/'journal-layout-cache.json').read_text()
        self.assertIn('quota_signal',cached)
        self.assertNotIn('private provider detail',cached)
        self.assertNotIn('Datapath',cached)

    def test_invalid_model_plan_has_specific_diagnostic_and_keeps_source_private(self):
        bad = dict(content='{"groups":[]}',finish_reason='stop',tool_calls=None)
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',return_value=bad):
            with self.assertRaisesRegex(LayoutUnavailable,'layout_output_invalid') as caught:
                review.revise(self.editor,*self.batch(),self.state,self.vault,'重新安排所有主题')
        self.assertIn('未通过校验',review.failure_message(caught.exception))

    def test_fenced_model_json_is_accepted_without_another_request(self):
        def complete(payload,secret):
            value = self.answer(json.loads(payload['messages'][1]['content']))
            return dict(content='```json\n'+json.dumps(value)+'\n```',finish_reason='stop',tool_calls=None)
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',side_effect=complete) as call:
            files,_,_ = review.revise(self.editor,*self.batch(),self.state,self.vault,'重新安排所有主题')
            self.assertEqual(call.call_count,1)
        self.assertIn('Datapath',files[0]['after'])
