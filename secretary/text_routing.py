"""Qwen first, direct OpenAI fallback. Never log prompts, output, or API errors."""
import asyncio
import logging
import re
from collections.abc import Callable

from openai import AsyncOpenAI

from .config import settings

log = logging.getLogger(__name__)
PRIMARY_TIMEOUT = 45
FALLBACK_TIMEOUT = 65
primary = AsyncOpenAI(api_key=settings.openrouter_api_key or "unused",
                      base_url="https://openrouter.ai/api/v1", timeout=40, max_retries=0)


def enabled(purpose: str) -> bool:
    return settings.provider == "qwen_fallback" and (
        purpose == "reply" or settings.qwen_scope == "all")


def usable(response, transform, validate) -> str:
    choice = response.choices[0]
    if choice.finish_reason in ("length", "content_filter", "tool_calls"):
        raise ValueError("Incomplete text response")
    if getattr(choice.message, "refusal", None):
        raise ValueError("Text response unavailable")
    text = choice.message.content or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    if "<think>" in text.lower() or "</think>" in text.lower():
        raise ValueError("Incomplete reasoning block")
    text = transform(text) if transform else text
    if not text.strip():
        raise ValueError("Empty text response")
    if validate:
        validate(text)
    return text


async def complete(*, messages, purpose: str, fallback_client, fallback_model: str,
                   max_tokens: int, transform: Callable | None = None,
                   validate: Callable | None = None, json_output: bool = False) -> str:
    """Generate once on Qwen; any provider/format failure falls back once.

    Cancellation propagates without starting a second request. Provider fallback
    happens before any Telegram send or memory/database mutation.
    """
    from .model_status import record
    fallback_reason = None
    if enabled(purpose):
        try:
            if not settings.openrouter_api_key:
                raise ValueError("Missing primary credential")
            if not settings.qwen_model.startswith("qwen/") or not settings.qwen_model.endswith(":free"):
                raise ValueError("A free Qwen model is required")
            async with asyncio.timeout(PRIMARY_TIMEOUT):
                response = await primary.chat.completions.create(
                    model=settings.qwen_model, messages=messages, max_tokens=max_tokens,
                    temperature=0.4,
                    extra_body={"reasoning": {"enabled": False, "exclude": True}},
                    **({"response_format": {"type": "json_object"}} if json_output else {}))
                text = usable(response, transform, validate)
        except Exception as error:
            fallback_reason = type(error).__name__
            status = getattr(error, 'status_code', None)
            if isinstance(status, int):
                fallback_reason += f' (HTTP {status})'
            # Exception class only: provider error bodies can echo private input.
            log.warning("Qwen fallback purpose=%s reason=%s", purpose, type(error).__name__)
        else:
            await record(purpose, 'openrouter', settings.qwen_model, response)
            return text
    if not settings.openai_api_key:
        raise ValueError("OpenAI fallback credential is missing")
    async with asyncio.timeout(FALLBACK_TIMEOUT):
        response = await fallback_client.chat.completions.create(
            model=fallback_model, messages=messages, max_completion_tokens=max_tokens,
            store=False, **({"response_format": {"type": "json_object"}} if json_output else {}))
        text = usable(response, transform, validate)
    await record(purpose, 'openai', fallback_model, response, fallback_reason)
    return text
