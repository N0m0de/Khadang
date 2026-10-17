"""Safe API diagnostics and bounded retries; never persist error messages or chat text."""
import asyncio
from openai import RateLimitError, APIConnectionError, InternalServerError

BILLING_CODES={'credit_balance_exhausted','insufficient_quota','organization_spend_limit_exceeded',
               'project_spend_limit_exceeded','organization_usage_limit_exceeded','billing_hard_limit_reached'}

def describe(error,model=None):
    body=getattr(error,'body',None)
    detail=body.get('error',body) if isinstance(body,dict) else {}
    code=detail.get('code') if isinstance(detail,dict) else None
    kind=detail.get('type') if isinstance(detail,dict) else None
    if code=='credit_balance_exhausted':
        reason='billing'; message='OpenAI API credit balance is empty. Add credits in OpenAI billing; waiting or restarting will not restore access.'
    elif code in BILLING_CODES or kind=='insufficient_quota':
        reason='billing'; message='OpenAI API quota or spending limit reached. Check API billing and project/organization limits.'
    elif isinstance(error,RateLimitError):
        reason='rate_limit'; message='OpenAI temporarily rate-limited this request. Khadang tried a bounded retry; no reply was sent.'
    else:
        reason='api_error'; message='The AI provider could not complete this request. Check the configured model and provider connection.'
    return {'reason':reason,'message':message,'model':model,
            'code':code if code in BILLING_CODES|{'rate_limit_exceeded','slow_down'} else None,
            'exception_type':type(error).__name__}

async def completion(client,**kwargs):
    for attempt in range(2):
        try: return await client.chat.completions.create(**kwargs)
        except RateLimitError as error:
            if describe(error)['reason']=='billing' or attempt==1: raise
            response=getattr(error,'response',None)
            value=response.headers.get('retry-after','2') if response is not None else '2'
            try: delay=float(value)
            except (TypeError,ValueError): delay=2
            # Don't ignore a long server-requested wait or block the Telegram pipeline indefinitely.
            if delay>30: raise
            await asyncio.sleep(max(1,delay))
        except (APIConnectionError,InternalServerError):
            if attempt==1: raise
            await asyncio.sleep(2)
