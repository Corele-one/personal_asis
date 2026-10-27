import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import life_freewrite as prose, life_sync as sync, life_journal as journal
from personal_asis.life_layout import Editor, LayoutUnavailable, slots, validate
from personal_asis.model_provider import MiMo, ProviderUnknown


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root/'home'; self.home.mkdir()
        self.profile = self.root/'profile'; self.profile.mkdir()
        self.vault = self.root/'vault'; self.vault.mkdir()
        (self.home/'sources.yaml').write_text(json.dumps(dict(node_id='synthetic',sources=[
            dict(id='life',root=str(self.vault),policy='private',index=True)])))
        (self.profile/'settings.json').write_text(json.dumps(dict(defaultProvider='xiaomi', defaultModel='mimo-v2.6-flash')))
        (self.profile/'life-sync.json').write_text(json.dumps(dict(enabled=True,host='owner@example.test',daily_directory='.')))
        self.editor = Editor(self.home,self.profile)
        self.template = ('---\ncssclasses: daily\n---\n### 📕Freewrite\n\n'
                         '> [!note]- Highlight\n> 留下手记\n\n'
                         '#### 课程与方向\n\n课程越来越难，我在想以后的方向。\n\n还想看看新的项目。\n\n'
                         '#### 晚饭\n\n和朋友一起吃了晚饭。\n\n'
                         '---\n--- start-multi-column: habits\n### ⚛️Habits\n- [ ] reading\n')

    def state(self, *texts):
        records = {}
        for i, text in enumerate(texts):
            rid = format(i+1,'064x')
            records[rid] = dict(id=rid,text=text,day='2026-10-27',occurred_at=f'2026-10-27T12:{i:02}:00+08:00',
                revision=1,capture_source='life_command',kind='journal',deleted=False,summary='',due_at=None,task_status=None)
        return dict(records=records,applied={},cursor=0)

    def response(self, groups):
        return dict(content=json.dumps(dict(groups=groups),ensure_ascii=False),finish_reason='stop',tool_calls=None)

    def test_context_places_related_prose_under_existing_h4_and_new_topic_at_end(self):
        desired=[('a','对数字IC的方向有些迷茫。\n'),('b','饭后散步看到一只小猫。\n')]
        def choose(document):
            self.assertIn('课程越来越难',document['context'])
            course=next(a for a in document['slots'] if '课程越来越难' in a['preceding'])
            return dict(groups=[dict(slot=course['id'],title='',records=['r0']),
                                dict(slot=len(document['slots'])-1,title='散步的小插曲',records=['r1'])])
        with patch.object(self.editor,'decision',side_effect=choose):
            after, locs = self.editor.arrange(self.template,desired)
        self.assertLess(after.index('对数字IC'),after.index('#### 晚饭'))
        self.assertIn('对数字IC的方向有些迷茫。\n\n还想看看新的项目。',after)
        self.assertIn('#### 散步的小插曲\n\n饭后散步看到一只小猫。\n\n---',after)
        self.assertNotIn('聊天随记',after)
        self.assertTrue(after.endswith(self.template[self.template.index('---\n--- start-multi'):]))
        for start,body in locs.values():self.assertEqual(after[start:start+len(body)],body)

    def test_model_cannot_rewrite_prose_or_omit_or_repeat_records_or_inject_markdown(self):
        anchors=slots(self.template)
        inside=next(i for i,a in enumerate(anchors) if not a['new_heading'])
        good=dict(groups=[dict(slot=len(anchors)-1,title='随想',records=['r0','r1'])])
        self.assertEqual(validate(good,anchors,['r0','r1']),good['groups'])
        for group in (dict(slot=True,title='',records=['r0','r1']),
                      dict(slot=999,title='',records=['r0','r1']),
                      dict(slot=inside,title='主题',records=['r0','r1']),
                      dict(slot=2,title='聊天随记',records=['r0','r1']),
                      dict(slot=2,title='主题\n---',records=['r0','r1']),
                      dict(slot=2,title='[链接](x)',records=['r0','r1']),
                      dict(slot=2,title='',records=['r0']),
                      dict(slot=2,title='',records=['r0','r0','r1']),
                      dict(slot=2,title='',records=['r1','r0']),
                      dict(slot=2,title='',records=['r0','r1'],text='模型改写')):
            with self.subTest(group=group),self.assertRaises(ValueError):validate(dict(groups=[group]),anchors,['r0','r1'])

    def test_no_anchor_inside_fenced_examples_and_no_title_before_remaining_manual_text(self):
        text='### 📕Freewrite\n\n#### 反思\n\n第一段\n\n```md\n\n假段落\n\n```\n\n第二段\n\n---\n卡片'
        anchors=slots(text)
        self.assertEqual(len(anchors),3)
        self.assertFalse(anchors[0]['new_heading']);self.assertFalse(anchors[1]['new_heading'])
        self.assertTrue(anchors[-1]['new_heading'])
        with self.assertRaises(LayoutUnavailable):slots('### 📕Freewrite\n```python\n# unfinished')

    def test_group_receipts_support_revision_delete_and_partial_recovery(self):
        state=self.state('对方向有些迷茫。','也想试试别的项目。','今天散步遇到小猫。')
        note=self.vault/'2026-10-27.md';note.write_text(self.template)
        def choose(document):
            records=[r['id'] for r in document['records']]
            return dict(groups=[dict(slot=len(document['slots'])-1,title='最近的想法',records=records)])
        with patch.object(self.editor,'decision',side_effect=choose):
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
            sync.apply(files);state['applied'].update(changes)
            self.assertEqual(sync.plan(state,self.vault,'.',editor=self.editor),([],[]))
            rid=next(iter(state['records']));state['records'][rid].update(deleted=True,revision=2)
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
            self.assertNotIn('对方向有些迷茫',files[0]['after'])
            self.assertEqual(files[0]['after'].count('#### 最近的想法'),1)
            state['pending_projection']=journal.pending(state,files,changes,{},self.vault)
            sync.apply(files);journal.recover(state,self.vault)
            self.assertEqual(sync.plan(state,self.vault,'.',editor=self.editor),([],[]))
            for r in state['records'].values():r.update(deleted=True,revision=r['revision']+1)
            files,_=sync.plan(state,self.vault,'.',editor=self.editor)
            self.assertNotIn('#### 最近的想法',files[0]['after'])
            self.assertIn('课程越来越难',files[0]['after'])

    def test_success_cached_and_timeout_not_automatically_retried(self):
        desired=[('a','合成自述\n')]
        good=self.response([dict(slot=0,title='',records=['r0'])])
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',return_value=good) as call:
            self.editor.arrange('### 📕Freewrite\n',desired)
            self.editor.arrange('### 📕Freewrite\n',desired)
            self.assertEqual(call.call_count,1)
            payload=call.call_args.args[0]
            self.assertNotIn(str(self.vault),json.dumps(payload))
            self.assertNotIn('tools',payload)
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',side_effect=ProviderUnknown('synthetic')) as call:
            for _ in range(2):
                with self.assertRaises(LayoutUnavailable):self.editor.arrange('### 📕Freewrite\n',[('a','不同的合成自述\n')])
            self.assertEqual(call.call_count,1)
            retry=Editor(self.home,self.profile,retry=True)
            with self.assertRaises(LayoutUnavailable):retry.arrange('### 📕Freewrite\n',[('a','不同的合成自述\n')])
            self.assertEqual(call.call_count,2)
        cache=self.profile/'journal-layout-cache.json'
        self.assertEqual(cache.stat().st_mode&0o777,0o600)
        self.assertNotIn('不同的合成自述',cache.read_text())

    def test_invalid_output_not_retried_and_other_provider_never_called(self):
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',return_value=self.response([])) as call:
            for _ in range(2):
                with self.assertRaises(LayoutUnavailable):self.editor.arrange('',[('a','合成原话\n')])
            self.assertEqual(call.call_count,1)
        (self.profile/'settings.json').write_text('{"defaultProvider":"other"}')
        with patch.object(MiMo,'credential') as credential:
            with self.assertRaises(LayoutUnavailable):self.editor.arrange('',[('a','合成原话\n')])
            credential.assert_not_called()

    def test_skip_never_writes_and_confirm_reuses_frozen_plan_without_model_call(self):
        state=self.state('最近想试试别的方向。')
        def fetch(config,current):current['records']=state['records']
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),\
             patch.object(MiMo,'credential',return_value='synthetic'),\
             patch.object(MiMo,'complete',return_value=self.response([dict(slot=0,title='方向的尝试',records=['r0'])])) as call,\
             contextlib.redirect_stdout(io.StringIO()):
            with patch('builtins.input',return_value=''):
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'skipped')
            self.assertFalse((self.vault/'2026-10-27.md').exists())
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'applied')
            self.assertEqual(call.call_count,1)
            with patch('builtins.input') as ask:
                self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'up_to_date')
                ask.assert_not_called()
            self.assertEqual(call.call_count,1)
        self.assertIn('#### 方向的尝试',(self.vault/'2026-10-27.md').read_text())

    def test_unavailable_does_not_fallback_to_mechanical_append_and_shared_still_runs(self):
        state=self.state('合成自述')
        (self.profile/'life-sync.json').write_text(json.dumps(dict(enabled=True,host='owner@example.test',shared_sync_mode='text')))
        def fetch(config,current):current['records']=state['records']
        with patch.object(sync,'pull',side_effect=fetch),patch.object(Editor,'decision',side_effect=LayoutUnavailable()),\
             patch('personal_asis.shared_sync.run',return_value='complete') as shared,\
             patch('builtins.input') as ask,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.startup(self.home,self.profile,interactive=True),'layout_unavailable')
            ask.assert_not_called();shared.assert_called_once()
        self.assertEqual(list(self.vault.iterdir()),[])

    def test_excluded_source_checked_before_read_or_model_and_noninteractive_does_not_call(self):
        state=self.state('合成自述')
        with patch.object(Editor,'decision') as call:
            with self.assertRaisesRegex(ValueError,'daily_target_excluded'):
                sync.plan(state,self.vault,'.',editor=self.editor,allowed=lambda relative:False)
            call.assert_not_called()
            self.assertEqual(sync.startup(self.home,self.profile,interactive=False),'interactive_sync_required')
            call.assert_not_called()

    def test_input_limit_stops_before_model(self):
        with patch.object(Editor,'decision') as call:
            with self.assertRaises(LayoutUnavailable):self.editor.arrange('',[('a','合成文本'*15000+'\n')])
            call.assert_not_called()

    def test_generated_heading_retained_if_user_added_manual_paragraph_beneath_it(self):
        state=self.state('一段聊天原话。')
        choose=dict(groups=[dict(slot=0,title='生活小记',records=['r0'])])
        with patch.object(self.editor,'decision',return_value=choose):
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
        sync.apply(files);state['applied'].update(changes)
        note=self.vault/'2026-10-27.md'
        note.write_text(note.read_text()+'\n我后来手写的补充。\n')
        next(iter(state['records'].values())).update(deleted=True,revision=2)
        files,_=sync.plan(state,self.vault,'.',editor=self.editor)
        self.assertIn('#### 生活小记\n\n',files[0]['after'])
        self.assertIn('我后来手写的补充。',files[0]['after'])
        self.assertNotIn('一段聊天原话。',files[0]['after'])

    def test_duplicate_messages_share_group_and_cross_day_interruption_recovers(self):
        state=self.state('相同原话。','相同原话。')
        def choose(document):
            self.assertEqual(len(document['records']),1)
            return dict(groups=[dict(slot=len(document['slots'])-1,title='生活小记',records=['r0'])])
        with patch.object(self.editor,'decision',side_effect=choose):
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
            sync.apply(files);state['applied'].update(changes)
            note=self.vault/'2026-10-27.md'
            self.assertEqual(note.read_text().count('相同原话。'),1)
            for r in state['records'].values():r.update(day='2026-10-26',revision=2)
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
            state['pending_projection']=journal.pending(state,files,changes,{},self.vault)
            sync.apply(files[-1:]);journal.recover(state,self.vault)
            files,changes=sync.plan(state,self.vault,'.',editor=self.editor)
            sync.apply(files);state['applied'].update(changes)
            self.assertNotIn('相同原话。',note.read_text())
            self.assertEqual((self.vault/'2026-10-26.md').read_text().count('相同原话。'),1)
            self.assertEqual(sync.plan(state,self.vault,'.',editor=self.editor),([],[]))

    def test_request_count_bounded_and_existing_successes_reused(self):
        good=self.response([dict(slot=0,title='',records=['r0'])])
        with patch.object(MiMo,'credential',return_value='synthetic'),patch.object(MiMo,'complete',return_value=good) as call:
            for i in range(4):self.editor.arrange('',[('a',f'第{i}份原话\n')])
            with self.assertRaisesRegex(LayoutUnavailable,'layout_call_limit'):
                self.editor.arrange('',[('a','第五份原话\n')])
            self.editor.arrange('',[('a','第0份原话\n')])
            self.assertEqual(call.call_count,4)

    def test_new_h4_cannot_change_parent_of_manual_h5_and_lists_are_not_split(self):
        text='### 📕Freewrite\n\n#### 主题\n\n第一段\n\n##### 细节\n\n- 一个条目\n\n- 另一个条目\n\n结束的手记\n\n---\n'
        anchors=slots(text)
        first=next(a for a in anchors if a['preceding']=='第一段')
        self.assertFalse(first['new_heading'])
        self.assertFalse(any(a['preceding']=='- 一个条目' for a in anchors))
