"""Private, content-free provenance of successful text generations."""
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db
from .config import settings


async def record(purpose, provider, requested, response=None, fallback_reason=None):
    # Response model is a provider identifier, never arbitrary response content.
    actual = getattr(response, 'model', None)
    if not isinstance(actual, str) or len(actual) > 160 or not all(
            c.isalnum() or c in '/:._-@' for c in actual):
        actual = requested
    value = {'at': int(time.time()), 'provider': provider, 'model': actual,
             'requested_model': requested, 'fallback_reason': fallback_reason}
    try:
        await db.set_state('model_last_' + purpose, json.dumps(value))
    except Exception:
        # Diagnostics must never cause a failed reply or retry a completed generation.
        pass


async def describe():
    if settings.provider == 'qwen_fallback':
        lines = ['AI mode: Qwen first → OpenAI fallback',
                 'Primary: ' + settings.qwen_model,
                 'OpenAI reply/report fallback: ' + settings.openai_model,
                 'OpenAI learning fallback: ' + settings.openai_extractor_model,
                 'Qwen scope: ' + ('all text operations' if settings.qwen_scope == 'all' else 'replies only')]
    else:
        lines = ['AI provider: ' + settings.provider, 'Configured reply model: ' + settings.reply_model]
    lines += ['OpenRouter key: ' + ('saved' if settings.openrouter_api_key else 'missing'),
              'OpenAI key: ' + ('saved' if settings.openai_api_key else 'missing')]
    found = False
    for purpose, label in (('reply', 'reply'), ('memory', 'learning/summary'), ('report', 'report')):
        try:
            value = json.loads(await db.get_state('model_last_' + purpose) or 'null')
            if not value:
                continue
            stamp = datetime.fromtimestamp(value['at'], ZoneInfo('Asia/Tehran')).strftime('%Y-%m-%d %H:%M:%S')
            lines += ['', f'Latest generated {label}: {value["provider"]} / {value["model"]}',
                      stamp + ' Tehran time']
            if value.get('fallback_reason'):
                lines.append('Qwen → OpenAI fallback: ' + value['fallback_reason'])
            found = True
        except (ValueError, TypeError, KeyError):
            continue
    if not found:
        lines += ['', 'No generation recorded since model tracking was installed.']
    lines += ['', 'Generation records show which model produced text, not a Telegram delivery receipt.',
              'This command is private to your direct bot chat and makes no AI request.']
    return '\n'.join(lines)
