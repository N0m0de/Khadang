"""No network: distinguish empty credit from temporary throttling and never leak error bodies."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from openai import RateLimitError
from secretary import api_failures

def error(code,kind='rate_limit_error',wait='2'):
    response=httpx.Response(429,headers={'retry-after':wait},request=httpx.Request('POST','https://api.openai.com/v1/chat/completions'))
    return RateLimitError('PRIVATE TEXT AND ORGANIZATION DETAILS',response=response,body={'code':code,'type':kind,'message':'PRIVATE TEXT'})

async def main():
    billing=error('credit_balance_exhausted','insufficient_quota')
    detail=api_failures.describe(billing,'gpt-4.1')
    assert detail['reason']=='billing' and 'balance is empty' in detail['message']
    assert 'PRIVATE' not in json.dumps(detail)
    assert api_failures.describe(error('project_spend_limit_exceeded','insufficient_quota'))['reason']=='billing'
    calls=[]
    async def exhausted(**kwargs): calls.append(1); raise billing
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=exhausted)))
    try: await api_failures.completion(client,model='test',messages=[])
    except RateLimitError: pass
    else: raise AssertionError('Billing error swallowed')
    assert len(calls)==1
    calls.clear(); sleeps=[]
    async def temporary(**kwargs):
        calls.append(1)
        if len(calls)==1: raise error('rate_limit_exceeded')
        return 'ok'
    async def sleep(delay): sleeps.append(delay)
    api_failures.asyncio.sleep=sleep
    client.chat.completions.create=temporary
    assert await api_failures.completion(client,model='test',messages=[])=='ok'
    assert len(calls)==2 and sleeps==[2]
    calls.clear(); sleeps.clear()
    async def long_wait(**kwargs): calls.append(1); raise error('rate_limit_exceeded',wait='120')
    client.chat.completions.create=long_wait
    try: await api_failures.completion(client,model='test',messages=[])
    except RateLimitError: pass
    assert len(calls)==1 and not sleeps
    print('API limit checks passed: empty credits/limits distinguished, billing never retried, temporary throttling bounded, long waits respected, no private error text persisted.')

asyncio.run(main())
