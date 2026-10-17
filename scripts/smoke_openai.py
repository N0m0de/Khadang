"""Offline direct OpenAI request, voice conversion and configuration regression checks."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

temp = Path(tempfile.mkdtemp())
os.environ.update(AI_PROVIDER="openai", OPENAI_API_KEY="test-openai-key", OPENROUTER_API_KEY="unused-router-key",
                  ANTHROPIC_API_KEY="", TG_BOT_TOKEN="", OWNER_USER_ID="0", DB_PATH=str(temp / "test.db"),
                  PROMPTS_DIR=str(temp / "prompts"), SECRETORY_CONFIG_FILE=str(temp / ".env"))
os.environ.pop("SECRETORY_PRIVATE_AUTH", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import imageio_ffmpeg
from dotenv import dotenv_values
from secretary import db, llm, memory, voice, handlers
from secretary.config import settings
from secretary.dashboard import auth, pages
from secretary.dashboard.app import create_app

calls = []
async def reply(**kwargs):
    calls.append(kwargs)
    return NS(choices=[NS(message=NS(content="hello."))])
async def extract(**kwargs):
    calls.append(kwargs)
    return NS(choices=[NS(message=NS(content='{"memories": []}'))])
async def transcribe(**kwargs):
    calls.append(kwargs)
    assert kwargs["file"][0] == "voice.wav" and kwargs["file"][1].startswith(b"RIFF")
    assert len(kwargs["file"][1]) < 25 * 1024 * 1024
    return NS(text="sample voice transcript")

async def main():
    assert settings.provider == "openai" and settings.provider_key == "test-openai-key"
    assert str(llm.openai_client.base_url) == "https://api.openai.com/v1/"
    assert str(memory._openai_extractor.base_url) == "https://api.openai.com/v1/"
    llm.openai_client.chat.completions.create = reply
    memory._openai_extractor.chat.completions.create = extract
    llm.openai_client.audio.transcriptions.create = transcribe
    assert await llm.generate_reply(system_prompt="persona", history=[], user_message="hello", summary="context") == "hello"
    assert calls[-1]["model"] == settings.openai_model and calls[-1]["store"] is False
    assert "extra_body" not in calls[-1] and "max_tokens" not in calls[-1]
    assert len(calls[-1]["messages"]) == 3
    assert await memory._chat("extract", "conversation", max_tokens=100) == '{"memories": []}'
    assert calls[-1]["model"] == settings.openai_extractor_model and calls[-1]["store"] is False
    process = await asyncio.create_subprocess_exec(imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1", "-c:a", "libopus", "-f", "ogg", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    ogg, _ = await process.communicate()
    assert process.returncode == 0
    assert await voice.transcribe(ogg) == "sample voice transcript"
    assert calls[-1]["model"] == settings.openai_transcription_model
    assert await voice.transcribe(b"invalid") is None
    assert await voice.transcribe(b"") is None
    assert await voice.transcribe(b"x" * (voice.MAX_BYTES + 1)) is None
    assert await pages._credit() is None and await pages._model_ids() is None
    await db.init_db()
    assert await handlers._voice_enabled()
    app = create_app(NS(username=""), lambda: None, temp / ".env")
    token = await auth.create_login_token()
    base = "http://127.0.0.1:18763"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
        assert (await client.post("/login", data={"token": token}, headers={"Origin": base})).status_code == 303
        page = await client.get("/settings")
        assert page.status_code == 200 and 'name="OPENAI_API_KEY"' in page.text and 'name="OPENAI_MODEL"' in page.text
        assert "test-openai-key" not in page.text
        result = await client.post("/settings/config", headers={"Origin": base}, data={"AI_PROVIDER": "openai", "OPENAI_MODEL": "custom-model", "OPENAI_EXTRACTOR_MODEL": "custom-memory"})
        assert result.status_code == 303 and "restart=1" in result.headers["location"]
        assert dotenv_values(temp / ".env")["OPENAI_MODEL"] == "custom-model"
        assert (await client.post("/settings/config", headers={"Origin": base}, data={"AI_PROVIDER": "evil"})).status_code == 303
        assert dotenv_values(temp / ".env")["OPENAI_MODEL"] == "custom-model"
    await db.close_db()
    await llm.openai_client.close()
    await memory._openai_extractor.close()
    print("OpenAI checks passed: direct endpoint, reply/history, memory, model settings, key masking, native audio conversion/transcription and invalid-audio guards.")

asyncio.run(main())
