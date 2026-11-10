import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from personal_asis.chat_ui import ChatUI, display_emoji

class Manager:
    def __init__(self):
        self.current = {'owner':'a'}
        self.convs = {'a':NS(cid='a',user_id='owner',title='当前',updated_at=2),
                      'b':NS(cid='b',user_id='owner',title='旧话题',updated_at=1),
                      'x':NS(cid='x',user_id='other',title='私人',updated_at=3)}
        self.created = 0

    async def get_curr_conversation_id(self,origin):
        return self.current.get(origin)

    async def get_conversations(self,origin):
        return list(self.convs.values())  # deliberately loose: UI must recheck owner

    async def get_conversation(self,origin,cid):
        return self.convs.get(cid)  # same behavior as native lookup by id

    async def new_conversation(self,origin,*,title):
        self.created += 1
        cid = 'new'+str(self.created)
        self.convs[cid] = NS(cid=cid,user_id=origin,title=title,updated_at=10)
        self.current[origin] = cid
        return cid

    async def switch_conversation(self,origin,cid):
        self.current[origin] = cid

class ChatUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'ui.sqlite3'
        self.manager = Manager()
        self.now = 0
        self.ui = ChatUI(self.path,self.manager,clock=lambda:self.now)
        self.addCleanup(lambda:self.ui.close())

    async def test_card_has_current_model_and_no_foreign_titles(self):
        self.ui.attributed('owner','a','mimo-test')
        card = await self.ui.card('owner')
        text = json.dumps(card,ensure_ascii=False)
        self.assertIn('当前会话：当前',text)
        self.assertIn('mimo-test',text)
        self.assertIn('未启用',text)
        self.assertNotIn('私人',text)
        self.assertNotIn('history',text)

    async def test_new_preserves_old_and_duplicate_click_does_not_create_twice(self):
        code = self.ui.token('owner','a','new','新主题')
        await self.ui.act('owner',code)
        self.assertIn('已处理',await self.ui.act('owner',code))
        self.assertEqual(self.manager.created,1)
        self.assertIn('a',self.manager.convs)

    async def test_stale_card_cannot_switch_after_native_current_changes(self):
        code = self.ui.token('owner','a','switch','b')
        self.manager.current['owner'] = 'b'
        self.assertIn('已变化',await self.ui.act('owner',code))
        self.assertEqual(self.manager.current['owner'],'b')

    async def test_expired_foreign_and_deleted_targets_rejected(self):
        code = self.ui.token('owner','a','switch','x')
        self.assertIn('不可用',await self.ui.act('owner',code))
        self.assertIn('过期',await self.ui.act('other',code))
        self.now=301
        self.assertIn('过期',await self.ui.act('owner',code))
        code = self.ui.token('owner','a','switch','b')
        del self.manager.convs['b']
        self.assertIn('不可用',await self.ui.act('owner',code))

    async def test_archive_current_preserves_history_and_restore_does_not_switch(self):
        code = self.ui.token('owner','a','archive','a')
        await self.ui.act('owner',code)
        self.assertIn('a',self.manager.convs)
        self.assertEqual(self.manager.current['owner'],'new1')
        self.assertNotIn('当前"',json.dumps(await self.ui.card('owner'),ensure_ascii=False))
        card = await self.ui.card('owner',archived=True)
        self.assertIn('当前',json.dumps(card,ensure_ascii=False))
        code = self.ui.token('owner','new1','restore','a')
        await self.ui.act('owner',code)
        self.assertEqual(self.manager.current['owner'],'new1')
        self.assertEqual(self.ui.db.execute('SELECT count(*) FROM archived').fetchone()[0],0)

    async def test_generation_busy_does_not_consume_action(self):
        code = self.ui.token('owner','a','switch','b')
        self.ui.active['owner'] = {'message'}
        self.assertIn('处理中',await self.ui.act('owner',code))
        self.ui.active.clear()
        self.assertIn('已切换',await self.ui.act('owner',code))

    async def test_two_concurrent_clicks_one_mutation(self):
        code = self.ui.token('owner','a','new')
        await asyncio.gather(self.ui.act('owner',code),self.ui.act('owner',code))
        self.assertEqual(self.manager.created,1)

    async def test_unknown_after_native_commit_is_not_replayed_across_restart(self):
        original = self.manager.new_conversation
        async def partial(*a,**kw):
            await original(*a,**kw)
            raise OSError('synthetic lost receipt')
        self.manager.new_conversation = partial
        code = self.ui.token('owner','a','new')
        with self.assertRaises(OSError):
            await self.ui.act('owner',code)
        self.ui.close()
        self.ui = ChatUI(self.path,self.manager,clock=lambda:self.now)
        self.assertIn('已处理',await self.ui.act('owner',code))
        self.assertEqual(self.manager.created,1)

    async def test_reaction_claims_and_deletion_are_once_across_restart(self):
        self.assertTrue(self.ui.reserve_reaction('message','processing'))
        self.assertFalse(self.ui.reserve_reaction('message','processing'))
        self.ui.reaction_saved('message','processing','synthetic-rid')
        self.assertEqual(self.ui.take_reaction('message','processing'),'synthetic-rid')
        self.assertEqual(self.ui.take_reaction('message','processing'),'')
        self.ui.close()
        self.ui = ChatUI(self.path,self.manager,clock=lambda:self.now)
        self.assertFalse(self.ui.reserve_reaction('message','processing'))

class EmojiTests(unittest.TestCase):
    def test_only_known_normal_prose_changes(self):
        self.assertEqual(display_emoji('你好[捂脸] [未知]\n'), '你好🤦 [未知]\n')

    def test_code_quotes_and_links_are_preserved(self):
        text = '> [捂脸]\n“[笑哭]”\n`[思考]` [加油]\n```python\nx="[捂脸]"\n```\n[点赞](https://example.test)\n'
        result=display_emoji(text)
        self.assertEqual(result,text.replace('` [加油]','` 💪'))

    def test_tilde_fences_and_emoji_idempotence(self):
        text='~~~\n[捂脸]\n~~~\n[庆祝]\n'
        self.assertEqual(display_emoji(display_emoji(text)),'~~~\n[捂脸]\n~~~\n🎉\n')
