import asyncio
import logging
import time
from .classifier import refine_auto_event
from .config import Settings
from .delivery import synthesize, telegram_send
from .store import Store

log = logging.getLogger("voice-sentinel")


class Engine:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self._lock = asyncio.Lock()
        self._last_digest = time.monotonic()

    async def run_once(self):
        async with self._lock:
            for event in self.store.pending():
                await self._deliver(event)
            if time.monotonic() - self._last_digest >= self.settings.digest_interval_seconds:
                await self.flush_digest()
                self._last_digest = time.monotonic()

    async def _deliver(self, event):
        event_id = event["id"]
        priority, speech = event["priority"], event["speech"]
        if event["requested_level"] == "auto":
            priority, speech = await refine_auto_event(self.settings, event["source"],
                          event["title"], event["message"], priority)
        if priority in {"normal", "silent"}:
            self.store.update(event_id, priority=priority, speech=speech,
                              status="digest" if priority == "normal" else "silent",
                              processed_at=int(time.time()))
            return
        # Store final text first; failure to deliver must not erase the event.
        self.store.update(event_id, priority=priority, speech=speech, status="processing")
        path = self.settings.audio_dir / f"{event_id}.wav"
        audio = None
        error = ""
        try:
            if await synthesize(self.settings, speech, path):
                audio = path
        except Exception as exc:
            error = f"TTS failed: {type(exc).__name__}: {exc}"[:300]
            log.warning("event %s speech fallback: %s", event_id, error)
        try:
            await telegram_send(self.settings, speech, priority, audio)
        except Exception as exc:
            error += f" Telegram failed: {type(exc).__name__}"
            log.warning("event %s Telegram delivery failed (%s)", event_id, type(exc).__name__)
        self.store.update(event_id, status="ready", audio_file=audio.name if audio else None,
                          error=error or None, processed_at=int(time.time()))

    async def flush_digest(self) -> int:
        items = self.store.digest_items()
        if not items:
            return 0
        lines = [f"{i['source']}: {i['title']}" for i in items[:12]]
        summary = f"За период накопилось {len(items)} событий. " + "; ".join(lines)
        # Create a real event: both web playback and Telegram receive one summary.
        event, _ = self.store.insert(
            "Sentinel", None, "Дайджест событий", summary[:1000],
            "important", "important", summary[:320])
        self.store.digest_mark([i["id"] for i in items])
        await self._deliver(event)
        return len(items)

    async def loop(self):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop failed; will retry")
            await asyncio.sleep(self.settings.worker_interval)
