"""Generate a standalone Obsidian Dataview learning overview, without writing notes."""
from pathlib import Path
import json
from .learning_history import ALIASES, UNFINISHED


def render_note(study_history=None, *, imported_at=''):
    script=Path(__file__).with_suffix('.mjs').read_text().replace('export function ','function ').replace('export async function ','async function ')
    history = dict(rows=study_history or [], imported_at=imported_at)
    if any(r.get('source') != 'study' for r in history['rows']):
        raise ValueError('tracker_only_imports_external_study_history')
    script=script.replace('const HISTORY_RULES = null;', 'const HISTORY_RULES = '+json.dumps(dict(aliases=ALIASES, unfinished=UNFINISHED.pattern),ensure_ascii=False)+';')
    script=script.replace('const STUDY_HISTORY = null;', 'const STUDY_HISTORY = '+json.dumps(history,ensure_ascii=False)+';')
    return ('# 学习追踪\n\n汇总 Life 的学习记录与 Study 的历史研究日志，保留原文出处。\n\n'
            '```dataviewjs\n'+script+'\nawait renderLearningTracker(dv, app, this.container);\n```\n')
