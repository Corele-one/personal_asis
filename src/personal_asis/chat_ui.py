"""Private Chat UI receipts; native AstrBot remains conversation/history authority."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

EMOJI = {'[捂脸]':'🤦', '[笑哭]':'😂', '[微笑]':'🙂', '[思考]':'🤔',
         '[点赞]':'👍', '[拥抱]':'🫂', '[爱心]':'❤️', '[加油]':'💪', '[庆祝]':'🎉'}

def display_emoji(text):
    """Conservative display-only conversion: code and quoted lines stay literal."""
    fence = None
    result = []
    for line in text.splitlines(keepends=True):
        mark = re.match(r'^\s*(`{3,}|~{3,})', line)
        if mark:
            token = mark[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append(line)
            continue
        if fence or re.match(r'^\s*>', line) or any(q in line for q in ('"', "'", '“', '”', '「', '」')):
            result.append(line)
            continue
        # Inline code and markdown links/images are source references.
        pieces = re.split(r'(`+[^`]*`+|!?\[[^\]]*\]\([^)]*\)|!?\[[^\]]*\]\[[^\]]*\])', line)
        for i in range(0, len(pieces), 2):
            pieces[i] = re.sub(r'\[[^\]\n]{1,8}\]', lambda m: EMOJI.get(m[0], m[0]), pieces[i])
        result.append(''.join(pieces))
    return ''.join(result)

def safe_title(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or '未命名会话'))[:60]

class ChatUI:
    def __init__(self, path, manager, *, clock=time.time):
        self.manager, self.clock = manager, clock
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS actions(token TEXT PRIMARY KEY, origin TEXT, expected TEXT,
                kind TEXT, target TEXT, expires REAL, state TEXT);
            CREATE TABLE IF NOT EXISTS archived(origin TEXT, cid TEXT, PRIMARY KEY(origin,cid));
            CREATE TABLE IF NOT EXISTS models(origin TEXT, cid TEXT, model TEXT, at REAL, PRIMARY KEY(origin,cid));
            CREATE TABLE IF NOT EXISTS reactions(key TEXT PRIMARY KEY, phase TEXT, reaction_id TEXT, state TEXT);
            CREATE TABLE IF NOT EXISTS cards(message_id TEXT PRIMARY KEY, origin TEXT);
            CREATE TABLE IF NOT EXISTS deliveries(key TEXT PRIMARY KEY);
        """)
        self.locks = {}
        self.active = {}

    def close(self):
        self.db.close()

    def claim_delivery(self, key):
        return self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?)',(key,)).rowcount == 1

    def lock(self, origin):
        return self.locks.setdefault(origin, asyncio.Lock())

    def token(self, origin, expected, kind, target=''):
        self.db.execute('DELETE FROM actions WHERE expires<?', (self.clock()-86400,))
        token = secrets.token_hex(16)
        self.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?)',
            (token, origin, expected or '', kind, target, self.clock()+300, 'ready'))
        return token

    async def current(self, origin):
        return await self.manager.get_curr_conversation_id(origin) or ''

    async def conversations(self, origin):
        # Native get_conversation ignores origin when fetching by id. Verify owner explicitly.
        return [c for c in await self.manager.get_conversations(origin)
                if c.user_id == origin]

    async def act(self, origin, token):
        async with self.lock(origin):
            row = self.db.execute('SELECT * FROM actions WHERE token=?', (token,)).fetchone()
            if not row or row['origin'] != origin or row['expires'] < self.clock() or row['state'] != 'ready':
                return '这个按钮已处理或过期，请发送 /chat 刷新。'
            if self.active.get(origin):
                return '当前消息仍在处理中，请等回复完成后再切换会话。'
            current = await self.current(origin)
            if current != row['expected']:
                return '当前会话已变化，旧卡片未执行。请发送 /chat 刷新。'
            if row['kind'] not in ('new', 'switch', 'archive', 'restore'):
                return '操作不可用。'
            if row['kind'] != 'new':
                conv = await self.manager.get_conversation(origin, row['target'])
                if not conv or conv.user_id != origin:
                    return '目标会话已不可用，没有执行。'
            if await self.current(origin) != current:
                return '当前会话已变化，请刷新后重试。'
            changed = self.db.execute("UPDATE actions SET state='claimed' WHERE token=? AND state='ready'", (token,))
            if changed.rowcount != 1:
                return '这个按钮已处理，请刷新。'
            try:
                if row['kind'] == 'new':
                    await self.manager.new_conversation(origin, title=row['target'] or '新话题')
                    result = '已新建 Chat 会话，下一条消息进入新话题。'
                elif row['kind'] == 'switch':
                    await self.manager.switch_conversation(origin, row['target'])
                    self.db.execute('DELETE FROM archived WHERE origin=? AND cid=?', (origin,row['target']))
                    result = '已切换 Chat 会话，下一条消息进入所选会话。'
                elif row['kind'] == 'restore':
                    self.db.execute('DELETE FROM archived WHERE origin=? AND cid=?', (origin,row['target']))
                    result = '已从归档恢复；当前会话未改变。'
                else:
                    # Switch away first; if interrupted, do not hide the active session.
                    if row['target'] == current:
                        await self.manager.new_conversation(origin, title='新话题')
                    self.db.execute('INSERT OR IGNORE INTO archived VALUES(?,?)', (origin,row['target']))
                    result = '已归档，历史保留。'
                self.db.execute("UPDATE actions SET state='done' WHERE token=?", (token,))
                return result
            except BaseException:
                self.db.execute("UPDATE actions SET state='unknown' WHERE token=?", (token,))
                raise

    async def card(self, origin, *, archived=False, notice='', pending_count=0):
        async with self.lock(origin):
            cid = await self.current(origin)
            convs = await self.conversations(origin)
            current = next((c for c in convs if c.cid == cid), None)
            hidden = {r[0] for r in self.db.execute('SELECT cid FROM archived WHERE origin=?',(origin,))}
            visible = [c for c in convs if (c.cid in hidden) == archived]
            visible.sort(key=lambda c: getattr(c,'updated_at',0) or 0, reverse=True)
            model = self.db.execute('SELECT model FROM models WHERE origin=? AND cid=?',(origin,cid)).fetchone()
            title = safe_title(current.title) if current else '尚无当前会话'
            status = '处理中' if self.active.get(origin) else '待确认' if pending_count else '就绪'
            def plain(text):
                return dict(tag='div',text=dict(tag='plain_text',content=text))
            elements = [plain(notice)] if notice else []
            elements += [plain('当前会话：'+title+'\n状态：'+status+
                '\n最近实际模型：'+(model[0] if model else '尚无本卡片可核对回执')+
                '\n待确认日历操作：'+str(pending_count)+'\n跨会话个人记忆：未启用；旧会话仅按需回查，最近回答的回查参与未观测。')]
            def button(text, kind, target=''):
                code = self.token(origin,cid,kind,target)
                return dict(tag='button',text=dict(tag='plain_text',content=text),
                    type='default',value=dict(asis_chat_action=code))
            elements.append(dict(tag='action',actions=[button('新话题','new')]+
                ([button('归档当前会话','archive',cid)] if current else [])))
            elements.append(plain(('归档会话' if archived else '最近会话')+'（最多8个；归档不删除历史）'))
            for conv in visible[:8]:
                elements.append(plain(('● ' if conv.cid == cid else '')+safe_title(conv.title)))
                elements.append(dict(tag='action',actions=[button('恢复' if archived else '切换到此会话',
                    'restore' if archived else 'switch',conv.cid)]))
            elements += [dict(tag='hr'), plain(
                '常用入口\n/chat 会话面板　/chat archived 归档列表\n/chat new 标题 新话题\n'
                '/chat switch 完整标题 切换　/chat archive 归档当前\n'
                '/router status 模型路由　/life status 记录状态\n/life 内容 主动随记；普通聊天不进入日记。\n'
                '按钮5分钟有效；不派发Work，不写日历或笔记。\n'
                '按钮未生效时可发 /chat；输入框实时斜杠补全未接入。')]
            return dict(config=dict(wide_screen_mode=True),header=dict(
                title=dict(tag='plain_text',content='个人助手 · Chat'),template='blue'),elements=elements)

    def attributed(self, origin, cid, model):
        if model and cid:
            self.db.execute('INSERT OR REPLACE INTO models VALUES(?,?,?,?)',
                (origin,cid,model,self.clock()))

    def reserve_reaction(self, key, phase):
        # One create attempt per inbound message/phase, including across restarts.
        return self.db.execute('INSERT OR IGNORE INTO reactions VALUES(?,?,?,?)',
            (key+':'+phase,phase,'','claimed')).rowcount == 1

    def reaction_saved(self, key, phase, reaction_id):
        self.db.execute("UPDATE reactions SET reaction_id=?,state='created' WHERE key=?",
            (reaction_id,key+':'+phase))

    def take_reaction(self, key, phase):
        row = self.db.execute('SELECT reaction_id,state FROM reactions WHERE key=?',(key+':'+phase,)).fetchone()
        if not row or row['state'] != 'created':
            return ''
        self.db.execute("UPDATE reactions SET state='delete_claimed' WHERE key=?",(key+':'+phase,))
        return row['reaction_id']

def reaction_key(platform, message_id):
    return hashlib.sha256(json.dumps([platform,message_id]).encode()).hexdigest()
