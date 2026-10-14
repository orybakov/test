import asyncio
import io
from pathlib import Path
import httpx
from .config import Settings


async def synthesize(settings: Settings, speech: str, target: Path) -> bool:
    if settings.tts_provider != "qwen":
        return False
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(settings.tts_url, json={"text": speech, "voice": settings.tts_voice})
        r.raise_for_status()
        if not r.content.startswith(b"RIFF"):
            raise ValueError("TTS response was not WAV")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.content)
    return True


async def to_voice(wav: Path) -> Path | None:
    ogg = wav.with_suffix(".ogg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
            "-ac", "1", "-c:a", "libopus", "-b:a", "32k", str(ogg),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return None
    except OSError:
        return None
    return ogg


async def telegram_send(settings: Settings, speech: str, priority: str, wav: Path | None = None):
    if not (settings.telegram_token and settings.telegram_chat_id):
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_token}"
    icon = "🚨" if priority == "critical" else "🔔"
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(url + "/sendMessage", data={
            "chat_id": settings.telegram_chat_id, "text": f"{icon} {speech}"})
        if r.status_code >= 400:
            raise RuntimeError(f"Telegram sendMessage returned HTTP {r.status_code}")
        if wav and wav.is_file():
            audio = await to_voice(wav)
            if audio is not None:
                with audio.open("rb") as f:
                    res = await client.post(url + "/sendVoice", data={
                        "chat_id": settings.telegram_chat_id},
                        files={"voice": (audio.name, f, "audio/ogg")})
                if res.status_code >= 400:
                    raise RuntimeError(f"Telegram sendVoice returned HTTP {res.status_code}")
    return True
