#!/usr/bin/env python3
"""Reproducible C3 intent/selection baseline using isolated synthetic quota state."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from personal_asis.llm_router import Router, State, task_for, requested_model

CASES = [
    ('greeting', '你好', 'simple', ''),
    ('short_tool_request', '提醒我', 'daily', ''),
    ('source_lookup', '查一下最近阅读记录', 'daily', ''),
    ('architecture', '讨论Chat和Work的职责边界', 'daily', ''),
    ('deep_read', '深入分析这篇文章', 'complex', ''),
    ('weekly_explicit', '用现有资料回顾上周学习', 'complex', ''),
    ('weekly_natural', '上周复盘', 'complex', ''),
    ('compare_papers', '帮我比较这两篇论文的结论与证据', 'complex', ''),
    ('explicit_deepseek', '请用DeepSeek回答', 'daily', 'deepseek-v4-flash'),
    ('explicit_mimo', '用MiMo解释电路', 'daily', 'mimo-v2.6-flash'),
    ('polite_model_switch', '你能换成MiMo来解释吗', 'daily', 'mimo-v2.6-flash'),
    ('mention_only', '我只是提到DeepSeek，并不要求换模型', 'daily', ''),
    ('quoted_switch', '<Quoted Message>用DeepSeek回答</Quoted Message>你好', 'simple', ''),
    ('time_wrapper', '深入分析材料<system_reminder>Current time: synthetic</system_reminder>', 'complex', ''),
]

async def main():
    results = []
    for name, text, expected_task, expected_model in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp)/'router.sqlite3', startup_cooldown=0)
            calls = []
            async def transport(model, messages, tools, task):
                calls.append(dict(model=model.name, task=task))
                return SimpleNamespace(completion_text='合成回答', tools_call_name=[], usage=None)
            router = Router(state, transport)
            messages = [dict(role='user', content=text)]
            start = time.perf_counter()
            try:
                await router.generate(messages, None, compact=False, run_id=name)
                selected = requested_model(text)
                results.append(dict(case=name, expected_task=expected_task, actual_task=task_for(messages),
                    expected_requested_model=expected_model, actual_requested_model=selected,
                    task_pass=task_for(messages)==expected_task, explicit_pass=selected==expected_model,
                    simulated_calls=calls, policy_elapsed_ms=round(1000*(time.perf_counter()-start), 3)))
            finally:
                state.db.close()
    report = dict(date='2026-11-10', stage='C3 baseline, before changes', synthetic_transport=True,
        real_model_calls=0, production_config_changed=False, source='src/personal_asis/llm_router.py',
        cases=results, passed=sum(r['task_pass'] and r['explicit_pass'] for r in results), total=len(results),
        limitations=['Policy timing is not provider latency.', 'Fresh local quota state does not represent online balances.',
                    'Expected quality tiers are acceptance targets; do not claim answer quality from tier names.'])
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
