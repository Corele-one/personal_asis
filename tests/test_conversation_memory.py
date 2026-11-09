import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from personal_asis.conversation_memory import ConversationMemory, PAGE
from personal_asis.llm_router import State, fingerprint


class ConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbpath = Path(self.tmp.name)/'chat.sqlite3'
        self.routerpath = Path(self.tmp.name)/'router.sqlite3'
        self.db = sqlite3.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE conversations(conversation_id TEXT PRIMARY KEY,user_id TEXT,title TEXT,updated_at TEXT,content JSON)')
        self.origin = 'test:FriendMessage:owner'
        self.messages = [dict(role='user',content=[dict(type='text',text='写套磁信'),
            dict(type='text',text='<system_reminder>synthetic</system_reminder>')]),
            dict(role='assistant',content='套磁信草稿。'*1500),
            dict(role='assistant',tool_calls=[dict(function=dict(name='secret_tool',arguments='private_tool_argument'))]),
            dict(role='tool',content='private_tool_result')]
        self.put('ours', self.origin, self.messages)
        self.put('foreign', 'test:FriendMessage:someone_else', [dict(role='user',content='秘密套磁信')])
        self.state = State(self.routerpath, startup_cooldown=0)
        self.addCleanup(self.state.db.close)
        self.memory = ConversationMemory(self.dbpath,self.routerpath)

    def put(self, cid, origin, messages):
        self.db.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?,?,?)',
            (cid,origin,'synthetic','2026-11-09',json.dumps(messages)))
        self.db.commit()

    def test_recent_and_search_are_scoped_to_exact_owner_origin(self):
        self.assertEqual([r['conversation_id'] for r in self.memory.query(self.origin)['conversations']], ['ours'])
        found = self.memory.query(self.origin,'search','套磁信')
        self.assertEqual({r['conversation_id'] for r in found['matches']}, {'ours'})
        self.assertEqual({r['role'] for r in found['matches']}, {'user','assistant'})
        self.assertEqual(self.memory.query(self.origin,'search','private_tool_argument')['matches'], [])
        self.assertEqual(self.memory.query(self.origin,'read',conversation_id='foreign')['error'], 'conversation_not_found')
        self.assertEqual(self.memory.query('test:GroupMessage:owner')['error'], 'owner_private_origin_required')

    def test_native_array_text_is_searchable_even_with_unicode_escapes(self):
        found = self.memory.query(self.origin,'search','写套磁信')
        self.assertEqual(found['matches'][0]['message_index'],0)
        self.assertIn('写套磁信',found['matches'][0]['excerpt'])

    def test_read_pagination_preserves_original_and_labels_assistant_as_unconfirmed(self):
        before = self.dbpath.read_bytes()
        offset = 0; pieces = []
        while True:
            result = self.memory.query(self.origin,'read',conversation_id='ours',message_index=1,offset=offset)
            self.assertLessEqual(len(result['text']), PAGE)
            self.assertEqual(result['role'],'assistant')
            pieces.append(result['text'])
            offset = result['next_offset']
            if offset is None:break
        self.assertEqual(''.join(pieces), self.messages[1]['content'])
        self.assertEqual(before,self.dbpath.read_bytes())
        self.assertEqual(self.memory.query(self.origin,'read',conversation_id='ours',message_index=3)['error'], 'only_dialogue_text_available')

    def test_invalid_query_is_bounded_and_cannot_read_an_arbitrary_path(self):
        self.assertEqual(self.memory.query(self.origin,'read',conversation_id='../other')['error'], 'invalid_conversation_id')
        self.assertEqual(self.memory.query(self.origin,'search','')['error'], 'query_required')
        self.assertEqual(self.memory.query(self.origin,'search','x'*81)['error'], 'query_too_long')
        self.assertEqual(self.memory.query(self.origin,'read',offset=-1)['error'], 'invalid_memory_page')
        self.assertEqual(self.memory.query(self.origin,'search',"' OR 1=1 --")['matches'], [])

    def test_summary_requires_matching_source_and_disappears_after_delete(self):
        scope = fingerprint([self.origin,'ours'])
        prefix = fingerprint(self.messages[:2])
        self.state.save_summary(scope,prefix,2,'已验证覆盖范围的合成摘要')
        self.state.db.execute('INSERT INTO summary_ranges VALUES(?,?,?)',(scope,prefix,0))
        result = self.memory.query(self.origin,'summary',conversation_id='ours')
        self.assertTrue(result['summary_available'])
        self.assertEqual(result['covered_messages'],[1,2])
        changed = [dict(role='user',content='修改过的原话')]+self.messages[1:]
        self.put('ours',self.origin,changed)
        self.assertFalse(self.memory.query(self.origin,'summary',conversation_id='ours')['summary_available'])
        self.db.execute("DELETE FROM conversations WHERE conversation_id='ours'");self.db.commit()
        self.assertEqual(self.memory.query(self.origin,'summary',conversation_id='ours')['error'], 'conversation_not_found')

    def test_missing_or_expired_summary_never_claims_to_have_summarized(self):
        self.assertFalse(self.memory.query(self.origin,'summary',conversation_id='ours')['summary_available'])
        prefix = fingerprint(self.messages[:1]);scope = fingerprint([self.origin,'ours'])
        self.state.save_summary(scope,prefix,1,'旧摘要')
        self.state.db.execute('INSERT INTO summary_ranges VALUES(?,?,?)',(scope,prefix,0))
        self.state.db.execute('UPDATE summaries SET created=0')
        self.assertFalse(self.memory.query(self.origin,'summary',conversation_id='ours')['summary_available'])
