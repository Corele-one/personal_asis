"""Private PWA feedback queue and version-bound corrections of derived life data."""
import json
import re
from .life_store import timestamp
from .life_tracking import HABITS, clean, observations, validate, evidence_text

FIELDS = ('summary','tracking','entry_excluded','revision')


class LifeFeedback:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS feedback_jobs(
          id TEXT PRIMARY KEY, thread TEXT NOT NULL, state TEXT NOT NULL,
          payload TEXT NOT NULL, created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS feedback_thread ON feedback_jobs(thread,created);
        ''')

    def submit(self, value):
        if not isinstance(value,dict) or set(value) != {'id','thread','text','record_id','revision'}:
            raise ValueError('invalid_feedback_request')
        for key in ('id','thread'):
            if not isinstance(value[key],str) or not re.fullmatch('[a-f0-9]{32}',value[key]):
                raise ValueError('invalid_feedback_identity')
        text = clean(value['text'],4000)
        if not text:raise ValueError('feedback_text_required')
        if type(value['revision']) is not int or value['revision'] < 0:
            raise ValueError('invalid_feedback_revision')
        rid = value['record_id']
        if not isinstance(rid,str) or rid and not re.fullmatch('[a-f0-9]{64}',rid):
            raise ValueError('invalid_feedback_target')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT payload FROM feedback_jobs WHERE id=?',(value['id'],)).fetchone()
            if old:
                saved=json.loads(old[0])
                if any(saved[k] != value[k] for k in value):raise ValueError('feedback_id_conflict')
                return dict(id=value['id'],state=self.db.execute('SELECT state FROM feedback_jobs WHERE id=?',(value['id'],)).fetchone()[0])
            if self.db.execute("SELECT 1 FROM feedback_jobs WHERE state IN ('pending','running')").fetchone():
                raise ValueError('feedback_busy')
            if rid:
                record = self.store.get(rid)
                if record['deleted'] or record['revision'] != value['revision']:
                    raise ValueError('feedback_record_changed')
            payload=dict(value,reply='',effect=None,error='')
            self.db.execute('INSERT INTO feedback_jobs VALUES(?,?,?,?,?)',(value['id'],value['thread'],'pending',json.dumps(payload,ensure_ascii=False),timestamp()))
        return dict(id=value['id'],state='pending')

    def thread(self, thread):
        if not re.fullmatch('[a-f0-9]{32}',thread):raise ValueError('invalid_feedback_identity')
        rows=self.db.execute('SELECT state,payload FROM feedback_jobs WHERE thread=? ORDER BY created DESC LIMIT 12',(thread,)).fetchall()
        return [dict(json.loads(row['payload']),state=row['state']) for row in reversed(rows)]

    def claim(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT payload FROM feedback_jobs WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
            if not row:return None
            job=json.loads(row[0]);self.db.execute("UPDATE feedback_jobs SET state='running' WHERE id=?",(job['id'],))
            return job

    def finish(self, job, *, reply='', error=''):
        with self.db:
            current=self.db.execute('SELECT payload FROM feedback_jobs WHERE id=?',(job['id'],)).fetchone()
            value=json.loads(current[0]);value.update(reply=clean(reply,16000),error=error)
            self.db.execute('UPDATE feedback_jobs SET state=?,payload=? WHERE id=?',('unknown' if error else 'done',json.dumps(value,ensure_ascii=False),job['id']))

    def recover(self):
        # Never resend a paid request after process interruption, even if a
        # correction reached SQLite before its final natural-language response.
        with self.db:
            self.db.execute("UPDATE feedback_jobs SET state='unknown' WHERE state='running'")

    def correct(self, job, owner, *, action, habit='', value=''):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT state,payload FROM feedback_jobs WHERE id=?',(job['id'],)).fetchone()
            saved=json.loads(row['payload'])
            if row['state'] != 'running':raise ValueError('feedback_not_running')
            if saved['effect']:
                return saved['effect']
            if not re.search(r'不是|不对|不妥|错|误|删|去掉|移除|改|纠正|更正|取消|其实|实际|应[该当]',saved['text']):
                raise ValueError('explicit_correction_required')
            # Target and expected revision come only from the authenticated UI,
            # never from a tool argument or model-supplied identifier.
            if not saved['record_id']:raise ValueError('select_record_before_correction')
            r=self.store.get(saved['record_id'])
            if (r['platform'],r['sender']) != tuple(owner):raise ValueError('feedback_owner_required')
            if r['deleted'] or r['revision'] != saved['revision']:raise ValueError('feedback_record_changed')
            before={k:r.get(k) for k in FIELDS};tracking=observations(r)
            if action == 'clear_habit':
                if habit not in HABITS:raise ValueError('invalid_habit')
                tracking['habits']=[h for h in tracking['habits'] if h['habit'] != habit]
                r['tracking']=tracking
            elif action == 'clear_learning':
                items = tracking['learning']
                if value:
                    if sum(item['topic'] == value for item in items) != 1:
                        raise ValueError('learning_topic_ambiguous')
                    items = [item for item in items if item['topic'] != value]
                elif len(items) > 1:
                    raise ValueError('learning_topic_required')
                else:
                    items = []
                r['tracking']=dict(tracking,learning=items)
            elif action == 'exclude_entry':
                if not re.search(r'日记|随记|同步|生活记录',saved['text']):
                    raise ValueError('explicit_journal_exclusion_required')
                r.update(entry_excluded=True,tracking=dict(habits=[],learning=[]))
            elif action == 'summary':
                r['summary']=clean(value,4000)
            elif action == 'tracking':
                notes=r.get('feedback_notes',[])[-7:]+[dict(id=job['id'],text=saved['text'],at=timestamp())]
                r['feedback_notes']=notes
                tracking=json.loads(value)
                validate(tracking,evidence_text(r))
                r['tracking']=tracking
            else:
                raise ValueError('invalid_feedback_action')
            r.update(revision=r['revision']+1,updated_at=timestamp())
            # Prepared summaries must not continue displaying withdrawn evidence.
            # Do not erase explicitly selected continuing goals on a tracking edit.
            for report in self.db.execute('SELECT owner,day,payload FROM attention_delivery').fetchall() if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='attention_delivery'").fetchone() else []:
                if r['id'] in json.loads(report['payload']).get('source_ids',[]):
                    self.db.execute("UPDATE attention_delivery SET state='withdrawn',payload='{}' WHERE owner=? AND day=?",(report['owner'],report['day']))
            self.store._save(r)
            effect=dict(action=action,record_id=r['id'],before=before,after={k:r.get(k) for k in FIELDS},saved_on='VPS',obsidian='requires_Mac_confirmation')
            saved['effect']=effect
            self.db.execute('UPDATE feedback_jobs SET payload=? WHERE id=?',(json.dumps(saved,ensure_ascii=False),job['id']))
            return effect
