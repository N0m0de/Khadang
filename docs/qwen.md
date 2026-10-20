# Free Qwen with automatic OpenAI fallback

The `qwen_fallback` provider tries `qwen/qwen3.8-27b:free` through
OpenRouter first, then uses your existing direct OpenAI API key and model if
Qwen errors, times out, refuses, returns empty or truncated text, or produces
invalid JSON for learning or reports. It does not send two Telegram replies.
If both providers fail, existing error notification/draft behavior applies.

1. Open Settings, then the technical model/credential section.
2. Enter your **OpenRouter API key** in its password field. Blank fields preserve
   saved keys; leave your OpenAI key and chosen models in place.
3. Choose **Qwen first → OpenAI fallback** as the AI provider.
4. Leave the free Qwen model ID at `qwen/qwen3.8-27b:free`. Choose all text
   operations (replies, memory learning, summaries, and reports) or replies only.
5. Save and restart from the dashboard.

Equivalent environment settings:

```dotenv
AI_PROVIDER=qwen_fallback
QWEN_MODEL=qwen/qwen3.8-27b:free
QWEN_SCOPE=all
```

Supply `OPENROUTER_API_KEY` and `OPENAI_API_KEY` privately, never in Git.
The dashboard rejects activation without both keys. `QWEN_SCOPE=replies`
keeps background learning and reports on OpenAI. Voice transcription and the
separately authorized exported-chat analysis continue to use OpenAI in either mode.

Qwen requests have a 45-second overall deadline, no SDK retries, and no paid
OpenRouter model substitution. A failure starts one direct OpenAI request with
a 65-second overall deadline; cancellation does not trigger fallback. Subsequent
operations try Qwen again. Fallback uses the configured `OPENAI_MODEL` for
replies/reports and `OPENAI_EXTRACTOR_MODEL` for learning. No transcript or API
error body is added to logs; a fallback log contains purpose and exception class.

Free models have rate limits and availability constraints, so this reduces
OpenAI usage without guaranteeing zero cost. Check [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits)
and the [model page](https://openrouter.ai/qwen/qwen3.8-27b:free) for current terms.
The model page can remain online when no free endpoints are available. Settings
shows a warning in Qwen mode when its endpoint catalogue is empty; all operations
will then use paid OpenAI fallback until a free endpoint returns.
In this mode private conversation context is processed by OpenRouter and the
selected Qwen provider, subject to their policies and your OpenRouter privacy
settings. OpenAI fallback requests keep `store=false`.
