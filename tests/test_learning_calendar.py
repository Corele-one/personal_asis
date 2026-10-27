import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from personal_asis.dashboard import snapshot
from personal_asis.life_store import LifeStore
from personal_asis.life_tracking import LifeTracking


class LearningCalendarBackendTests(unittest.TestCase):
    def test_all_dates_beyond_recent_window_revisions_conversation_and_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve();store=LifeStore(home/'life.sqlite3')
            try:
                a=store.capture('fixture','owner','old','/life 开始学习 模集','2024-02-29T15:00:00Z')[0]
                a=LifeTracking(store).auto(a)
                b=store.capture('fixture','owner','new','/life 学完了 锁相环','2026-10-26T22:00:00+08:00')[0]
                LifeTracking(store).auto(b)
                memory=store.capture('fixture','owner','memory','普通聊天学完了 C++','2026-10-26T23:00:00+08:00',capture_source='conversation')[0]
                # A legacy derived observation cannot bypass current intake gates.
                with store.db:
                    store._save(dict(memory,tracking=a['tracking']))
                for n in range(101):store.capture('fixture','owner','other'+str(n),'/life 今天风很大','2026-10-27T12:00:00+08:00')
                data=snapshot(home,'2026-10-27')
                self.assertEqual(data['tracking']['learning'],[])
                self.assertEqual(len(data['astrbot']['records']),100)
                self.assertEqual(len(data['learning_live']),2)
                old=next(r for r in data['learning_live'] if r['record_id']==a['id'])
                self.assertEqual((old['day'],old['time'],old['topic']),('2024-02-29','23:00','模拟集成电路'))
                self.assertEqual(old['record_revision'],a['revision'])
                self.assertNotIn(str(home),json.dumps(data))
                store.delete(a['id'])
                self.assertEqual(len(snapshot(home,'2026-10-27')['learning_live']),1)
            finally:store.close()


@unittest.skipUnless(shutil.which('node'),'Node required for calendar behavior validation')
class LearningCalendarViewTests(unittest.TestCase):
    def run_node(self,code):
        script=Path(__file__).resolve().parents[1]/'src/personal_asis/web/dashboard-learning.js'
        result=subprocess.run(['node','-e',"const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');vm.runInThisContext(fs.readFileSync("+json.dumps(str(script))+",'utf8'));\n"+code],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_leap_year_week_alignment_invalid_dates_and_filter_consistency(self):
        self.run_node('''
const c=LearningCalendar;
assert.equal(c.daysForYear(2024).filter(Boolean).length,366);
assert.equal(c.daysForYear(2026).filter(Boolean).length,365);
assert.equal(c.daysForYear(2012).length/7,54);
assert.equal(c.daysForYear(0).length,0);
assert.equal(c.validDay('2026-02-30'),false);
assert.equal(c.daysForYear(2026)[3],'2026-01-01');
const rows=[{day:'2026-05-07',topic:'电路',content:'复习共模增益',source:'life'},
 {day:'2026-05-07',topic:'电路',content:'研究原理',source:'astrbot',blocker:'负反馈'},
 {day:'2026-05-08',topic:'FPGA',content:'实验',source:'study'},
 {day:'2025-05-08',topic:'电路',content:'去年'},
 {day:'2026-02-30',topic:'错误日期',content:'不能计数'}];
let model=c.calendarModel(rows,{year:'2026'});
assert.equal(model.days,2);assert.equal(model.count,3);assert.equal(model.topics,2);
assert.equal(model.latest,'2026-05-08');assert.equal(model.perDay.get('2026-05-07').length,2);
model=c.calendarModel(rows,{year:'2026',topic:'电路',query:'负反馈'});
assert.equal(model.days,1);assert.equal(model.count,1);assert.equal(model.latest,'2026-05-07');
''')

    def test_click_day_details_filter_close_refresh_and_clear(self):
        self.run_node('''
// A small DOM fixture exercises the real handlers without a browser/network.
class Node {
 constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this.textContent='';this.value='';this.className='';this.hidden=false;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=[...items];}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){this.focused=true;}
 click(){if(this.onclick)this.onclick();}
 querySelector(selector){return walk(this).find(n=>selector.startsWith('.')?n.className.split(' ').includes(selector.slice(1)):n.dataset.day===selector.match(/data-day="(.*?)"/)[1]);}
}
function walk(n){return [n,...n.children.flatMap(walk)];}
global.document={createElement:tag=>new Node(tag)};
const root=new Node('div'),selected=[];
const view=LearningCalendar.mount(root,{today:'2026-10-27',onSelectDay:day=>selected.push(day),correctionButton:()=>new Node('button')});
const history={available:true,replica_complete:true,rows:[{day:'2026-05-07',topic:'电路',phase:'legacy',source:'life',path:'Calendar/Journal/Daily/2026-05-07.md',line:20,content:'学习共模增益'},
 {day:'2026-05-08',topic:'FPGA',phase:'work',source:'study',path:'Research/Journal/2026-05-08.md',line:2,content:'探索实现'}]};
const live=[{day:'2026-05-07',topic:'电路',phase:'end',source:'astrbot',time:'22:00',content:'结束复习',record_id:'fixture',record_revision:2}];
view.update(history,live);
const detail=walk(root).find(n=>n.className==='lc-detail');
assert.equal(detail.hidden,true);
assert.equal(walk(root).some(n=>n.textContent==='学习共模增益'),false);
root.querySelector('.lc-scroll').scrollLeft=320;
root.querySelector('[data-day="2026-05-07"]').click();
assert.equal(root.querySelector('.lc-scroll').scrollLeft,320);
assert.deepEqual(selected,['2026-05-07']);assert.equal(detail.hidden,false);
assert.equal(walk(detail).filter(n=>n.className==='lc-topic-group').length,1);
assert.equal(walk(detail).filter(n=>n.className==='lc-entry').length,2);
assert.equal(walk(detail).some(n=>n.textContent==='探索实现'),false);
view.update(history,live);assert.equal(detail.hidden,false);
root.querySelector('.lc-close').click();assert.equal(detail.hidden,true);
const search=walk(root).find(n=>n.attrs['aria-label']==='搜索学习记录');search.value='FPGA';search.oninput();
root.querySelector('[data-day="2026-05-08"]').click();
assert.equal(walk(detail).some(n=>n.textContent==='探索实现'),true);
assert.equal(walk(detail).some(n=>n.textContent==='学习共模增益'),false);
view.clear();assert.equal(detail.hidden,true);assert.equal(search.value,'');
assert.equal(walk(root).some(n=>n.textContent==='探索实现'),false);
''')
