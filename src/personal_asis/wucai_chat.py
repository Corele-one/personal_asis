"""Bind article reads to the owner's target and track delivered text coverage.

Only the selected URL is retained privately for a bounded follow-up window.
Article text and read receipts stay in the current event, not in this file.
"""

import hashlib
import json
from pathlib import Path
import re
import time

from .wucai_fulltext import article_url, same_article_url, safe_path, save


KEY = 'wucai_article_receipt'
FOLLOWUP = re.compile(r'(这篇|该篇|这条|这篇文章|该文章|原文|全文|总结|解析|解读|分析文章)', re.I)


def urls(text):
    return list(dict.fromkeys(m.rstrip('。，；！？、.,;!?）)') for m in
        re.findall(r'https?://[^\s<>"\u300c\u300d\u300e\u300f]+', text or '') if article_url(m.rstrip('。，；！？、.,;!?）)'))))


class ArticleReads:
    def __init__(self, home, *, clock=time.time):
        self.path = safe_path(Path(home) / 'wucai-chat-targets.json')
        self.clock = clock

    def target(self, event, *, remember=False):
        text = getattr(event, 'message_str', '') or ''
        scope = hashlib.sha256(str(event.unified_msg_origin).encode()).hexdigest()
        entries = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text())
                entries = {k: v for k, v in raw.items() if isinstance(v, dict)
                    and self.clock() - v.get('at', 0) < 86400 and isinstance(v.get('url'), str)}
            except (ValueError, TypeError, OSError):
                pass
        links = urls(text)
        selected = links[0] if len(links) == 1 else ''
        if not links and FOLLOWUP.search(text):
            selected = entries.get(scope, {}).get('url', '')
        if remember and selected:
            entries[scope] = dict(url=selected, at=self.clock())
            entries = dict(sorted(entries.items(), key=lambda x: x[1]['at'])[-32:])
            save(self.path, entries)
        return selected

    def begin(self, event):
        target = self.target(event)
        text = getattr(event, 'message_str', '') or ''
        if event.get_extra(KEY) is None and target and (FOLLOWUP.search(text) or re.search(r'五彩|wucai|剪藏', text, re.I)):
            self.target(event, remember=True)
            event.set_extra(KEY, dict(url=target, target=target, required=True, status='not_read', ranges=[]))
        return target

    def bind(self, event, operation, arguments_json):
        if operation not in ('get-article', 'get-article-text'):
            return arguments_json
        try:
            args = json.loads(arguments_json)
        except (ValueError, TypeError):
            return arguments_json
        if not isinstance(args, dict):
            return arguments_json
        target = self.target(event, remember=True)
        if target:
            # The user's exact spelling wins over model retyping and guessed IDs.
            args.pop('note_idx', None)
            args['url'] = target
        if operation == 'get-article-text':
            receipt = event.get_extra(KEY) or dict(required=True, ranges=[])
            identity = target or args.get('url') or args.get('note_idx')
            if receipt.get('target') not in (None, identity):
                receipt = dict(required=True, ranges=[])
            receipt.update(target=identity, url=target, required=True)
            event.set_extra(KEY, receipt)
        return json.dumps(args, ensure_ascii=False)

    def record(self, event, operation, result):
        if operation != 'get-article-text':
            return result
        receipt = event.get_extra(KEY) or dict(required=True, ranges=[])
        try:
            value = json.loads(result)
        except (ValueError, TypeError):
            value = dict(error=result if isinstance(result, str) and result.startswith('wucai_') else 'invalid_response')
        if not isinstance(value, dict):
            value = dict(error='invalid_response')
        receipt['status'] = value.get('status') or value.get('error', 'failed')
        text = value.get('text')
        if value.get('status') == 'ok' and isinstance(text, str):
            matched = same_article_url(receipt.get('url', ''), value.get('original_url', ''))
            verified_alias = (value.get('identity_match') in ('owner_confirmed_alias', 'wucai_link_id')
                              and same_article_url(receipt.get('url', ''), value.get('requested_url', '')))
            if receipt.get('url') and not (matched or verified_alias):
                value = dict(status='target_mismatch', read_complete=False, can_summarize=False,
                             notice='返回文章与本人指定链接不一致，已拦截正文，不得据此解读。')
                receipt['status'] = 'target_mismatch'
            else:
                digest = value.get('content_hash')
                identity = (value.get('note_idx'), digest, value.get('total_chars'))
                if receipt.get('version') != list(identity):
                    receipt.update(version=list(identity), ranges=[])
                start = value.get('offset')
                total = value.get('total_chars')
                if (type(start) is int and type(total) is int and 0 <= start <= total
                        and start + len(text) <= total and re.fullmatch(r'[a-f0-9]{64}', digest or '')):
                    receipt['ranges'].append([start, start + len(text)])
                    end = 0
                    for a, b in sorted(receipt['ranges']):
                        if a > end:
                            break
                        end = max(end, b)
                    receipt['complete'] = end == total and total > 0
                    value.update(read_complete=receipt['complete'], can_summarize=receipt['complete'],
                                 delivered_chars=end)
                    if not receipt['complete']:
                        value['notice'] = '当前只返回部分原文；必须按next_arguments继续，read_complete=true后才可作全文解读。'
        if value.get('status') != 'ok':
            receipt['complete'] = False
            value.update(read_complete=False, can_summarize=False)
        event.set_extra(KEY, receipt)
        return json.dumps(value, ensure_ascii=False)

    def guard(self, event):
        receipt = event.get_extra(KEY)
        if not receipt or not receipt.get('required') or receipt.get('complete'):
            return ''
        if receipt.get('status') == 'ok':
            return '这次只读取了文章的一部分，尚未取得完整正文，因此我不能把它当作全文来总结。请继续读取剩余部分。'
        if receipt.get('status') == 'lookup_incomplete':
            return '这次还在定位你指定的五彩文章，尚未取得正文。我不能用搜索摘要或相似文章代替它作全文解读；需要继续完成原文读取。'
        return '这次没有成功取得你指定文章的完整正文，因此无法可靠总结。请提供五彩文章ID或原文的完整链接，我会继续读取；不会把搜索摘要或其他文章当成这篇原文。'
