"""Installed AstrBot/Lark SDK + native temporary conversations. No real transport."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,sys.argv[1])
module = importlib.import_module('astrbot_plugin_life_agent.chat_interaction')
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.conversation_mgr import ConversationManager
import astrbot.core.conversation_mgr as cm
import lark_oapi as lark

class SessionStore:
    def __init__(self): self.values={}
    async def session_put(self,origin,key,value): self.values[origin,key]=value
    async def session_get(self,origin,key,default=None): return self.values.get((origin,key),default)

class Transport:
    def __init__(self): self.calls=[]
    async def acreate(self,request):
        self.calls.append(('create',request))
        return NS(success=lambda:True,data=NS(message_id='synthetic-card',reaction_id='synthetic-reaction'))
    async def areply(self,request):
        self.calls.append(('reply',request))
        return NS(success=lambda:True,data=NS(message_id='synthetic-card'))
    async def apatch(self,request):
        self.calls.append(('patch',request));return NS(success=lambda:True)
    async def adelete(self,request):
        self.calls.append(('delete',request));return NS(success=lambda:True)

async def main():
    with tempfile.TemporaryDirectory(prefix='asis-c6-synthetic-') as tmp:
        db=SQLiteDatabase(str(Path(tmp)/'native.sqlite3'))
        await db.initialize()
        manager=ConversationManager(db)
        origin='synthetic:FriendMessage:owner'
        with patch.object(cm,'sp',SessionStore()):
            a=await manager.new_conversation(origin,title='合成当前',content=[dict(role='user',content='合成历史')])
            b=await manager.new_conversation(origin,title='合成另一话题')
            foreign=await manager.new_conversation('synthetic:FriendMessage:other',title='禁止显示')
            await manager.switch_conversation(origin,a)
            transport=Transport()
            client=NS(im=NS(v1=NS(message=transport,message_reaction=transport)))
            handler=lark.EventDispatcherHandler.builder('','').register_p2_im_message_receive_v1(lambda e:None).build()
            platform=NS(lark_api=client,event_handler=handler)
            context=NS(conversation_manager=manager,get_platform_inst=lambda _:platform)
            bot=NS(home=Path(tmp),context=context,config=dict(owner_id='owner',owner_platform='synthetic'),calendar_pending={})
            bridge=module.ChatInteraction(bot)
            initial=dict(handler._processorMap)
            try:
                context.get_platform_inst=lambda _:None
                assert not bridge.install() and bridge.attach_status=='waiting_for_platform'
                context.get_platform_inst=lambda _:platform
                assert bridge.install()
                assert bridge.installed and bridge.attach_status=='attached'
                assert bridge.install()  # lifecycle replay is idempotent
                card=await bridge.ui.card(origin)
                assert '禁止显示' not in json.dumps(card,ensure_ascii=False)
                assert 'p2.card.action.trigger' in handler._callback_processor_map
                assert all(handler._processorMap[k] is v for k,v in initial.items())
                extras={}
                async def forbidden_send(*a,**k):raise AssertionError('unexpected_fallback_send')
                event=NS(message_str='/chat',message_obj=NS(message_id='synthetic-message'),
                    bot=client,unified_msg_origin=origin,get_platform_id=lambda:'synthetic',
                    stop_event=lambda:extras.update(stopped=True),get_extra=lambda k:extras.get(k),
                    set_extra=lambda k,v:extras.update({k:v}),send=forbidden_send)
                assert await bridge.command(event)
                assert len(transport.calls)==1 and transport.calls[0][0]=='reply'
                await bridge.command(event)
                assert len(transport.calls)==1
                code=bridge.ui.token(origin,a,'switch',b)
                payload=dict(schema='2.0',header=dict(event_type='card.action.trigger',event_id='synthetic-click'),
                    event=dict(operator=dict(open_id='stranger'),action=dict(value=dict(asis_chat_action=code)),
                    context=dict(open_message_id='synthetic-card')))
                handler._do_without_validation(json.dumps(payload).encode())
                await asyncio.sleep(0)
                assert await manager.get_curr_conversation_id(origin)==a
                payload['event']['operator']['open_id']='owner'
                handler._do_without_validation(json.dumps(payload).encode())
                await asyncio.gather(*list(bridge.tasks))
                assert await manager.get_curr_conversation_id(origin)==b
                # The next native turn resolves the selected conversation, without rewriting old history.
                selected=await manager.get_conversation(origin,await manager.get_curr_conversation_id(origin))
                assert selected.cid==b
                old=await manager.get_conversation(origin,a)
                assert json.loads(old.history)[0]['content']=='合成历史'
                count=len(await manager.get_conversations(origin))
                handler._do_without_validation(json.dumps(payload).encode())
                await asyncio.gather(*list(bridge.tasks))
                assert len(await manager.get_conversations(origin))==count
                assert await manager.get_curr_conversation_id(origin)==b
                denied=bridge.ui.token(origin,b,'switch',foreign)
                assert '不可用' in await bridge.ui.act(origin,denied)
                await bridge.reaction(event,'processing')
                await bridge.reaction(event,'processing')
                await bridge.reaction(event,'done')
                await bridge.reaction(event,'done')
                assert [k for k,_ in transport.calls].count('delete')==1
                creates=[r for k,r in transport.calls if k=='create']
                assert len(creates)==1 and creates[0].request_body.reaction_type.emoji_type=='Typing'
                # Persistent claim means an unknown create cannot be reissued.
                async def unavailable(req): raise TimeoutError()
                transport.acreate=unavailable
                event.message_obj.message_id='synthetic-timeout'
                await bridge.reaction(event,'processing')
                assert not bridge.ui.reserve_reaction(module.reaction_key('synthetic','synthetic-timeout'),'processing')
                print(json.dumps(dict(actual_sdk=True,native_temp_conversations=True,deferred_platform_attachment=True,
                    selected_next_turn=True,old_history_preserved=True,foreign_owner_denied=True,
                    callback_sdk_dispatch=True,duplicate_and_stale_claims=True,command_delivery_dedup=True,
                    actual_reaction_builders=True,unknown_reaction_not_reissued=True,
                    platform_requests=0,model_calls=0)))
            finally:
                await bridge.close()
                assert handler._processorMap==initial
                assert not handler._callback_processor_map
                await db.engine.dispose()

asyncio.run(main())
