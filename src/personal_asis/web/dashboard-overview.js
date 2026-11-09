/* Render business observations as text; this view never controls an agent. */
window.Overview=(()=>{
 const element=id=>document.getElementById(id);
 const node=(tag,text,cls='')=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
 const time=value=>{const date=new Date(value);return value&&Number.isFinite(date.valueOf())?date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚无观测时间';};
 const labels={running:'运行中',stopped:'已停止',fresh:'最近已更新',stale:'上次观测已过期',unknown:'暂时未知',observed:'已接入',not_connected:'未接入',not_configured:'未启用'};
 function clear(){for(const id of ['overview-services','overview-pending','overview-recent'])element(id).replaceChildren();element('overview-updated').textContent='';}
 function render(data){
  clear();element('overview-updated').textContent='总览取得于 '+time(data.observed_at)+' · 北京时间';
  for(const [key,title] of [['chat','Chat'],['router','模型调用'],['mac','Mac 同步'],['library','共享资料'],['memory','共享记忆'],['work','Work']]){
   const item=data[key]||{state:'unknown'},card=node('article','','panel overview-card');
   card.append(node('h3',title),node('strong',labels[item.state]||'暂时未知','overview-state state-'+item.state));
   if(key==='router'){
    if(item.total_requests!==undefined)card.append(node('p','今日发出 '+item.total_requests+' 次请求'));
    if(item.last_model)card.append(node('p','最近模型：'+item.last_model));
    if(item.last_status)card.append(node('p','该次请求：'+({completed:'完成',success:'成功',sending:'结果待核对',failed:'失败',unknown:'结果未知'}[item.last_status]||item.last_status)));
    card.append(node('p',item.label||'等待可用的调用观测','muted'));
   }
   if(key==='mac')card.append(node('p','这是上次检查，不能据此判断 Mac 现在是否在线。','muted'));
   if(key==='library'&&item.replica_complete!==undefined)card.append(node('p',item.replica_complete?'最近一批副本已接收完整':'当前副本覆盖尚未确认；资料查询会说明范围。','muted'));
   if(key==='memory')card.append(node('p','旧会话仍可按需回查；跨会话个人记忆尚未启用。','muted'));
   if(key==='work')card.append(node('p','未接入 Work 状态，Chat 与生活看板可独立使用。','muted'));
   card.append(node('small','来源：'+(item.source||'未取得来源')),node('small',time(item.observed_at)));
   element('overview-services').append(card);
  }
  const pending=data.pending||{};
  for(const [title,value,detail] of [
   ['日记待确认',pending.journal,'来自 Mac 上次检查：'+time(pending.journal_observed_at)+'；写入仍需在 Mac 确认。'],
   ['记录纠正',pending.feedback,'VPS 处理中；结果待核对 '+(pending.feedback_unknown??'未知')+' 项。'],
   ['日历确认',null,'当前在原聊天中查看预览；日历批次尚未接入总览。']]){
   const box=node('article','','panel');box.append(node('h3',title),node('strong',value==null?'—':String(value),'overview-number'),node('p',detail,'muted'));element('overview-pending').append(box);
  }
  const recent=data.recent||[];
  for(const item of recent){const card=node('article','','record overview-recent-card');card.append(node('small',item.day+' · '+item.source),node('p',item.text),node('small','记录更新：'+time(item.observed_at)));const link=node('a','查看生活记录 ↗');link.href='/dashboard#records';card.append(link);element('overview-recent').append(card);}
  if(!recent.length)element('overview-recent').append(node('p','当前没有可展示的主动随记。未记录不等于未发生。','muted'));
 }
 return {render,clear};
})();
