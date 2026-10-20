"""Stable, channel-independent Conversation Core API (conversation-session-v1)."""
import json

from . import conversation as core
from .conversation_tools import submit


API_VERSION='conversation-session-v1'


class ConversationAPI:
    """Thin application boundary; authentication and channel disclosure stay in adapters."""
    def __init__(self, home):
        self.home=home

    def create(self):
        with core.ConversationStore(self.home) as store:
            return {'api_version':API_VERSION,'session_id':store.create()}

    def sessions(self):
        with core.ConversationStore(self.home) as store:
            # A remote-capable API must not leak content through list previews;
            # even locally, expose only stable identity and activity time.
            rows=store.sessions()
            return {'api_version':API_VERSION,'sessions':[{'id':row['id'],'at':row['at']} for row in rows]}

    def history(self, sid):
        with core.ConversationStore(self.home) as store:
            store.clean(sid)
            turns=[]
            for row in store.turns(sid):
                item={'turn_id':row['id'],'status':row['status'],'error':row['error']}
                if row['state']:
                    state=json.loads(row['state'])
                    item['question']=state['question']
                    if row['status']=='waiting_permission':
                        item['permission']=state.get('pending_permission')
                if row['result']:
                    item['result']=json.loads(row['result'])
                turns.append(item)
            return {'api_version':API_VERSION,'session_id':sid,'turns':turns}

    def send(self, sid, message, turn_id):
        return {'api_version':API_VERSION,**submit(self.home,sid,message,turn_id=turn_id)}

    def status(self, sid, turn_id=None):
        return {'api_version':API_VERSION,**core.inspect(self.home,sid,turn_id)}

    def budget(self):
        return {'api_version':API_VERSION,**core.budget_status(self.home)}

    def events(self, sid, after=0, limit=200):
        with core.ConversationStore(self.home) as store:
            return {'api_version':API_VERSION,'events':store.events(sid,after,limit)}

    def control(self, sid, action, turn_id):
        if action in ('approve','deny'):
            return self.send(sid,'/approve' if action=='approve' else '/deny',turn_id)
        if action=='resume':
            current=core.inspect(self.home,sid)
            if not current.get('turn_id'):
                raise ValueError('chat_turn_not_found')
            if current['turn_id']!=turn_id:
                raise ValueError('chat_control_target_conflict')
            return {'api_version':API_VERSION,**core.send(self.home,sid,turn_id=current['turn_id'],resume=True)}
        if action=='cancel':
            core.cancel(self.home,sid,turn_id)
            return self.status(sid,turn_id)
        if action=='forget':
            with core.ConversationStore(self.home) as store:
                store.forget(sid)
            return self.status(sid)
        raise ValueError('chat_invalid_control_action')
