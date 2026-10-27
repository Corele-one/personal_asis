import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import asyncio
import contextlib
import io
import sys
from unittest.mock import patch

from personal_asis import shared_sync, shared_transfer, shared_sources
from personal_asis.shared_store import SharedStore, identity, validate_body
from personal_asis.shared_cli import annotate
from personal_asis.life_store import LifeStore


class SharedSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.mac=SharedStore(self.root/'mac/shared.sqlite3','mac');self.addCleanup(self.mac.close)
        self.vps_home=self.root/'vps';self.vps_home.mkdir()
        self.life=LifeStore(self.vps_home/'life.sqlite3');self.addCleanup(self.life.close)
        self.calls=[]

    def body(self, text='合成资料的正文', **kwargs):
        return shared_sources.document_bodies('study','Note/synthetic.md','合成标题',text,**kwargs)[0]

    def put(self, key='one', text='合成资料的正文'):
        key=identity(key);self.mac.put('notes',key,self.body(text));return key

    def transport(self, config, request):
        self.calls.append(copy.deepcopy(request))
        return shared_transfer.handle(request,self.vps_home)

    def sync(self, **kwargs):
        return shared_sync.replicate(self.mac,{},transport=self.transport,**kwargs)

    def test_roundtrip_sources_life_and_separate_vps_annotation(self):
        key=self.put()
        record=self.life.capture('synthetic','owner','one','合成生活自述','2026-10-26T08:00:00+08:00')[0]
        result=self.sync();self.assertTrue(result['complete'])
        self.assertEqual(result['uploaded'],1);self.assertEqual(result['downloaded'],1)
        self.assertEqual(len(self.mac.search('生活自述')),1)
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            self.assertEqual(remote.read('mac','notes',key)['body']['text'],'合成资料的正文')
            value=annotate(remote,'mac/notes/'+key,'补充','合成的本人补充')
        result=self.sync();self.assertEqual(result['downloaded'],1)
        self.assertEqual(self.mac.read('vps','annotations',value['id'])['body']['text'],'合成的本人补充')
        self.assertEqual(self.sync()['uploaded'],0);self.assertEqual(self.sync()['downloaded'],0)
        self.assertEqual(self.mac.path.stat().st_mode&0o777,0o600)

    def test_lost_ssh_ack_is_replayed_without_duplicate_rows_or_versions(self):
        self.put()
        def lost_ack(config,request):
            self.transport(config,request)
            raise subprocess.TimeoutExpired('synthetic-ssh',30)
        with self.assertRaises(subprocess.TimeoutExpired):
            shared_sync.replicate(self.mac,{},transport=lost_ack)
        self.assertEqual(self.mac.get_meta('ack:vps',0),0)
        self.assertTrue(self.sync()['complete'])
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            self.assertEqual(remote.db.execute("SELECT count(*) FROM objects WHERE origin='mac'").fetchone()[0],1)
        self.assertEqual(self.sync()['uploaded'],0)

    def test_tombstone_withdraws_body_and_old_page_does_not_resurrect(self):
        key=self.put();old=self.mac.export(0);self.sync()
        self.mac.put('notes',key,None);self.sync()
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            with self.assertRaises(ValueError):remote.read('mac','notes',key)
            remote.receive(old,'mac')
            with self.assertRaises(ValueError):remote.read('mac','notes',key)
            self.assertEqual(remote.search('合成资料'),[])
            self.assertIsNone(remote.db.execute('SELECT body FROM objects WHERE id=?',(key,)).fetchone()[0])

    def test_source_withdrawal_hides_and_tombstones_derived_annotations_on_both_peers(self):
        key=self.put();self.sync()
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            note=annotate(remote,'mac/notes/'+key,'合成补充','从来源整理的合成补充')
        self.sync();self.assertEqual(len(self.mac.search('合成补充')),1)
        self.mac.put('notes',key,None)
        self.assertEqual(self.mac.search('合成补充'),[])
        self.sync()
        with self.assertRaises(ValueError):self.mac.read('vps','annotations',note['id'])
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            row=remote.db.execute('SELECT body FROM objects WHERE id=?',(note['id'],)).fetchone()
            self.assertIsNone(row['body'])

    def test_annotation_replay_uses_same_id_and_does_not_create_a_new_revision(self):
        key=self.put();annotation_id=identity('same-explicit-action')
        one=annotate(self.mac,'mac/notes/'+key,'补充','重复执行的合成补充',key=annotation_id)
        sequence=self.mac.get_meta('sequence')
        two=annotate(self.mac,'mac/notes/'+key,'补充','重复执行的合成补充',key=annotation_id)
        self.assertEqual(one,two);self.assertEqual(self.mac.get_meta('sequence'),sequence)

    def test_conflicting_revision_and_spoofed_origin_abort_page_atomically(self):
        key=self.put();self.sync()
        with SharedStore(self.vps_home/'shared.sqlite3','vps') as remote:
            batch=self.mac.export(0)
            batch['changes'][0]['body']['text']='相同版本被非法改动'
            with self.assertRaisesRegex(ValueError,'collision'):remote.receive(batch,'mac')
            self.assertEqual(remote.read('mac','notes',key)['body']['text'],'合成资料的正文')
            batch=self.mac.export(0);batch['changes'][0]['origin']='vps'
            with self.assertRaises(ValueError):remote.receive(batch,'mac')
            with self.assertRaisesRegex(ValueError,'authority'):
                remote.put('notes',identity('foreign'),self.body())

    def test_bounded_large_pages_resume_and_transfer_only_new_versions(self):
        for i in range(40):self.put(str(i),'合成大段资料'*1500+str(i))
        first=self.sync(max_pages=1)
        self.assertFalse(first['complete'])
        self.assertLess(first['uploaded'],40)
        self.assertTrue(self.sync()['complete'])
        self.assertEqual(self.sync()['uploaded'],0)
        self.put('7','只修改这一份')
        self.assertEqual(self.sync()['uploaded'],1)

    def test_credentials_machine_paths_and_query_tokens_never_enter_shared_rows(self):
        body=self.body()
        for changed in (dict(body,text='password=synthetic-secret-value'),
                        dict(body,locator='../outside.md'),dict(body,text='/Users/synthetic/private.md'),
                        dict(body,url='https://example.test/item?xsec_token=synthetic')):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):self.mac.put('notes',identity('bad'),changed)
        self.assertEqual(self.mac.get_meta('sequence',0),0)
        self.assertNotIn('/Users/',self.body('参考 /Users/synthetic/file.md')['text'])
        for value in ('C:/Users/synthetic/file.md',r'C:\Users\synthetic\file.md','file:///tmp/synthetic.md'):
            clean=self.body('参考 '+value+'\x0b')
            self.assertNotIn(value,clean['text']);self.assertNotIn('\x0b',clean['text'])
            validate_body(clean,'notes')
        self.assertEqual(shared_sources.public_url('https://example.test/p?xsec_token=secret&q=ok'),'https://example.test/p?q=ok')

    def test_invalid_protocol_and_replica_reset_are_rejected(self):
        for request in ({'path':'/tmp/no'},dict(version=1,after=-1,head=0,upload={})):
            with self.assertRaises(ValueError):shared_transfer.handle(request,self.vps_home)
        self.put();self.sync()
        with self.assertRaisesRegex(ValueError,'reset'):
            shared_transfer.handle(dict(version=1,after=0,head=0,upload=dict(changes=[],cursor=0,more=False)),self.vps_home)

    def test_annotation_cas_does_not_overwrite_a_newer_edit(self):
        key=self.put()
        value=annotate(self.mac,'mac/notes/'+key,'补充','第一版')
        current=self.mac.read('mac','annotations',value['id'])
        body=dict(current['body'],text='第二版',hash=hashlib.sha256('第二版'.encode()).hexdigest())
        self.mac.put('annotations',value['id'],body,expected=current['version'])
        with self.assertRaisesRegex(ValueError,'conflict'):
            self.mac.put('annotations',value['id'],None,expected=current['version'])

    def make_sources(self):
        home=self.root/'home';home.mkdir();vault=self.root/'vault';vault.mkdir()
        (home/'sources.yaml').write_text(json.dumps(dict(node_id='synthetic',sources=[
            dict(id='life',root=str(vault),index=True,policy='private')]),ensure_ascii=False))
        return home,vault

    def test_mac_index_refresh_change_delete_and_offline_source(self):
        home,vault=self.make_sources();note=vault/'one.md';note.write_text('# 合成笔记\n第一版内容')
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(len(self.mac.search('第一版')),1)
        sequence=self.mac.get_meta('sequence')
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(self.mac.get_meta('sequence'),sequence)
        note.write_text('# 合成笔记\n第二版内容')
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(len(self.mac.search('第二版')),1);self.assertEqual(self.mac.search('第一版'),[])
        vault.rename(self.root/'offline')
        refresh=shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(refresh['unavailable_notes'],['life'])
        self.assertEqual(len(self.mac.search('第二版')),1)
        (self.root/'offline').rename(vault);note.unlink()
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(self.mac.search('第二版'),[])

    def test_metadata_mode_and_explicit_exclusion_withdraw_shared_prose(self):
        home,vault=self.make_sources();note=vault/'one.md';note.write_text('# 合成笔记\n私密原文')
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(len(self.mac.search('私密原文')),1)
        shared_sources.refresh_mac(self.mac,home,network=False,mode='metadata')
        self.assertEqual(self.mac.search('私密原文'),[])
        self.assertEqual(len(self.mac.search('合成笔记')),1)
        note.write_text('---\nassistant_exclude: true\n---\n# 合成笔记\n不再使用')
        shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(self.mac.search('合成笔记'),[])

    def test_replacing_source_root_does_not_expand_approved_shared_scope(self):
        from personal_asis.config import root_identity
        home,vault=self.make_sources();(vault/'one.md').write_text('# 已授权资料\n合成正文')
        scope=dict(notes={'life':root_identity(vault)},reading=[])
        shared_sources.refresh_mac(self.mac,home,network=False,scope=scope)
        self.assertEqual(len(self.mac.search('已授权资料')),1)
        other=self.root/'new-vault';other.mkdir();(other/'two.md').write_text('# 未授权新根目录\n另一份正文')
        config=json.loads((home/'sources.yaml').read_text());config['sources'][0]['root']=str(other)
        (home/'sources.yaml').write_text(json.dumps(config))
        shared_sources.refresh_mac(self.mac,home,network=False,scope=scope)
        self.assertEqual(self.mac.search('未授权新根目录'),[])
        self.assertEqual(self.mac.search('已授权资料'),[])

    def test_reading_accounts_and_forget_do_not_mix_or_infer_platform_deletion(self):
        from personal_asis.reading_library import Library
        from personal_asis.reading_sources import Article
        home,vault=self.make_sources()
        accounts={('xiaohongshu','first'):'合成账号一',('xiaohongshu','second'):'合成账号二'}
        with Library(home,accounts=accounts) as library:
            for account in ('first','second'):
                library.put('xiaohongshu',account,Article('same','合成收藏',author_text='账号内容'+account),'favorite')
        with patch('personal_asis.reading_library.configured_accounts',return_value=accounts):
            shared_sources.refresh_mac(self.mac,home,network=False)
            self.assertEqual(len(self.mac.search('合成收藏')),2)
            self.assertEqual(len(self.mac.search('合成收藏',account='first')),1)
            with Library(home,accounts=accounts) as library:library.forget('xiaohongshu','first','same')
            shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(self.mac.search('合成收藏',account='first'),[])
        self.assertEqual(len(self.mac.search('合成收藏',account='second')),1)

    def test_explicitly_disabled_reading_account_withdraws_shared_body(self):
        from personal_asis.reading_library import Library
        from personal_asis.reading_sources import Article
        home,vault=self.make_sources();accounts={('wucai','cn'):'合成五彩'}
        with Library(home,accounts=accounts) as library:library.put('wucai','cn',Article('one','合成划线',user_note='本人合成批注'),'saved_article')
        with patch('personal_asis.reading_library.configured_accounts',return_value=accounts):
            shared_sources.refresh_mac(self.mac,home,network=False)
            self.assertEqual(len(self.mac.search('本人合成批注')),1)
            with Library(home,accounts=accounts) as library:
                library.db.execute("UPDATE accounts SET enabled=0 WHERE source='wucai'");library.db.commit()
            shared_sources.refresh_mac(self.mac,home,network=False)
        self.assertEqual(self.mac.search('本人合成批注'),[])

    def test_refresh_does_not_rehash_unchanged_notes_and_missing_cache_is_not_deletion(self):
        from personal_asis.index import Index
        home,vault=self.make_sources();(vault/'one.md').write_text('# 合成标题\n无需重复读取')
        shared_sources.refresh_mac(self.mac,home,network=False)
        with patch.object(Index,'_current',side_effect=AssertionError('unchanged file rehashed')):
            shared_sources.refresh_mac(self.mac,home,network=False)

    def test_diary_skip_still_runs_refresh_and_exchange_noninteractive_does_not(self):
        from personal_asis import life_sync
        home,vault=self.make_sources();profile=self.root/'profile';profile.mkdir()
        (profile/'life-sync.json').write_text(json.dumps(dict(enabled=True,host='owner@example.test',daily_directory='Daily',journal_layout_mode='plain',shared_sync_mode='text')))
        record=self.life.capture('p','owner','r','合成日记','2026-10-26T08:00:00+08:00')[0]
        def pull(config,state):state['records'][record['id']]=record
        with patch.object(life_sync,'pull',side_effect=pull),patch.object(life_sync,'publish_status'),patch('builtins.input',return_value=''),patch.object(shared_sync,'run',return_value='complete') as phases,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(life_sync.startup(home,profile,interactive=True),'skipped')
            phases.assert_called_once()
        with patch.object(shared_sync,'run') as phases,patch.object(life_sync,'pull') as upstream:
            self.assertEqual(life_sync.startup(home,profile,interactive=False),'interactive_sync_required')
            phases.assert_not_called();upstream.assert_not_called()


class SharedPluginTests(unittest.TestCase):
    def setUp(self):
        from test_life_bedtime import PluginTests
        PluginTests.setUp(self)
        self.bot.home=self.bot.home.resolve()
        self.event=lambda *args,**kw:PluginTests.event(self,*args,**kw)
        from personal_asis import shared_store,shared_sources,shared_cli
        mappings={'synthetic_life_plugin.'+name:module for name,module in (
            ('shared_store',shared_store),('shared_sources',shared_sources),('shared_cli',shared_cli))}
        mock=patch.dict(sys.modules,mappings);mock.start();self.addCleanup(mock.stop)

    def test_owner_can_search_read_and_add_idempotent_annotation_without_editing_source(self):
        key=identity('synthetic-doc')
        value=shared_sources.document_bodies('study','Note/synthetic.md','合成电路笔记','合成电路分析')[0]
        with SharedStore(self.bot.home/'shared.sqlite3','vps') as db:
            db.receive(dict(changes=[dict(origin='mac',collection='notes',id=key,version=1,body=value)],cursor=1,more=False),'mac')
        event=self.event('帮我记下一点补充')
        async def run():
            denied=await self.bot.shared_knowledge(self.event('搜索',owner=False),'search',query='电路')
            self.assertEqual(denied,'owner_required')
            result=json.loads(await self.bot.shared_knowledge(event,'search',query='电路'))
            self.assertEqual(result['results'][0]['id'],key)
            row=json.loads(await self.bot.shared_knowledge(event,'read',record_id=key))
            self.assertEqual(row['body']['text'],'合成电路分析')
            one=json.loads(await self.bot.shared_knowledge(event,'annotate',record_id=key,text='先核对合成条件'))
            two=json.loads(await self.bot.shared_knowledge(event,'annotate',record_id=key,text='先核对合成条件'))
            self.assertEqual(one,two)
            return one
        annotation=asyncio.run(run())
        with SharedStore(self.bot.home/'shared.sqlite3','vps') as db:
            self.assertEqual(db.read('mac','notes',key)['body']['text'],'合成电路分析')
            self.assertEqual(db.read('vps','annotations',annotation['id'])['body']['text'],'先核对合成条件')


if __name__ == '__main__':
    unittest.main()
