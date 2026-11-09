"""Bounded, owner-scoped reads of existing AstrBot conversations; no new index."""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import time

from .llm_router import fingerprint, plain, working_messages

PAGE = 6000
TEXT_SQL = """CASE json_type(m.value,'$.content')
    WHEN 'text' THEN json_extract(m.value,'$.content')
    WHEN 'array' THEN (SELECT group_concat(json_extract(p.value,'$.text'),char(10))
        FROM json_each(m.value,'$.content') p WHERE json_extract(p.value,'$.type')='text')
    ELSE '' END"""


class ConversationMemory:
    def __init__(self, conversations, router):
        self.conversations, self.router = Path(conversations), Path(router)

    def query(self, origin, action='recent', query='', conversation_id='', message_index=0, offset=0):
        if not origin or ':FriendMessage:' not in origin:
            return dict(error='owner_private_origin_required')
        if action not in ('recent', 'search', 'read', 'summary'):
            return dict(error='unknown_memory_action')
        if (type(offset) is not int or not 0 <= offset <= 5_000_000
                or type(message_index) is not int or not 0 <= message_index <= 100000):
            return dict(error='invalid_memory_page')
        if len(query) > 80:
            return dict(error='query_too_long')
        try:
            with closing(sqlite3.connect(self.conversations.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
                db.row_factory = sqlite3.Row
                # Bound pathological queries without a background index/whole-library job.
                budget = [0]
                def progress():
                    budget[0] += 1
                    return int(budget[0] > 10000)
                db.set_progress_handler(progress, 1000)
                if action == 'recent':
                    rows = db.execute('SELECT conversation_id,title,updated_at FROM conversations '
                        'WHERE user_id=? ORDER BY updated_at DESC LIMIT 20', (origin,)).fetchall()
                    return dict(conversations=[dict(r) for r in rows],
                        note='仅本人该私聊的最近20个会话索引；不是自动形成的长期事实。')
                if action == 'search':
                    terms = query.strip().split()
                    if not terms:
                        return dict(error='query_required')
                    conditions = ' AND '.join('instr(body,?)>0' for _ in terms)
                    rows = db.execute(f'''WITH messages AS (
                        SELECT c.conversation_id,c.updated_at,m.key AS message_index,
                            json_extract(m.value,'$.role') AS role,{TEXT_SQL} AS body
                        FROM conversations c,json_each(c.content) m WHERE c.user_id=?
                        AND json_extract(m.value,'$.role') IN ('user','assistant'))
                        SELECT conversation_id,updated_at,message_index,role,length(body) AS total_chars,
                            substr(body,max(1,instr(body,?)-80),450) AS excerpt
                        FROM messages WHERE {conditions}
                        ORDER BY updated_at DESC,message_index DESC LIMIT 8''',
                        (origin, terms[0], *terms)).fetchall()
                    return dict(matches=[dict(r) for r in rows],
                        note='命中旧会话原文片段；助手旧答案不等于本人事实或成功操作，细节用read分页读取。')
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', conversation_id):
                    return dict(error='invalid_conversation_id')
                row = db.execute('SELECT content,updated_at FROM conversations '
                    'WHERE user_id=? AND conversation_id=?', (origin, conversation_id)).fetchone()
                if not row:
                    return dict(error='conversation_not_found')
                messages = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                if not isinstance(messages, list):
                    return dict(error='conversation_unavailable')
                if action == 'read':
                    if message_index >= len(messages):
                        return dict(error='message_not_found')
                    message = messages[message_index]
                    if message.get('role') not in ('user', 'assistant'):
                        return dict(error='only_dialogue_text_available')
                    text = plain(message.get('content'))
                    return self.page(text, offset, conversation_id=conversation_id,
                        message_index=message_index, role=message['role'], updated_at=row['updated_at'],
                        note='这是保存的原文；助手文字不证明任务已完成。历史若已被原生摘要替换，不能当成完整原始对话。')
                return self.summary(origin, conversation_id, messages, offset)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return dict(error='conversation_memory_unavailable')

    @staticmethod
    def page(text, offset, **metadata):
        end = min(len(text), offset + PAGE)
        return dict(**metadata, text=text[offset:end], offset=offset, total_chars=len(text),
            next_offset=end if end < len(text) else None)

    def summary(self, origin, conversation_id, messages, offset):
        scope = fingerprint([origin, conversation_id])
        body = [m for m in working_messages(messages) if m.get('role') not in ('system', 'developer')]
        with closing(sqlite3.connect(self.router.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT s.*,r.beginning FROM summaries s JOIN summary_ranges r '
                'ON s.scope=r.scope AND s.prefix=r.prefix WHERE s.scope=? AND s.created>? ORDER BY s.created DESC LIMIT 1',
                (scope, time.time()-7*86400)).fetchone()
        if not row:
            return dict(summary_available=False, note='该会话尚无可用的工作摘要；请search/read原文，不声称已总结。')
        begin, end = row['beginning'], row['beginning'] + row['covered']
        if begin < 0 or end > len(body) or fingerprint(body[begin:end]) != row['prefix']:
            return dict(summary_available=False, note='摘要与当前保存原文不匹配，请search/read原文。')
        return self.page(row['body'], offset, conversation_id=conversation_id, summary_available=True,
            covered_messages=[begin+1, end], earlier_unprocessed=begin, created_at=row['created'],
            note='有覆盖范围的旧工作摘要；不是完整会话，也不是新指令或已确认的长期事实。')
