"""
TTS Engine for OpenAI TTS.
"""
import json
import logging
import aiohttp
from asyncio import CancelledError

from homeassistant.exceptions import HomeAssistantError

from .const import KOKORO_MODEL # To identify Kokoro engine for chunk_size

_LOGGER = logging.getLogger(__name__)

class OpenAITTSEngine:
    def __init__(self, api_key: str, voice: str, model: str, speed: float, url: str, chunk_size: int | None = None):
        self._api_key = api_key
        self._voice = voice
        self._model = model
        self._speed = speed
        self._url = url
        self._session = aiohttp.ClientSession()
        self._chunk_size = chunk_size # Store chunk_size

    async def get_tts(self, text: str, speed: float = None, instructions: str = None, voice: str = None):
        """Asynchronous TTS request that streams audio chunks."""
        current_speed = speed if speed is not None else self._speed
        current_voice = voice if voice is not None else self._voice
        # Note: self._model is the configured model, used for engine-specific logic like chunk_size.
        # The 'model' in the 'data' payload is what's sent to the API.
        # For Kokoro, self._model will be KOKORO_MODEL, but data["model"] will also be KOKORO_MODEL.
        # For OpenAI, self._model is e.g. "tts-1", and data["model"] is also "tts-1".

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        if self._model == KOKORO_MODEL:
            # Payload for Kokoro - does not include 'model' key
            data = {
                "input": text,
                "voice": current_voice,
                "response_format": "mp3",
                "speed": current_speed
            }
            if self._chunk_size is not None:
                data["chunk_size"] = self._chunk_size
                _LOGGER.debug("Using chunk_size %s for Kokoro request", self._chunk_size)
            # Note: Instructions are not typically part of the linked Kokoro-FastAPI server's basic endpoint.
            # If your Kokoro server handles 'instructions', it would need to be added here conditionally too.
        else:
            # Payload for OpenAI or other compatible engines
            data = {
                "model": self._model,
                "input": text,
                "voice": current_voice,
                "response_format": "mp3",
                "speed": current_speed
            }
            # Handling for instructions - ensure this model check is appropriate for your setup
            # This 'gpt-4o-mini-tts' might be a custom name for your OpenAI compatible proxy
            if instructions is not None and self._model == "gpt-4o-mini-tts": # This specific model check might need to be more generic if instructions are supported by other openai models
                data["instructions"] = instructions

        _LOGGER.debug("Requesting TTS from URL: %s", self._url)
        _LOGGER.debug("Request Headers: %s", headers)
        _LOGGER.debug("Request Payload: %s", data)

        try:
            async with self._session.post(
                self._url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30) # Overall timeout for the request
            ) as response:
                response.raise_for_status()  # Raise an exception for bad status codes
                async for chunk in response.content.iter_any():
                    if chunk:
                        yield chunk
        except CancelledError:
            _LOGGER.debug("TTS request cancelled")
            raise
        except aiohttp.ClientResponseError as net_err:
            # More specific error for HTTP issues if needed, e.g. response.status
            _LOGGER.error("Network error in get_tts: %s, status: %s", net_err.message, net_err.status)
            raise HomeAssistantError(f"Network error occurred while fetching TTS audio: {net_err.message}") from net_err
        except aiohttp.ClientError as net_err:
            _LOGGER.error("Network error in get_tts: %s", net_err)
            raise HomeAssistantError(f"Network error occurred while fetching TTS audio: {net_err}") from net_err
        except Exception as exc:
            _LOGGER.exception("Unknown error in get_tts")
            raise HomeAssistantError("An unknown error occurred while fetching TTS audio") from exc

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def get_supported_langs() -> list:
        return [
            "af", "ar", "hy", "az", "be", "bs", "bg", "ca", "zh", "hr", "cs", "da", "nl", "en",
            "et", "fi", "fr", "gl", "de", "el", "he", "hi", "hu", "is", "id", "it", "ja", "kn",
            "kk", "ko", "lv", "lt", "mk", "ms", "mr", "mi", "ne", "no", "fa", "pl", "pt", "ro",
            "ru", "sr", "sk", "sl", "es", "sw", "sv", "tl", "ta", "th", "tr", "uk", "ur", "vi", "cy"
        ]
