"""
Setting up TTS entity.
"""
from __future__ import annotations
import logging
import os
import re
import subprocess
import tempfile
import time
from asyncio import CancelledError
from collections.abc import AsyncGenerator, AsyncIterable
from functools import partial

from homeassistant.components.tts import TextToSpeechEntity, TTSAudioRequest, TTSAudioResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import MaxLengthExceeded
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import generate_entity_id
from .const import (
    CONF_API_KEY,
    CONF_MODEL,
    CONF_SPEED,
    CONF_VOICE,
    CONF_INSTRUCTIONS,
    CONF_URL,
    DOMAIN,
    UNIQUE_ID,
    CONF_CHIME_ENABLE,
    CONF_CHIME_SOUND,
    CONF_NORMALIZE_AUDIO,
    CONF_TTS_ENGINE,
    OPENAI_ENGINE,
    KOKORO_FASTAPI_ENGINE,
    CONF_KOKORO_URL,
    CONF_KOKORO_CHUNK_SIZE,
    DEFAULT_KOKORO_CHUNK_SIZE,
)
from .openaitts_engine import OpenAITTSEngine

_LOGGER = logging.getLogger(__name__)

# A sentence ends at terminal punctuation (plus any closing quote or bracket) followed by whitespace, or at a newline.
_SENTENCE_END = re.compile(r"""[.!?…]["')\]]*\s+|\n+""")
# Shorter pieces ("Mr.", "Oh.") are merged into the following sentence so each request has enough text for natural prosody.
MIN_SENTENCE_CHARS = 20


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Split the complete sentences off the front of `buffer`; return them and the unfinished remainder."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(buffer):
        piece = buffer[start:match.end()].strip()
        if len(piece) >= MIN_SENTENCE_CHARS:
            sentences.append(piece)
            start = match.end()
    return sentences, buffer[start:]


def id3_length(head: bytes) -> int:
    """Byte length of the ID3v2 tag at the start of `head` (at least 10 bytes), or 0 if there is none."""
    if head[:3] != b"ID3":
        return 0
    size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
    return 10 + size + (10 if head[5] & 0x10 else 0)


async def strip_id3(chunks: AsyncIterable[bytes]) -> AsyncGenerator[bytes]:
    """Drop the leading ID3v2 tag, which decoders reject when it appears mid-stream between concatenated clips."""
    head = b""
    skip: int | None = None
    async for chunk in chunks:
        if skip is None:
            head += chunk
            if len(head) < 10:
                continue
            skip, chunk = id3_length(head), head
        if skip:
            dropped = min(skip, len(chunk))
            chunk, skip = chunk[dropped:], skip - dropped
        if chunk:
            yield chunk
    if skip is None and head:
        yield head


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    engine_type = config_entry.data.get(CONF_TTS_ENGINE, OPENAI_ENGINE)
    api_key = config_entry.data.get(CONF_API_KEY) # Will be None if not provided

    if engine_type == KOKORO_FASTAPI_ENGINE:
        api_url = config_entry.data.get(CONF_KOKORO_URL)
    else: # OpenAI or compatible
        api_url = config_entry.data.get(CONF_URL)

    if not api_url:
        _LOGGER.error(
            "TTS API URL is not configured for engine type '%s'. Cannot setup OpenAI TTS.",
            engine_type
        )
        return

    kokoro_chunk_size = None
    if engine_type == KOKORO_FASTAPI_ENGINE:
        kokoro_chunk_size = config_entry.options.get(
            CONF_KOKORO_CHUNK_SIZE,
            config_entry.data.get(CONF_KOKORO_CHUNK_SIZE, DEFAULT_KOKORO_CHUNK_SIZE)
        )

    engine = OpenAITTSEngine(
        session=async_get_clientsession(hass),
        api_key=api_key,
        voice=config_entry.data[CONF_VOICE],
        # The options flow offers a model choice for OpenAI; Kokoro's model is fixed in data.
        model=config_entry.options.get(CONF_MODEL, config_entry.data[CONF_MODEL]),
        speed=config_entry.data.get(CONF_SPEED, 1.0),
        url=api_url,
        chunk_size=kokoro_chunk_size,
    )

    async_add_entities([KokoroOpenAITTSEntity(hass, config_entry, engine)])


class KokoroOpenAITTSEntity(TextToSpeechEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: ConfigEntry, engine: OpenAITTSEngine) -> None:
        super().__init__()
        self.hass = hass
        self._engine = engine
        self._config = config
        self._attr_unique_id = config.data.get(UNIQUE_ID)
        if not self._attr_unique_id:
            # Fallback unique ID using URL and model if specific UNIQUE_ID isn't set
            url_part = config.data.get(CONF_URL, "unknown_url")
            model_part = config.data.get(CONF_MODEL, "unknown_model")
            self._attr_unique_id = f"{url_part}_{model_part}"

        base_name = self._config.data.get(CONF_MODEL, "openai_tts").replace("-", "_").lower()
        self.entity_id = generate_entity_id(
            "tts.{}",
            f"{DOMAIN}_{base_name}",
            hass=hass
        )

    @property
    def default_language(self) -> str:
        return "en"

    @property
    def supported_options(self) -> list:
        return ["instructions", "chime", "chime_sound"]

    @property
    def supported_languages(self) -> list:
        return self._engine.get_supported_langs()

    @property
    def device_info(self) -> dict:
        engine_type = self._config.data.get(CONF_TTS_ENGINE, OPENAI_ENGINE)
        manufacturer = "OpenAI"
        model_identifier = self._config.data.get(CONF_MODEL, "Generic TTS")

        if engine_type == KOKORO_FASTAPI_ENGINE:
            manufacturer = "Kokoro FastAPI"
            model_identifier = f"Kokoro ({model_identifier})"

        return {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": self.name,
            "manufacturer": manufacturer,
            "model": model_identifier,
            "sw_version": "1.0",
        }

    @property
    def name(self) -> str:
        if self._config.title:
            return self._config.title

        engine_type_display = "OpenAI"
        if self._config.data.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
            engine_type_display = "Kokoro FastAPI"
        model_name = self._config.data.get(CONF_MODEL, "TTS")
        return f"{engine_type_display} {model_name}"

    def _setting(self, key: str, default=None):
        """A config value, with options overriding the initial setup data."""
        return self._config.options.get(key, self._config.data.get(key, default))

    def _request_settings(self, options: dict) -> dict:
        """Voice, speed and instructions for one request; a service call's instructions override the configured ones."""
        return {
            "voice": self._setting(CONF_VOICE),
            "speed": self._setting(CONF_SPEED, 1.0),
            "instructions": options.get(CONF_INSTRUCTIONS, self._setting(CONF_INSTRUCTIONS)),
        }

    async def async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse:
        """Speak each sentence as soon as the incoming text completes it, so playback starts before the full reply exists."""
        if request.options.get(CONF_CHIME_ENABLE, self._setting(CONF_CHIME_ENABLE, False)) or self._setting(CONF_NORMALIZE_AUDIO, False):
            # The chime and loudness passes run ffmpeg over the whole clip, so they take the non-streaming path.
            return await super().async_stream_tts_audio(request)

        settings = self._request_settings(request.options)

        async def speak(text: str) -> AsyncGenerator[bytes]:
            _LOGGER.debug("Streaming TTS for sentence: '%s'", text[:50])
            async for chunk in strip_id3(self._engine.get_tts(text=text, **settings)):
                yield chunk

        async def data_gen() -> AsyncGenerator[bytes]:
            buffer = ""
            async for delta in request.message_gen:
                buffer += delta
                sentences, buffer = split_sentences(buffer)
                for sentence in sentences:
                    async for chunk in speak(sentence):
                        yield chunk
            if buffer.strip():
                async for chunk in speak(buffer.strip()):
                    yield chunk

        return TTSAudioResponse("mp3", data_gen())

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict | None = None
    ) -> tuple[str | None, bytes | None]:
        """Render the whole message to one MP3, adding the chime and loudness normalisation when enabled."""
        overall_start = time.monotonic()
        options = options or {}
        _LOGGER.debug("async_get_tts_audio called with message (first 50 chars): '%s', lang: %s, options: %s", message[:50], language, options)

        try:
            if len(message) > 4096:
                raise MaxLengthExceeded(f"Message length {len(message)} exceeds maximum allowed 4096 characters for non-streaming TTS.")

            api_start = time.monotonic()
            audio_chunks = []
            async for chunk in self._engine.get_tts(text=message, **self._request_settings(options)):
                audio_chunks.append(chunk)
            audio_content = b"".join(audio_chunks)

            if not audio_content:
                _LOGGER.error("TTS API returned no audio content (non-streaming path).")
                return "mp3", None

            _LOGGER.debug("TTS API call (non-streaming) completed in %.2f ms, received %d bytes", (time.monotonic() - api_start) * 1000, len(audio_content))

            chime_enabled = options.get(CONF_CHIME_ENABLE, self._setting(CONF_CHIME_ENABLE, False))
            normalize_audio = self._setting(CONF_NORMALIZE_AUDIO, False)

            if chime_enabled or normalize_audio:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tts_file:
                    tts_file.write(audio_content)
                    tts_input_path = tts_file.name

                processed_output_path = ""

                try:
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out_file:
                        processed_output_path = out_file.name

                    ffmpeg_cmd_list = ["ffmpeg", "-y"]

                    if chime_enabled:
                        chime_file_name = options.get(CONF_CHIME_SOUND, self._setting(CONF_CHIME_SOUND, "threetone.mp3"))
                        if not chime_file_name.lower().endswith('.mp3'):
                            chime_file_name = f"{chime_file_name}.mp3"
                        chime_file_path = os.path.join(os.path.dirname(__file__), "chime", chime_file_name)

                        if not os.path.exists(chime_file_path):
                            _LOGGER.error("Chime file not found at %s. Skipping chime.", chime_file_path)
                            chime_enabled = False
                        else:
                            ffmpeg_cmd_list.extend(["-i", chime_file_path]) # Input 0 (chime)

                    ffmpeg_cmd_list.extend(["-i", tts_input_path]) # Input 1 (or 0 if no chime)

                    filter_complex_parts = []
                    input_label_tts = "[1:a]" if chime_enabled else "[0:a]"

                    if normalize_audio:
                        filter_complex_parts.append(f"{input_label_tts}loudnorm=I=-16:TP=-1:LRA=5[norm_tts]")
                        input_label_tts = "[norm_tts]"

                    if chime_enabled:
                        filter_complex_parts.append(f"[0:a]{input_label_tts}concat=n=2:v=0:a=1[out]")
                    elif normalize_audio:
                        filter_complex_parts.append(f"{input_label_tts}acopy[out]")

                    if filter_complex_parts:
                        ffmpeg_cmd_list.extend(["-filter_complex", ";".join(filter_complex_parts), "-map", "[out]"])

                    ffmpeg_cmd_list.extend([
                        "-ac", "1", "-ar", "24000", "-b:a", "128k",
                        processed_output_path
                    ])

                    _LOGGER.debug("Executing FFmpeg command: %s", " ".join(ffmpeg_cmd_list))
                    ffmpeg_start_time = time.monotonic()
                    process = await self.hass.async_add_executor_job(
                        partial(subprocess.run, ffmpeg_cmd_list, check=False, capture_output=True, text=True)
                    )
                    _LOGGER.debug("FFmpeg processing completed in %.2f ms. Return code: %d", (time.monotonic() - ffmpeg_start_time) * 1000, process.returncode)

                    if process.returncode != 0:
                        _LOGGER.error("FFmpeg failed. Stdout: %s. Stderr: %s", process.stdout, process.stderr)
                        final_audio_content = audio_content
                    else:
                        with open(processed_output_path, "rb") as merged_file:
                            final_audio_content = merged_file.read()
                finally:
                    for path in (tts_input_path, processed_output_path):
                        if path and os.path.exists(path):
                            try:
                                os.remove(path)
                            except OSError as e_remove:
                                _LOGGER.warning("Could not remove temp file %s: %s", path, e_remove)
            else:
                final_audio_content = audio_content

            _LOGGER.debug("Overall TTS processing (non-streaming) completed in %.2f ms. Returning %d bytes.", (time.monotonic() - overall_start) * 1000, len(final_audio_content))
            return "mp3", final_audio_content

        except MaxLengthExceeded as mle:
            _LOGGER.error("TTS Error: %s", mle)
            return "mp3", None
        except CancelledError:
            raise
        except Exception as e:
            _LOGGER.exception("Unknown error during TTS generation: %s", e)
            return "mp3", None
