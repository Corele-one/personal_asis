"""Allowlisted provider error facts. Never retain error bodies or headers."""

from email.utils import parsedate_to_datetime
import json
import math
import time


CATEGORIES={'quota_signal','concurrency_signal','rate_signal','balance_signal',
            'overload_signal','http_error','network_timeout','transport_or_response_unknown',
            'output_limit','content_filter','repetition_truncated'}


def http_diagnostic(error, clock=time.time):
    result={'http_status':error.code,'category':'http_error','retry_after_seconds':None}
    header=error.headers.get('Retry-After','') if error.headers else ''
    if isinstance(header,str) and len(header)<=128:
        try:
            delay=int(header) if header.isdigit() else math.ceil(parsedate_to_datetime(header).timestamp()-clock())
            if 1<=delay<=7*86400:
                result['retry_after_seconds']=delay
        except (ValueError,TypeError,OverflowError):
            pass
    try:
        raw=error.read(8193)
        if len(raw)>8192:
            return result
        body=json.loads(raw)
        detail=body.get('error',body) if isinstance(body,dict) else None
        if not isinstance(detail,dict):
            return result
        message=detail.get('message','')
        if not isinstance(message,str):
            return result
        message=message.lower()
        for category,terms in (
            ('concurrency_signal',('concurren','并发')),
            ('quota_signal',('quota','token plan','额度','套餐')),
            ('balance_signal',('balance','余额')),
            ('overload_signal',('overload','过载','繁忙')),
            ('rate_signal',('rate limit','too many requests','频繁','速率'))):
            if any(term in message for term in terms):
                result['category']=category
                break
    except (OSError,ValueError,UnicodeError,TypeError):
        pass
    return result


def validate_diagnostic(value):
    if (not isinstance(value,dict) or set(value)!={'http_status','category','retry_after_seconds'} or
            value['category'] not in CATEGORIES or
            (value['http_status'] is not None and (type(value['http_status']) is not int or not 100<=value['http_status']<=599)) or
            (value['retry_after_seconds'] is not None and
             (type(value['retry_after_seconds']) is not int or not 1<=value['retry_after_seconds']<=7*86400))):
        raise ValueError('invalid_provider_diagnostic')
    return value


def diagnostic_for(error):
    value=getattr(error,'diagnostic',None)
    if value is not None:
        return validate_diagnostic(value)
    current=error
    category='transport_or_response_unknown'
    for _ in range(8):
        if current is None:
            break
        if isinstance(current,TimeoutError) or isinstance(getattr(current,'reason',None),TimeoutError):
            category='network_timeout'
            break
        current=current.__context__
    return {'http_status':None,'category':category,'retry_after_seconds':None}
