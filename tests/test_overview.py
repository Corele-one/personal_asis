from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from personal_asis.overview import snapshot
from personal_asis.chat_status import publish
from personal_asis.life_store import LifeStore
from personal_asis.life_feedback import LifeFeedback
from personal_asis.llm_router import State,BY_NAME


class OverviewTests(unittest.TestCase):
    def test_missing_services_are_independent_and_do_not_create_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'missing'
            result=snapshot(home)
            self.assertFalse(home.exists())
            self.assertEqual(result['memory']['state'],'not_configured')
            self.assertEqual(result['work']['state'],'not_connected')
            self.assertEqual(result['chat']['state'],'unknown')
            self.assertEqual(result['recent'],[])
            self.assertIsNone(result['pending']['journal'])

    def test_fresh_stale_and_invalid_observations_do_not_imply_live_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            self.assertTrue(publish(home))
            current=datetime.now(timezone.utc).timestamp()
            self.assertEqual(snapshot(home,now=current)['chat']['state'],'running')
            self.assertEqual(snapshot(home,now=current+100)['chat']['state'],'stale')
            publish(home,ready=False)
            self.assertEqual(snapshot(home)['chat']['state'],'stopped')
            (home/'mac-status.json').write_text(json.dumps(dict(checked_at='2026-11-01T12:00:00+08:00',pending=4,applied=12,sources={k:True for k in ('life','study','wucai','xiaohongshu')})))
            result=snapshot(home,now=datetime.fromisoformat('2026-11-09T12:00:00+08:00').timestamp())
            self.assertEqual(result['mac']['state'],'stale')
            self.assertEqual(result['pending']['journal'],4)
            (home/'mac-status.json').write_text('broken')
            (home/'chat-status.json').write_text('broken')
            result=snapshot(home)
            self.assertEqual(result['chat']['state'],'unknown')
            self.assertEqual(result['work']['state'],'not_connected')

    def test_only_explicit_entries_are_recent_and_router_reads_preserve_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);home=root/'life';home.mkdir()
            store=LifeStore(home/'life.sqlite3')
            try:
                store.capture('p','owner','ordinary','普通聊天不能当日记',capture_source='conversation')
                r,_=store.capture('p','owner','entry','<script>合成主动随记</script>',capture_source='life_command')
                store.capture('p','owner','deleted','已删除的随记')
                store.delete(store.recent()[0]['id'])
                LifeFeedback(store).submit(dict(id='a'*32,thread='b'*32,text='合成纠正',record_id=r['id'],revision=r['revision']))
            finally:store.close()
            router_home=root/'router';router=State(router_home/'router.sqlite3',startup_cooldown=0)
            try:
                attempt,_=router.reserve(BY_NAME['mimo-v2.6-flash'],100,'daily')
                router.finish(attempt,actual=50)
            finally:router.db.close()
            before=(router_home/'router.sqlite3').read_bytes()
            result=snapshot(home,router_home=router_home)
            self.assertEqual([v['record_id'] for v in result['recent']],[r['id']])
            self.assertEqual(result['pending']['feedback'],1)
            self.assertEqual(result['router']['total_requests'],1)
            self.assertIn('不是官方',result['router']['label'])
            self.assertEqual(before,(router_home/'router.sqlite3').read_bytes())
            self.assertNotIn(tmp,json.dumps(result))
