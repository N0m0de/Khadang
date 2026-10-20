"""Offline provenance persistence and owner/private/business-chat isolation checks."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

temp = Path(tempfile.mkdtemp())
os.environ.update(SECRETORY_CONFIG_FILE=str(temp / '.env'), DB_PATH=str(temp / 'db.sqlite'),
                  OWNER_USER_ID='111', AI_PROVIDER='qwen_fallback',
                  OPENROUTER_API_KEY='synthetic-router-key', OPENAI_API_KEY='synthetic-openai-key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secretary import db, commands, llm, model_status, text_routing as route
from secretary.config import settings


def response(text, model):
    return NS(model=model, choices=[NS(finish_reason='stop', message=NS(content=text, refusal=None))])


async def main():
    await db.init_db()
    assert 'No generation recorded' in await model_status.describe()
    route.primary.chat.completions.create = AsyncMock(return_value=response('hello', settings.qwen_model))
    fallback = AsyncMock(return_value=response('fallback', 'gpt-4.1-2025-04-14'))
    llm.openai_client.chat.completions.create = fallback
    await llm.generate_reply(system_prompt='synthetic', history=[], user_message='synthetic input')
    record = json.loads(await db.get_state('model_last_reply'))
    assert record['provider'] == 'openrouter' and record['fallback_reason'] is None
    fallback.assert_not_awaited()
    route.primary.chat.completions.create.side_effect = RuntimeError('PRIVATE ERROR BODY')
    await llm.generate_reply(system_prompt='synthetic', history=[], user_message='synthetic input')
    record = json.loads(await db.get_state('model_last_reply'))
    assert record['provider'] == 'openai' and record['model'] == 'gpt-4.1-2025-04-14'
    assert record['fallback_reason'] == 'RuntimeError' and 'PRIVATE' not in json.dumps(record)
    await db.close_db()
    await db.init_db()
    assert 'RuntimeError' in await model_status.describe()  # Survives process/database reopening.
    settings.ai_provider = 'openai'
    await llm.generate_reply(system_prompt='synthetic', history=[], user_message='synthetic input')
    record = json.loads(await db.get_state('model_last_reply'))
    assert record['fallback_reason'] is None and record['provider'] == 'openai'
    sent = AsyncMock()
    def update(user=111, chat=111, kind='private', business=None, regular=True):
        message = NS(reply_text=sent, business_connection_id=business)
        return NS(effective_user=NS(id=user), effective_chat=NS(id=chat, type=kind),
                  message=message if regular else None, effective_message=message)
    await commands.on_model(update(), None)
    sent.assert_awaited_once()
    text = sent.call_args.args[0]
    assert 'gpt-4.1-2025-04-14' in text and 'AI provider: openai' in text
    assert 'synthetic-openai-key' not in text and 'synthetic input' not in text
    sent.reset_mock()
    for rejected in (update(user=999), update(chat=-1, kind='group'), update(chat=222),
                     update(business='business'), update(regular=False),
                     update(kind='supergroup')):
        await commands.on_model(rejected, None)
    sent.assert_not_awaited()
    route.primary.chat.completions.create.reset_mock()
    fallback.reset_mock()
    await commands.on_model(update(), None)
    route.primary.chat.completions.create.assert_not_awaited()
    fallback.assert_not_awaited()
    await db.close_db()
    print('Model status checks passed: actual model, fallback reason, direct mode, persistence, no content/keys, owner-only private command, no business/group replies or AI calls.')


asyncio.run(main())
