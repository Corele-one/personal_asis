"""Recover only existing owner /life image placeholders; never write a vault.

Run with VPS Python after deploying life_images. Credentials
remain in the existing VPS config; stdout contains counts and safe reasons only.
"""
import datetime
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

sys.path.insert(0, '/home/mac/personal-asis-v2/src')
from personal_asis.life_store import LifeStore
from personal_asis.life_intake import is_entry
from personal_asis import life_images


def main():
    base = Path('/home/mac/astrbot/data')
    owner = json.loads((base/'config/astrbot_plugin_life_agent_config.json').read_text(encoding='utf-8-sig'))
    platforms = json.loads((base/'cmd_config.json').read_text(encoding='utf-8-sig'))['platform']
    config = next(p for p in platforms if p.get('id') == owner['owner_platform'] and p.get('type') == 'lark')
    domain = config.get('domain') or 'https://open.feishu.cn'
    if domain != 'https://open.feishu.cn':
        raise ValueError('existing_feishu_cn_domain_required')
    # Same fixed official endpoints as the installed Lark SDK, without loading
    # its entire generated API tree beside the running bot on this small VPS.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('recovery_redirect_rejected')
    opener = build_opener(NoRedirect())
    def read(path, *, data=None, token='', limit=2_000_000):
        headers = {'Content-Type':'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            with opener.open(Request(domain+path, data=data, headers=headers),timeout=25) as response:
                body=response.read(limit+1)
            if len(body)>limit:
                raise ValueError('recovery_response_size_limit')
            return body
        except OSError:
            raise ValueError('recovery_http_unavailable') from None
    auth=json.loads(read('/open-apis/auth/v3/tenant_access_token/internal',
        data=json.dumps(dict(app_id=config['app_id'],app_secret=config['app_secret'])).encode()))
    if auth.get('code') != 0 or not auth.get('tenant_access_token'):
        raise ValueError('tenant_token_unavailable')
    token=auth['tenant_access_token']
    store = LifeStore(Path('/home/mac/.local/share/personal-asis-life/life.sqlite3'))
    try:
        candidates = [json.loads(row[0]) for row in store.db.execute('SELECT payload FROM records')]
        candidates = [r for r in candidates if not r['deleted'] and is_entry(r) and not r.get('images')
                      and '[image]' in r['text'] and r['platform'] == owner['owner_platform']
                      and r['sender'] == owner['owner_id']]
        if len(candidates) > 20:
            raise ValueError('recovery_batch_limit')
        staged, outcomes = [], []
        for r in candidates:
            try:
                message_path='/open-apis/im/v1/messages/'+quote(r['message'],safe='')
                response = json.loads(read(message_path+'?user_id_type=open_id',token=token))
                if response.get('code') != 0:
                    outcomes.append(dict(day=r['day'],status='message_unavailable',code=response.get('code')))
                    continue
                items = response.get('data',{}).get('items',[])
                if (len(items) != 1 or items[0].get('message_id') != r['message'] or items[0].get('deleted')
                        or items[0].get('sender',{}).get('id') != r['sender']
                        or items[0].get('msg_type') not in ('post','image')):
                    raise ValueError('message_identity_or_type_mismatch')
                message = items[0]
                content = json.loads(message['body']['content'])
                components = ([dict(tag='img',image_key=content.get('image_key'))] if message['msg_type'] == 'image'
                              else [c for row in content.get('content',[]) for c in (row if isinstance(row,list) else [row])
                                    if isinstance(c,dict)])
                # Like the installed adapter, ignore unsupported post tags.
                # Exact stored-text equality below prevents replacing a record
                # whose mentions/media or later edits cannot be reconstructed.
                text_parts, keys = [], []
                for c in components:
                    if c.get('tag') == 'img':
                        keys.append(c['image_key']);text_parts.append('[image]')
                    elif c.get('tag') == 'text' and c.get('text','').strip():
                        text_parts.append(c['text'].strip())
                    elif c.get('tag') == 'a' and c.get('text') and c.get('href'):
                        text_parts.append(f"{c['text'].strip()}({c['href'].strip()})")
                    elif c.get('tag') == 'a' and c.get('text'):
                        text_parts.append(c['text'].strip())
                recovered_text = ' '.join(text_parts).strip()
                if recovered_text.removeprefix('/') != r['text'].strip().removeprefix('/'):
                    raise ValueError('original_text_mismatch')
                if not 1 <= len(keys) <= life_images.MAX_IMAGES:
                    raise ValueError('image_count_limit')
                values = []
                for key in keys:
                    data=read(message_path+'/resources/'+quote(key,safe='')+'?type=image',
                              token=token,limit=life_images.MAX_BYTES)
                    item = life_images.descriptor(data)
                    values.append((item,data))
                staged.append((r,values))
            except (ValueError,KeyError,TypeError,OSError) as error:
                safe = str(error) if isinstance(error,ValueError) and str(error) in (
                    'message_identity_or_type_mismatch','unsupported_recovery_components','original_text_mismatch',
                    'image_count_limit','image_resource_unavailable','unsupported_diary_image','diary_image_size_limit') else 'recovery_unavailable'
                outcomes.append(dict(day=r['day'],status=safe))
        if staged:
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            backup = Path('/home/mac/personal-asis-v2-rollbacks')/('image-recovery-'+stamp)
            backup.mkdir(mode=0o700)
            dest=sqlite3.connect(backup/'life-before.sqlite3')
            try:
                store.db.backup(dest)
            finally:
                dest.close()
            (backup/'life-before.sqlite3').chmod(0o600)
            for r,values in staged:
                if store.get(r['id']) != r:
                    outcomes.append(dict(day=r['day'],status='record_changed'))
                    continue
                for item,data in values:
                    life_images.write_bytes(store.path.parent/'images'/life_images.filename(item),data)
                store.capture(r['platform'],r['sender'],r['message'],r['text'],capture_source='life_command',
                              images=[item for item,_ in values])
                outcomes.append(dict(day=r['day'],status='recovered',images=len(values)))
        print(json.dumps(dict(candidates=len(candidates),outcomes=outcomes,real_messages_sent=0,vault_writes=0)))
    finally:
        store.close()


if __name__ == '__main__':
    main()
