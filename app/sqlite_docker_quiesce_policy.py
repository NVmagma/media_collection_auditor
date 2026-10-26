"""Reduction-only requests for explicitly selected disposable container IDs.

No daemon calls, inventory completeness claim, production caller or start path.
"""
import base64
import json
import re

DENY = {'Allow': False, 'Msg': 'Maintenance request denied', 'Err': ''}


def validate_scope(values):
    if not isinstance(values, (list, tuple, frozenset)) or len(values) > 100:
        raise ValueError('Bounded immutable container identity scope required')
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{64}',v) for v in values):
        raise ValueError('Full container IDs required')
    if len(set(values)) != len(values):
        raise ValueError('Duplicate container identity')
    return frozenset(values)


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def authorize_quiesce_request(request, container_ids):
    try:
        scope=validate_scope(container_ids)
        if not isinstance(request,dict) or request.get('RequestMethod') not in ('GET','POST'): return DENY
        method=request['RequestMethod']
        uri=request.get('RequestURI')
        if not isinstance(uri,str) or len(uri)>256: return DENY
        match=re.fullmatch(r'/containers/([0-9a-f]{64})/(stop|update|json)',uri)
        if not match or match[1] not in scope: return DENY
        if (method=='GET') != (match[2]=='json'): return DENY
        if 'RequestHeaders' in request and 'RequestHeader' in request: return DENY
        headers=request.get('RequestHeaders',request.get('RequestHeader',{}))
        if not isinstance(headers,dict): return DENY
        selected={}
        for key,value in headers.items():
            if not isinstance(key,str) or not key.isascii() or not re.fullmatch(r'[A-Za-z0-9-]+',key): return DENY
            key=key.lower()
            if key in selected: return DENY
            if isinstance(value,list) and len(value)==1: value=value[0]
            if not isinstance(value,str): return DENY
            selected[key]=value
        if set(selected).intersection({'upgrade','connection','transfer-encoding','trailer','te','x-http-method-override'}): return DENY
        body=request.get('RequestBody')
        if match[2] in ('stop','json'):
            if body not in (None,'') or selected.get('content-length','0')!='0' or 'content-type' in selected: return DENY
        else:
            if not isinstance(body,str) or len(body)>512 or selected.get('content-type')!='application/json': return DENY
            raw=base64.b64decode(body,validate=True)
            if base64.b64encode(raw).decode()!=body: return DENY
            if 'content-length' in selected and selected['content-length']!=str(len(raw)): return DENY
            value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_object)
            if not isinstance(value,dict) or set(value)!={'RestartPolicy'}: return DENY
            policy=value['RestartPolicy']
            if (not isinstance(policy,dict) or set(policy)!={'Name','MaximumRetryCount'}
                    or policy['Name']!='no' or type(policy['MaximumRetryCount']) is not int
                    or policy['MaximumRetryCount']!=0): return DENY
        return {'Allow':True,'Msg':'Selected fixture quiesce request allowed','Err':''}
    except (ValueError,TypeError,UnicodeError):
        return DENY
