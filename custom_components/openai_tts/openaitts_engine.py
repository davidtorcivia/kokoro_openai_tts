"""
TTS Engine for OpenAI TTS.
"""
import logging
import aiohttp
from asyncio import CancelledError

from homeassistant.exceptions import HomeAssistantError

from .const import KOKORO_MODEL # To identify Kokoro engine for chunk_size

_LOGGER = logging.getLogger(__name__)

class OpenAITTSEngine:
    def __init__(self, session: aiohttp.ClientSession, api_key: str | None, voice: str, model: str, speed: float, url: str, chunk_size: int | None = None):
        self._session = session
        self._api_key = api_key
        self._voice = voice
        self._model = model
        self._speed = speed
        self._url = url
        self._chunk_size = chunk_size

    async def get_tts(self, text: str, speed: float | None = None, instructions: str | None = None, voice: str | None = None):
        """Asynchronous TTS request that streams audio chunks."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # Kokoro FastAPI is OpenAI-compatible and expects the 'model' field too
        data = {
            "model": self._model,
            "input": text,
            "voice": voice if voice is not None else self._voice,
            "response_format": "mp3",
            "speed": speed if speed is not None else self._speed,
        }
        if self._model == KOKORO_MODEL and self._chunk_size is not None:
            data["chunk_size"] = self._chunk_size
        if instructions:
            data["instructions"] = instructions

        _LOGGER.debug("Requesting TTS from %s: %s", self._url, data)

        try:
            async with self._session.post(
                self._url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_any():
                    if chunk:
                        yield chunk
        except CancelledError:
            _LOGGER.debug("TTS request cancelled")
            raise
        except aiohttp.ClientResponseError as net_err:
            _LOGGER.error("Network error in get_tts: %s, status: %s", net_err.message, net_err.status)
            raise HomeAssistantError(f"Network error occurred while fetching TTS audio: {net_err.message}") from net_err
        except aiohttp.ClientError as net_err:
            _LOGGER.error("Network error in get_tts: %s", net_err)
            raise HomeAssistantError(f"Network error occurred while fetching TTS audio: {net_err}") from net_err
        except Exception as exc:
            _LOGGER.exception("Unknown error in get_tts")
            raise HomeAssistantError("An unknown error occurred while fetching TTS audio") from exc

    @staticmethod
    def get_supported_langs() -> list:
        return [
            "af", "ar", "hy", "az", "be", "bs", "bg", "ca", "zh", "hr", "cs", "da", "nl", "en",
            "et", "fi", "fr", "gl", "de", "el", "he", "hi", "hu", "is", "id", "it", "ja", "kn",
            "kk", "ko", "lv", "lt", "mk", "ms", "mr", "mi", "ne", "no", "fa", "pl", "pt", "ro",
            "ru", "sr", "sk", "sl", "es", "sw", "sv", "tl", "ta", "th", "tr", "uk", "ur", "vi", "cy"
        ]
