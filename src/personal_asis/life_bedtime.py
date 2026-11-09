"""Retired bedtime scheduler: keep provenance helpers and disable old policy rows."""
import re
from .life_store import digest


def owner_key(platform, sender):
    if not platform or not sender:
        raise ValueError('owner_binding_required')
    return digest(platform + '\0' + sender)


def retire(store):
    """Idempotently disable legacy policies without changing evidence or receipts."""
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bedtime_policy'").fetchone():
        with store.db:
            store.db.execute('UPDATE bedtime_policy SET enabled=0 WHERE enabled!=0')


def is_goodnight(text):
    # Full-message whitelist: quotes, negations, questions and retrospective reports
    # must not accidentally silence reminders. Commands have their own explicit path.
    if any(c in text for c in '?？'):
        return False
    text = re.sub(r'[\s，。！,.!～~、；;：:🌙😴💤]', '', text)
    return bool(re.fullmatch(r'(?:晚安[啦了咯]?|(?:我要|我准备|准备|我去|去|我)?睡觉[了啦咯]|我?睡了){1,3}', text))
