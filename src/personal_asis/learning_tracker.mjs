// Read-only Dataview view. Diary Markdown is the source; no writes or network.
const PHASES = {start:'开始', progress:'进展', end:'结束', legacy:'历史打卡', task:'任务勾选', work:'研究日志', manual:'手记'};
const HISTORY_RULES = null;
const STUDY_HISTORY = null;
const LEARNING = /^(?:📖\s*)?(?:Learning|Study)$/i;
const OLD_TOPICS = ['DDCA','Analog','Missing','Signal','C++','HDL'];
export function validDay(day) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  const value = new Date(day+'T00:00:00Z');
  return Number.isFinite(value.getTime()) && value.toISOString().slice(0,10) === day;
}
function surfaces(text) {
  let fence=null;
  return text.replaceAll('\r','').split('\n').map((line,index)=>{
    const marker=line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (marker) {
      if (!fence) fence=marker[1];
      else if (marker[1][0]===fence[0] && marker[1].length>=fence.length && !marker[2].trim()) fence=null;
      return {line,index,visible:false};
    }
    return {line,index,visible:!fence};
  });
}
export function parseLearningMarkdown(text,path,day) {
  if (!validDay(day)) return [];
  const lines=surfaces(text), regions=[];
  for(let i=0;i<lines.length;i++) {
    if(!lines[i].visible) continue;
    const h=lines[i].line.match(/^(#{1,4})\s+(.+?)\s*$/);
    if(h && LEARNING.test(h[2])) {
      let end=i+1;
      while(end<lines.length) {
        const item=lines[end], next=item.line.match(/^(#{1,6})\s+(.+?)\s*$/);
        if(item.visible && (/^---(?:\s+end-(?:multi-)?column(?: ---)?)?\s*$/.test(item.line)
          || /^!\[\[On This Day\.base\]\]/.test(item.line)
          || next && (next[1].length<=h[1].length || next[2]==='End-of-Day Checklist'))) break;
        end++;
      }
      regions.push([i+1,end]);
    }
    if(lines[i].line===`<!-- asis-learning:${day}:start -->`) {
      const end=lines.findIndex((l,j)=>j>i && l.visible && l.line===`<!-- asis-learning:${day}:end -->`);
      if(end>i) regions.push([i+1,end]);
    }
  }
  const rows=[];
  for(const [start,end] of regions) {
    let topic='', current=null;
    const finish=()=>{
      if(current) {
        current.content=current.body.join('\n').trim();delete current.body;
        if(current.phase!=='manual' || current.content) rows.push(current);current=null;
      }
    };
    for(let i=start;i<end;i++) {
      const {line,visible}=lines[i];
      if(!visible) continue;
      const old=line.match(/^####\s+(\d{2}:\d{2})\s*·\s*(开始|进展|结束)\s*·\s*(.+?)\s*$/);
      const heading=line.match(/^####\s+(.+?)\s*$/);
      const entry=line.match(/^- \*\*(\d{2}:\d{2})\s*·\s*(开始|进展|结束)\*\*\s*$/);
      if(old) {
        finish();topic=old[3];
        current={day,path,topic,time:old[1],phase:Object.keys(PHASES).find(k=>PHASES[k]===old[2]),body:[],source:'学习记录'};
      } else if(heading) {
        finish();topic=heading[1];current={day,path,topic,time:'',phase:'manual',body:[],source:'手写学习记录'};
      }
      else if(entry && topic) {
        finish();current={day,path,topic,time:entry[1],phase:Object.keys(PHASES).find(k=>PHASES[k]===entry[2]),body:[],source:'学习记录'};
      } else if(current && !/^<!-- asis-/.test(line)) {
        if(/^整理（可修正）：/.test(line)) continue;
        const body=line.replace(/^> ?/,'').replace(/^  /,'');
        if(!/^- \[[ xX]\]/.test(body)) current.body.push(body);
      }
    }
    finish();
  }
  return combineRows(rows);
}
function array(value) {return value ? Array.from(value) : [];}
export function legacyRows(page) {
  const day=page.file.name,path=page.file.path,rows=[];
  const tasks=array(page.file.tasks).filter(t=>t.completed);
  const found=new Set();
  for(const topic of OLD_TOPICS) {
    const flag=page[topic];
    const hit=flag===true || typeof flag==='number' && flag>0 || tasks.some(t=>String(t.text).includes(topic));
    if(hit) found.add(topic);
  }
  for(const task of tasks) {
    if(LEARNING.test(task.section?.subpath||'')) {
      const topic=String(task.text).trim();
      if(topic && topic.length<=160 && !OLD_TOPICS.some(t=>topic.includes(t))) found.add(topic);
    }
  }
  for(const topic of found) rows.push({day,path,topic,time:'',phase:'legacy',content:'旧字段或已勾选的学习打卡',source:'历史打卡'});
  return rows;
}
export function combineRows(rows) {
  const real=new Set(rows.filter(r=>r.content!=='旧字段或已勾选的学习打卡').map(r=>r.day+'\0'+r.topic));
  const seen=new Set();
  return rows.filter(r=>{
    if(r.phase==='legacy' && r.content==='旧字段或已勾选的学习打卡' && real.has(r.day+'\0'+r.topic)) return false;
    const key=JSON.stringify([r.day,r.topic,r.time,r.phase,r.content]);
    if(seen.has(key)) return false;seen.add(key);return true;
  }).sort((a,b)=>b.day.localeCompare(a.day) || a.time.localeCompare(b.time) || a.topic.localeCompare(b.topic,'zh-CN'));
}
export function historicalLifeRows(text,path,day,rules) {
  if(!validDay(day) || !rules) return [];
  const rows=[],unfinished=new RegExp(rules.unfinished), topics=rules.aliases.map(([topic,pattern])=>[topic,new RegExp(pattern,'i')]);let section='';
  const canonical=value=>topics.find(([,pattern])=>pattern.test(value))?.[0]||null;
  for(const item of surfaces(text)) {
    if(!item.visible)continue;
    const line=item.line,heading=line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if(heading){section=LEARNING.test(heading[2])?'learning':/^(?:🧾\s*)?(?:Tasks?|任务)$/i.test(heading[2])?'tasks':'';continue;}
    if(/^---(?:\s+end-(?:multi-)?column(?: ---)?)?\s*$/.test(line)||line.startsWith('![['))section='';
    const checked=line.match(/^\s*-\s*\[[xX]\]\s+(.+)$/),inline=line.match(/^\s*-\s*\[([^\]\n:]{1,80})::\s*(\d+(?:\.\d+)?)\s*\](.*)$/);
    let topic='',phase='';
    if(section==='learning') {
      if(inline&&Number(inline[2])>0){topic=canonical(inline[1])||inline[1].trim();phase='legacy';}
      else if(checked){topic=canonical(checked[1])||checked[1].trim();phase='legacy';}
    } else if(section==='tasks'&&checked&&!unfinished.test(checked[1])) {topic=canonical(checked[1]);phase='task';}
    if(topic) rows.push({day,path,topic,phase,content:line.trim(),line:item.index+1,time:'',source:'life'});
  }
  return rows;
}
export function dayCells(year) {
  const first=new Date(Date.UTC(year,0,1)), last=new Date(Date.UTC(year+1,0,1));
  const offset=(first.getUTCDay()+6)%7, cells=Array(offset).fill(null);
  for(let value=first.getTime();value<last.getTime();value+=86400000) cells.push(new Date(value).toISOString().slice(0,10));
  return cells;
}
const CSS=`
.learning-overview{--lt-gap:3px;--lt-cell:11px;margin:12px 0;color:var(--text-normal)}
.learning-overview .lt-heading{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
.learning-overview h2{margin:0 0 4px;border:0}.learning-overview .lt-muted{font-size:12px;color:var(--text-muted);margin:5px 0}
.learning-overview .lt-controls{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.learning-overview select,.learning-overview input{max-width:100%;height:34px}
.learning-overview .lt-search{flex:1;min-width:150px}.learning-overview .lt-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}
.learning-overview .lt-stat{padding:14px 12px;border:1px solid var(--background-modifier-border);border-radius:12px;background:var(--background-secondary)}
.learning-overview .lt-number{display:block;font-size:25px;line-height:1.3;font-weight:650}.learning-overview .lt-caption{font-size:12px;color:var(--text-muted)}
.learning-overview .lt-panel{border:1px solid var(--background-modifier-border);border-radius:14px;padding:18px;margin:16px 0;min-width:0}
.learning-overview .lt-scroll{overflow-x:auto;padding:4px 0 9px}.learning-overview .lt-months{display:grid;grid-auto-columns:var(--lt-cell);gap:var(--lt-gap);font-size:10px;color:var(--text-muted);height:21px}
.learning-overview .lt-months span{white-space:nowrap}.learning-overview .lt-grid{display:grid;grid-template-rows:repeat(7,var(--lt-cell));grid-auto-flow:column;grid-auto-columns:var(--lt-cell);gap:var(--lt-gap);width:max-content}
.learning-overview .lt-day{border:0;box-shadow:none!important;border-radius:2px;width:var(--lt-cell);height:var(--lt-cell);min-height:0;padding:0;display:block;background:var(--background-modifier-border)}
.learning-overview .lt-day[data-level="1"]{background:color-mix(in srgb,var(--interactive-accent) 35%,var(--background-primary))}
.learning-overview .lt-day[data-level="2"]{background:color-mix(in srgb,var(--interactive-accent) 60%,var(--background-primary))}
.learning-overview .lt-day[data-level="3"]{background:var(--interactive-accent)}.learning-overview .lt-day.lt-selected{outline:2px solid var(--text-normal);outline-offset:1px}
.learning-overview .lt-empty-day{visibility:hidden}.learning-overview .lt-chips{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.learning-overview .lt-chip{height:auto;white-space:normal;padding:5px 11px;border-radius:18px;max-width:100%}.learning-overview .lt-chip.is-active{background:var(--interactive-accent);color:var(--text-on-accent)}
.learning-overview .lt-row{padding:14px 0;border-bottom:1px solid var(--background-modifier-border)}.learning-overview .lt-row:last-child{border:0}
.learning-overview .lt-row-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.learning-overview .lt-topic{font-weight:600;overflow-wrap:anywhere}
.learning-overview .lt-body{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.learning-overview details{font-size:12px;color:var(--text-muted);margin-top:14px}
.learning-overview pre{white-space:pre-wrap;font-size:12px}.learning-overview .lt-reset{font-size:12px;margin-left:auto}
@media(max-width:640px){.learning-overview .lt-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.learning-overview .lt-panel{padding:13px}.learning-overview .lt-row-head{gap:7px}}
`;
function node(tag,text='',className='') {const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;}
export async function renderLearningTracker(dv,app,container) {
  const root=node('section','','learning-overview');container.append(root);
  const style=node('style',CSS);root.append(style);
  const heading=node('div','','lt-heading'), title=node('div');title.append(node('h2','学习足迹'),node('p','不同主题，在同一个地方回看。新增主题会自动出现。','lt-muted'));heading.append(title);root.append(heading);
  const pages=array(dv.pages('"Calendar/Journal/Daily"')).filter(p=>validDay(p.file.name) && p.file.path.startsWith('Calendar/Journal/Daily/'));
  const imported=STUDY_HISTORY||{rows:[],imported_at:''};
  const canonical=value=>HISTORY_RULES?.aliases.find(([,pattern])=>new RegExp(pattern,'i').test(value))?.[0]||value;
  const currentYear=String(new Date().getFullYear());
  const years=[...new Set([currentYear,...pages.map(p=>p.file.name.slice(0,4)),...imported.rows.map(r=>r.day.slice(0,4))])].sort().reverse();
  const controls=node('div','','lt-controls'), year=node('select'), topic=node('select'), search=node('input');
  year.setAttribute('aria-label','学习年份');topic.setAttribute('aria-label','学习主题');search.setAttribute('aria-label','搜索学习内容');search.placeholder='搜索主题、内容或问题';search.className='lt-search';
  for(const y of years){const o=node('option',y+' 年');o.value=y;year.append(o);}year.value=currentYear;
  controls.append(year,topic,search);root.append(controls);
  const status=node('p','','lt-muted'),stats=node('div','','lt-stats'),heat=node('div','','lt-panel'),chips=node('div','','lt-chips'),list=node('div','','lt-panel');root.append(status,stats,heat,chips,list);
  const help=node('details'),summary=node('summary','记录方式与统计口径');help.append(summary,node('p','Life 的 Learning、旧数字字段与已勾选学习任务实时读取。Study 研究日志来自经确认导入的历史快照，仅收 Today’s Work，未勾选待办与 Tomorrow Plan 不收录。任务勾选和研究日志不表示全部完成；热力图只统计有记录的日期，不推算时长或掌握程度。Study 内容更新后需重新导入。'),node('pre','#### 你的学习主题\n- **20:00 · 开始**  \n  本次要学习的具体内容\n- **21:10 · 结束**  \n  实际做了什么\n  待解决：目前的问题\n  下一步：下次先做什么'));root.append(help);
  let rows=[],selectedDay='',limit=50,token=0;const cache=new Map();
  function draw() {
    const query=search.value.trim().toLowerCase(), selected=topic.value;
    const filtered=rows.filter(r=>(!selected || r.topic===selected) && (!query || (r.topic+' '+r.content).toLowerCase().includes(query)));
    const days=new Set(filtered.map(r=>r.day)), subjects=new Set(filtered.map(r=>r.topic));
    stats.replaceChildren();for(const [value,label] of [[days.size,'有记录的天数'],[subjects.size,'学习主题'],[filtered.length,'学习记录'],[filtered[0]?.day.slice(5)||'—','最近记录']]){const card=node('div','','lt-stat');card.append(node('span',String(value),'lt-number'),node('span',label,'lt-caption'));stats.append(card);}
    const perDay=new Map();for(const r of filtered){if(!perDay.has(r.day))perDay.set(r.day,[]);perDay.get(r.day).push(r);}
    heat.replaceChildren(node('strong',year.value+' · 学习日历'),node('p','颜色越深，当天记录越多。点击一天查看详情。','lt-muted'));
    const scroller=node('div','','lt-scroll'),months=node('div','','lt-months'),grid=node('div','','lt-grid'),cells=dayCells(Number(year.value));
    for(let i=0;i<cells.length;i++) {
      const day=cells[i];if(!day){grid.append(node('span','','lt-day lt-empty-day'));continue;}
      if(day.endsWith('-01')){const m=node('span',Number(day.slice(5,7))+'月');m.style.gridColumn=(Math.floor(i/7)+1)+' / span 4';months.append(m);}
      const items=perDay.get(day)||[],cell=node('button','','lt-day'+(selectedDay===day?' lt-selected':''));cell.type='button';cell.dataset.level=String(Math.min(3,items.length));cell.title=day+(items.length?' · '+[...new Set(items.map(r=>r.topic))].join('、')+' · '+items.length+' 条':' · 暂无记录');cell.setAttribute('aria-label',cell.title);
      cell.onclick=()=>{selectedDay=selectedDay===day?'':day;limit=50;draw();};grid.append(cell);
    }
    scroller.append(months,grid);heat.append(scroller);
    chips.replaceChildren();const counts=new Map();for(const r of rows){if(!counts.has(r.topic))counts.set(r.topic,new Set());counts.get(r.topic).add(r.day);}
    for(const [name,dates] of [...counts].sort((a,b)=>b[1].size-a[1].size || a[0].localeCompare(b[0],'zh-CN')).slice(0,30)) {const chip=node('button',name+' · '+dates.size+' 天','lt-chip'+(selected===name?' is-active':''));chip.type='button';chip.onclick=()=>{topic.value=selected===name?'':name;selectedDay='';limit=50;draw();};chips.append(chip);}
    list.replaceChildren();const lh=node('div','','lt-row-head');lh.append(node('strong',selectedDay||'近期学习'));if(selectedDay){const reset=node('button','查看全年','lt-reset');reset.onclick=()=>{selectedDay='';draw();};lh.append(reset);}list.append(lh);
    const visible=filtered.filter(r=>!selectedDay || r.day===selectedDay);
    if(!visible.length)list.append(node('p','这个范围内还没有学习记录。可在日记 Learning 中按实际主题记录。','lt-muted'));
    for(const r of visible.slice(0,limit)) {
      const row=node('article','','lt-row'),head=node('div','','lt-row-head'),link=node('a',r.day);
      if(r.source==='study'){link.className='external-link';link.href='obsidian://open?vault=Study&file='+encodeURIComponent(r.path);}
      else {link.className='internal-link';link.href='#';link.setAttribute('data-href',r.path);link.onclick=e=>{e.preventDefault();app.workspace.openLinkText(r.path,dv.current().file.path);};}
      head.append(link,node('span',r.topic,'lt-topic'),node('span',(r.time?r.time+' · ':'')+PHASES[r.phase],'lt-muted'));row.append(head,node('p',r.content||'查看原日记中的学习记录。','lt-body'),node('p',(r.source==='study'?'Study':'Life')+' · '+r.path+(r.line?' : '+r.line:''),'lt-muted'));list.append(row);
    }
    if(visible.length>limit){const more=node('button','再看 50 条');more.onclick=()=>{limit+=50;draw();};list.append(more);}
  }
  async function loadYear() {
    const key=year.value,request=++token;status.textContent='正在读取 '+key+' 年的学习记录…';selectedDay='';limit=50;
    if(!cache.has(key)) {
      const selected=pages.filter(p=>p.file.name.startsWith(key+'-')),loaded=[];let failed=0;
      for(let i=0;i<selected.length;i+=16) {
        await Promise.all(selected.slice(i,i+16).map(async p=>{
          let parsed=[];try{const text=await dv.io.load(p.file.path);if(typeof text!=='string')throw Error();parsed=[...parseLearningMarkdown(text,p.file.path,p.file.name),...historicalLifeRows(text,p.file.path,p.file.name,HISTORY_RULES)];}catch{failed++;}
          loaded.push(...[...parsed,...legacyRows(p)].map(r=>({...r,topic:canonical(r.topic)})));
        }));
      }
      loaded.push(...imported.rows.filter(r=>r.day.startsWith(key+'-')));
      cache.set(key,{rows:combineRows(loaded),failed,count:selected.length});
    }
    if(request!==token)return;
    const value=cache.get(key);rows=value.rows;const previous=topic.value;topic.replaceChildren();const all=node('option','全部主题');all.value='';topic.append(all);
    for(const name of [...new Set(rows.map(r=>r.topic))].sort((a,b)=>a.localeCompare(b,'zh-CN'))){const option=node('option',name);option.value=name;topic.append(option);}topic.value=[...topic.options].some(o=>o.value===previous)?previous:'';
    status.textContent=(value.failed?`有 ${value.failed} 篇日记未能读取，当前统计不完整。`:`已检查 ${value.count} 篇 Life 日记。`)+(imported.imported_at?` Study 历史快照：${imported.imported_at}。`:'')+' 空白不代表未学习。';
    draw();
  }
  year.onchange=loadYear;topic.onchange=()=>{selectedDay='';limit=50;draw();};search.oninput=()=>{selectedDay='';limit=50;draw();};await loadYear();
}
