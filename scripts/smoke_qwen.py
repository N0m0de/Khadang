"""Synthetic primary/fallback and dashboard integration; no external requests."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

temporary = Path(tempfile.mkdtemp())
os.environ.update(AI_PROVIDER="qwen_fallback", OPENROUTER_API_KEY="synthetic-router",
                  OPENAI_API_KEY="synthetic-openai", OWNER_USER_ID="111", TG_BOT_TOKEN="",
                  DB_PATH=str(temporary / "db.sqlite"), SECRETORY_CONFIG_FILE=str(temporary / ".env"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from openai import AuthenticationError, RateLimitError, InternalServerError, APIConnectionError
from secretary import db, llm, memory, reporting, text_routing as route, voice
from secretary.config import settings
from secretary.dashboard import auth, pages
from secretary.dashboard.app import create_app
from dotenv import dotenv_values


def response(text="hello.", finish="stop"):
    return NS(choices=[NS(finish_reason=finish, message=NS(content=text, refusal=None))])


async def main():
    assert settings.provider == "qwen_fallback" and settings.provider_key
    primary = AsyncMock(return_value=response())
    fallback = AsyncMock(return_value=response("fallback."))
    route.primary.chat.completions.create = primary
    llm.openai_client.chat.completions.create = fallback
    async def reply():
        return await llm.generate_reply(system_prompt="synthetic persona", history=[], user_message="hello")
    assert await reply() == "hello"
    fallback.assert_not_awaited()
    kwargs = primary.call_args.kwargs
    assert kwargs['model'] == 'qwen/qwen3.8-27b:free'
    assert kwargs['extra_body']['reasoning']['exclude'] and route.primary.max_retries == 0
    request = httpx.Request('POST', 'https://example.invalid')
    for status, cls in ((401, AuthenticationError), (429, RateLimitError), (503, InternalServerError)):
        primary.side_effect = cls('synthetic', response=httpx.Response(status, request=request), body={})
        fallback.reset_mock()
        assert await reply() == 'fallback'
        fallback.assert_awaited_once()
        assert fallback.call_args.kwargs['model'] == settings.openai_model
        assert fallback.call_args.kwargs['store'] is False
    primary.side_effect = APIConnectionError(request=request)
    assert await reply() == 'fallback'
    primary.side_effect = None
    for bad in (response(''), response('partial', 'length'), response('<think>unfinished'), response('Reply:')):
        primary.return_value = bad
        fallback.reset_mock()
        assert await reply() == 'fallback'
        fallback.assert_awaited_once()
    async def hang(**kwargs):
        await asyncio.Event().wait()
    primary.side_effect = hang
    with patch.object(route, 'PRIMARY_TIMEOUT', .01):
        assert await reply() == 'fallback'
    primary.side_effect = asyncio.CancelledError
    fallback.reset_mock()
    try:
        await reply()
        raise AssertionError('Cancellation swallowed')
    except asyncio.CancelledError:
        pass
    fallback.assert_not_awaited()
    primary.side_effect = RuntimeError('synthetic')
    fallback.side_effect = RuntimeError('synthetic')
    try:
        await reply()
        raise AssertionError('Both failures swallowed')
    except RuntimeError:
        pass
    fallback.side_effect = None
    primary.side_effect = None
    primary.return_value = response('not JSON')
    extractor = AsyncMock(return_value=response('{"memories": []}'))
    memory._openai_extractor.chat.completions.create = extractor
    assert json.loads(await memory._chat(memory.EXTRACTION_SYSTEM, 'synthetic', max_tokens=300)) == {'memories': []}
    extractor.assert_awaited_once()
    primary.return_value = response('{"memories": []}')
    extractor.reset_mock()
    await memory._chat(memory.EXTRACTION_SYSTEM, 'synthetic', max_tokens=300)
    extractor.assert_not_awaited()
    settings.qwen_scope = 'replies'
    primary.reset_mock()
    await memory._chat(memory.EXTRACTION_SYSTEM, 'synthetic', max_tokens=300)
    primary.assert_not_awaited()
    assert await reply() == '{"memories": []}'
    settings.qwen_scope = 'all'
    await db.init_db()
    await db.upsert_connection(conn_id='synthetic', owner_user_id=111, owner_chat_id=111,
                               can_reply=True, is_enabled=True, rights=None)
    end = reporting.datetime(2026, 10, 20, 12, tzinfo=reporting.TZ)
    await db.append_message(conn_id='synthetic', chat_id=222, role='user', content='synthetic hello',
                            tg_message_id=1, created_at=int(end.timestamp()) - 60)
    primary.return_value = response('{"summary": "synthetic report", "requests": []}')
    fallback.reset_mock()
    assert 'synthetic report' in await reporting.render_report(end)
    fallback.assert_not_awaited()
    primary.return_value = response('{"summary": []}')
    fallback.return_value = response('{"summary": "fallback report", "requests": []}')
    assert 'fallback report' in await reporting.render_report(end)
    fallback.assert_awaited_once()
    with patch.object(voice, '_openai_transcribe', new=AsyncMock(return_value='voice text')):
        assert await voice.transcribe(b'synthetic voice bytes') == 'voice text'
    app = create_app(NS(username=''), lambda: None, temporary / '.env')
    base = 'http://127.0.0.1:18763'
    token = await auth.create_login_token()
    pages._qwen_availability_cache = (settings.qwen_model, time.monotonic(), False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
        await client.post('/login', data={'token': token}, headers={'Origin': base})
        page = await client.get('/settings')
        assert 'Qwen first' in page.text and 'name="QWEN_SCOPE"' in page.text
        assert 'No Qwen endpoints' in page.text and 'paid OpenAI fallback' in page.text
        assert 'synthetic-router' not in page.text and 'synthetic-openai' not in page.text
        result = await client.post('/settings/config', headers={'Origin': base}, data={'QWEN_SCOPE': 'replies'})
        assert 'restart=1' in result.headers['location']
        assert dotenv_values(temporary / '.env')['QWEN_SCOPE'] == 'replies'
        await client.post('/settings/config', headers={'Origin': base}, data={'QWEN_MODEL': 'qwen/paid-model'})
        assert dotenv_values(temporary / '.env').get('QWEN_MODEL') != 'qwen/paid-model'
        settings.openrouter_api_key = ''
        result = await client.post('/settings/config', headers={'Origin': base}, data={'AI_PROVIDER': 'qwen_fallback'})
        assert 'Enter' in result.headers['location']
    await db.close_db()
    print('Qwen checks passed: primary, errors, empty/truncated/JSON failures, timeout, cancellation, both failures, scope, reports, voice, secure settings.')


asyncio.run(main())
