from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_key: str
    db_path: Path
    audio_dir: Path
    telegram_token: str = ""
    telegram_chat_id: str = ""
    tts_provider: str = "browser"
    tts_url: str = "http://tts:7801/synthesize"
    tts_voice: str = "Ryan"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    worker_interval: float = 3.0
    digest_interval_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("SENTINEL_API_KEY", "")
        if len(api_key) < 24:
            raise RuntimeError("SENTINEL_API_KEY must be set (24+ characters). Run ./start.sh")
        provider = os.environ.get("TTS_PROVIDER", "browser").lower()
        if provider not in {"browser", "qwen"}:
            raise RuntimeError("TTS_PROVIDER must be browser or qwen")
        return cls(
            api_key=api_key,
            db_path=Path(os.environ.get("DB_PATH", "/data/sentinel.sqlite3")),
            audio_dir=Path(os.environ.get("AUDIO_DIR", "/data/audio")),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            tts_provider=provider,
            tts_url=os.environ.get("TTS_URL", "http://tts:7801/synthesize"),
            tts_voice=os.environ.get("TTS_VOICE", "Ryan"),
            llm_base_url=os.environ.get("LLM_BASE_URL", "").rstrip("/"),
            llm_model=os.environ.get("LLM_MODEL", ""),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            worker_interval=float(os.environ.get("WORKER_INTERVAL", "3")),
            digest_interval_seconds=int(os.environ.get("DIGEST_INTERVAL_SECONDS", "3600")),
        )
