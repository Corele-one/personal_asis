/* Learning calendar: private same-origin data, no dependencies or writes. */
(function (scope) {
 'use strict';
 const phases={start:'开始',progress:'进展',end:'结束',legacy:'历史打卡',task:'任务勾选',work:'研究日志',manual:'手记'};
 const sources={study:'Study',life:'Life',astrbot:'AstrBot'};
 function validDay(day) {
  if(typeof day!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;
  const value=new Date(day+'T00:00:00Z');
  return Number.isFinite(value.getTime())&&value.toISOString().slice(0,10)===day;
 }
 function daysForYear(year) {
  year=Number(year);if(!Number.isInteger(year)||year<1||year>9999)return [];
  const first=new Date(String(year).padStart(4,'0')+'-01-01T00:00:00Z');
  const cells=Array((first.getUTCDay()+6)%7).fill(null);
  for(let time=first.getTime();new Date(time).getUTCFullYear()===year;time+=86400000)cells.push(new Date(time).toISOString().slice(0,10));
  while(cells.length%7)cells.push(null);
  return cells;
 }
 function filterRows(rows,{year,topic='',query=''}) {
  const needle=query.trim().toLowerCase();
  return rows.filter(r=>validDay(r.day)&&r.day.startsWith(year+'-')&&(!topic||r.topic===topic)&&
   (!needle||[r.topic,r.content,r.blocker,r.next_step,r.evidence].filter(Boolean).join(' ').toLowerCase().includes(needle)));
 }
 function calendarModel(rows,selection) {
  const filtered=filterRows(rows,selection),perDay=new Map();
  for(const row of filtered){if(!perDay.has(row.day))perDay.set(row.day,[]);perDay.get(row.day).push(row);}
  const dates=[...perDay.keys()].sort();
  return {rows:filtered,perDay,days:dates.length,topics:new Set(filtered.map(r=>r.topic)).size,
   count:filtered.length,latest:dates.at(-1)||'',cells:daysForYear(selection.year)};
 }
 function element(tag,text='',className='') {
  const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;
 }
 function button(text,className='') {const node=element('button',text,className);node.type='button';return node;}
 function mount(container,{onSelectDay=()=>{},correctionButton=()=>null,today}={}) {
  today=today||new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  const state={year:today.slice(0,4),topic:'',query:'',selectedDay:''};let rows=[];
  const controls=element('div','','lc-controls'),year=element('select'),topic=element('select'),search=element('input');
  year.setAttribute('aria-label','学习年份');topic.setAttribute('aria-label','学习主题');
  search.type='search';search.placeholder='搜索主题、内容或问题';search.setAttribute('aria-label','搜索学习记录');
  controls.append(year,topic,search);
  const status=element('p','','lc-status'),stats=element('div','','lc-stats'),map=element('div','','lc-map-panel'),chips=element('div','','lc-chips');
  const detail=element('section','','lc-detail');detail.hidden=true;detail.tabIndex=-1;detail.setAttribute('aria-label','当天学习详情');
  const hint=element('p','点选日历中的一天，回看当时具体学了什么。','lc-hint');
  container.append(controls,stats,map,chips,hint,detail,status);

  function chooseDay(day,{focus=true}={}) {
   state.selectedDay=state.selectedDay===day?'':day;draw();
   if(state.selectedDay){if(focus){detail.focus({preventScroll:true});detail.scrollIntoView?.({behavior:'smooth',block:'nearest'});}onSelectDay(day);}
  }
  function draw() {
   const scrollLeft=map.querySelector('.lc-scroll')?.scrollLeft||0;
   const model=calendarModel(rows,state);
   stats.replaceChildren();
   for(const [value,label] of [[model.days,'有记录的天数'],[model.topics,'学习主题'],[model.count,'学习记录'],[model.latest.slice(5)||'—','最近记录']]) {
    const card=element('div','','lc-stat');card.append(element('strong',String(value)),element('span',label));stats.append(card);
   }
   map.replaceChildren();const title=element('div','','lc-map-title');title.append(element('h3',state.year+' · 学习日历'),element('p','颜色越深，当天记录越多。空白不代表未学习。','muted'));map.append(title);
   const scroller=element('div','','lc-scroll');scroller.tabIndex=0;scroller.setAttribute('aria-label','全年学习热力图，可左右滚动');
   const calendar=element('div','','lc-calendar'),weekdays=element('div','','lc-weekdays'),body=element('div');
   for(const label of ['一','','三','','五','','日'])weekdays.append(element('span',label));
   const months=element('div','','lc-months'),grid=element('div','','lc-grid');
   grid.setAttribute('aria-label',state.year+' 年学习日期');
   for(let i=0;i<model.cells.length;i+=7) {
    const week=model.cells.slice(i,i+7),first=week.find(day=>day&&day.endsWith('-01'));
    months.append(element('span',first?Number(first.slice(5,7))+'月':''));
   }
   const focusDay=state.selectedDay||[...model.perDay.keys()].sort().at(-1)||model.cells.find(Boolean);
   const cells=new Map();
   for(const day of model.cells) {
    if(!day){grid.append(element('span','','lc-cell lc-padding'));continue;}
    const entries=model.perDay.get(day)||[],cell=button('','lc-cell');
    cell.dataset.day=day;cell.dataset.level=entries.length>=7?'4':entries.length>=4?'3':entries.length>=2?'2':entries.length?'1':'0';
    cell.title=day+(entries.length?' · '+entries.length+' 条 · '+[...new Set(entries.map(r=>r.topic))].join('、'):' · 暂无记录');
    cell.setAttribute('aria-label',cell.title);cell.setAttribute('aria-pressed',String(day===state.selectedDay));
    cell.tabIndex=day===focusDay?0:-1;
    cell.onclick=()=>chooseDay(day);
    cell.onkeydown=event=>{
     const shift={ArrowUp:-1,ArrowDown:1,ArrowLeft:-7,ArrowRight:7}[event.key];
     if(shift!==undefined){event.preventDefault();const index=model.cells.indexOf(day),target=cells.get(model.cells[index+shift]);if(target){cell.tabIndex=-1;target.tabIndex=0;target.focus();}}
    };
    cells.set(day,cell);grid.append(cell);
   }
   body.append(months,grid);calendar.append(weekdays,body);scroller.append(calendar);map.append(scroller);scroller.scrollLeft=scrollLeft;
   const legend=element('div','','lc-legend');legend.append(element('span','少'));
   for(let level=0;level<=4;level++){const swatch=element('span','','lc-cell');swatch.dataset.level=String(level);swatch.setAttribute('aria-hidden','true');legend.append(swatch);}
   legend.append(element('span','多'));map.append(legend);
   chips.replaceChildren();const counts=new Map();
   for(const row of rows.filter(r=>r.day.startsWith(state.year+'-'))){if(!counts.has(row.topic))counts.set(row.topic,new Set());counts.get(row.topic).add(row.day);}
   for(const [name,dates] of [...counts].sort((a,b)=>b[1].size-a[1].size||a[0].localeCompare(b[0],'zh-CN')).slice(0,6)) {
    const chip=button(name+' · '+dates.size+' 天','lc-chip');chip.setAttribute('aria-pressed',String(state.topic===name));
    chip.onclick=()=>{state.topic=state.topic===name?'':name;topic.value=state.topic;state.selectedDay='';draw();};chips.append(chip);
   }
   drawDay(model);
  }
  function drawDay(model) {
   detail.replaceChildren();detail.hidden=!state.selectedDay;hint.hidden=!!state.selectedDay;
   if(!state.selectedDay)return;
   const entries=(model.perDay.get(state.selectedDay)||[]).slice().sort((a,b)=>(a.time||'').localeCompare(b.time||'')||(a.line||0)-(b.line||0));
   const head=element('div','','lc-detail-heading'),heading=element('div');
   heading.append(element('p','当天的学习','eyebrow'),element('h3',state.selectedDay));
   const close=button('收起','lc-close');close.onclick=()=>{const day=state.selectedDay;state.selectedDay='';draw();const cell=map.querySelector('[data-day="'+day+'"]');if(cell)cell.focus();};
   head.append(heading,close);detail.append(head);
   if(!entries.length){detail.append(element('p','这一天在当前筛选下暂无记录。','muted'));return;}
   const groups=new Map();for(const row of entries){if(!groups.has(row.topic))groups.set(row.topic,[]);groups.get(row.topic).push(row);}
   for(const [name,items] of groups) {
    const group=element('section','','lc-topic-group');group.append(element('h4',name));
    for(const item of items) {
     const row=element('article','','lc-entry'),meta=element('p','','lc-entry-meta');
     meta.append(element('span',phases[item.phase]||'学习记录','lc-badge'),element('span',[item.time,sources[item.source]||item.source].filter(Boolean).join(' · ')));
     row.append(meta,element('p',item.content,'lc-content'));
     if(item.blocker)row.append(element('p','待解决：'+item.blocker,'lc-content'));
     if(item.next_step)row.append(element('p','下一步：'+item.next_step,'lc-content'));
     const provenance=element('details','','lc-provenance');provenance.append(element('summary','原文与出处'));
     if(item.source==='astrbot'){provenance.append(element('p','AstrBot · 本人 /life 主动记录'));if(item.evidence)provenance.append(element('p',item.evidence,'lc-content'));}
     else provenance.append(element('p',(sources[item.source]||item.source)+' · '+item.path+(item.line?' : '+item.line:'')));
     row.append(provenance);
     if(item.record_id){const correction=correctionButton(item.record_id,item.record_revision,item.topic);if(correction)row.append(correction);}
     group.append(row);
    }
    detail.append(group);
   }
  }
  function update(history={},live=[]) {
   rows=[...(history.rows||[]),...live].filter(r=>validDay(r.day));
   const years=[...new Set([today.slice(0,4),state.year,...rows.map(r=>r.day.slice(0,4))])].sort().reverse();
   if(!years.includes(state.year))state.year=years[0];
   year.replaceChildren();for(const value of years){const option=element('option',value+' 年');option.value=value;year.append(option);}year.value=state.year;
   topic.replaceChildren();const all=element('option','全部主题');all.value='';topic.append(all);
   for(const name of [...new Set(rows.map(r=>r.topic))].sort((a,b)=>a.localeCompare(b,'zh-CN'))){const option=element('option',name);option.value=name;topic.append(option);}
   if(!rows.some(r=>r.topic===state.topic))state.topic='';topic.value=state.topic;
   status.textContent=(history.checked_at?'Mac 历史最近同步：'+new Date(history.checked_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'。':'')+
    (history.available===false?'等待 Mac 同步 Life / Study 历史。':'')+
    ((history.incomplete||history.replica_complete===false)?'部分历史来源尚未完整同步。':'')+' 打卡、任务勾选与研究日志保留各自含义，不等同于全部完成。';
   draw();
  }
  year.onchange=()=>{state.year=year.value;state.selectedDay='';draw();};
  topic.onchange=()=>{state.topic=topic.value;state.selectedDay='';draw();};
  search.oninput=()=>{state.query=search.value;state.selectedDay='';draw();};
  detail.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();detail.querySelector('.lc-close').click();}};
  return {update,selectDay(day){if(validDay(day)){state.year=day.slice(0,4);year.value=state.year;state.selectedDay=day;draw();}},
   clear(){rows=[];state.year=today.slice(0,4);state.topic='';state.query='';state.selectedDay='';search.value='';year.replaceChildren();topic.replaceChildren();stats.replaceChildren();map.replaceChildren();chips.replaceChildren();detail.replaceChildren();detail.hidden=true;status.textContent='';hint.hidden=false;}};
 }
 scope.LearningCalendar={validDay,daysForYear,filterRows,calendarModel,mount};
})(globalThis);
