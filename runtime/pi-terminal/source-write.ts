/** Native Pi write confirmation only. No conversation or retrieval restrictions. */
import { spawn } from 'node:child_process';
import { Type } from '@earendil-works/pi-ai';
import { defineTool, type ExtensionAPI } from '@earendil-works/pi-coding-agent';

function invoke(action: string, data: unknown): Promise<any> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.ASIS_WRITE_PYTHON!, ['-m', 'personal_asis.source_write', action], {env:process.env, stdio:['pipe','pipe','pipe']});
    let output=''; child.stdout.on('data', c => {output+=c; if(output.length>1000000) child.kill();});
    child.on('error',reject);
    child.on('close',()=>{try{resolve(JSON.parse(output));}catch{reject(Error('write_adapter_unavailable'));}});
    child.stdin.end(JSON.stringify(data));
  });
}
export default function(pi: ExtensionAPI) {
  pi.registerTool(defineTool({
    name:'source_write', label:'确认平台写入',
    description:'Propose a WUCAI or XiaoHongShu write. Human UI confirmation is mandatory. WUCAI: append_diary(content), update_article_note(note_idx,note), set_article_status(note_idx,status). XiaoHongShu: like_feed(feed_id,xsec_token,unlike), favorite_feed(feed_id,xsec_token,unfavorite), post_comment_to_feed(feed_id,xsec_token,content). Dashboard: publish_summary(title,content) publishes only the confirmed text to the private VPS dashboard. No social posts, deletion, or automatic retries.',
    parameters:Type.Object({source:Type.Union([Type.Literal('wucai'),Type.Literal('xiaohongshu'),Type.Literal('dashboard')]),operation:Type.String(),arguments:Type.Record(Type.String(),Type.Union([Type.String(),Type.Boolean()]))}),
    async execute(_id,params,_signal,_update,ctx){
      const result=(v:unknown)=>({content:[{type:'text' as const,text:JSON.stringify(v)}],details:{}});
      if(!ctx.hasUI)return result({state:'interactive_confirmation_required'});
      const plan=await invoke('prepare',params);
      if(plan.error)return result(plan);
      const ok=await ctx.ui.confirm('确认此次平台／看板写入？（五分钟内有效）',plan.preview);
      if(!ok)return result({state:'cancelled'});
      return result(await invoke('execute',{plan:plan.plan,digest:plan.digest}));
    }
  }));
}
