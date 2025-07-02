"""
Setting up TTS entity.
"""
from __future__ import annotations
import io
import logging
import os
import subprocess
import tempfile
import time
from asyncio import CancelledError
from functools import partial # Added for subprocess.run

from homeassistant.components.tts import TextToSpeechEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    # New constants
    CONF_TTS_ENGINE,
    OPENAI_ENGINE,
    KOKORO_FASTAPI_ENGINE,
    CONF_KOKORO_URL,
    CONF_KOKORO_CHUNK_SIZE,
    DEFAULT_KOKORO_CHUNK_SIZE,
    # CONF_KOKORO_VOICE_ALLOW_BLENDING is not directly used in tts.py, it's for config_flow
)
from .openaitts_engine import OpenAITTSEngine
from homeassistant.exceptions import MaxLengthExceeded
from homeassistant.components import media_source
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.network import get_url

_LOGGER = logging.getLogger(__name__)

# Define a constant for the streaming view URL
STREAMING_VIEW_URL = "/api/tts_openai_stream/{entity_id}/{message_hash}"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    engine_type = config_entry.data.get(CONF_TTS_ENGINE, OPENAI_ENGINE)
    api_key = config_entry.data.get(CONF_API_KEY) # Will be None if not provided

    if engine_type == KOKORO_FASTAPI_ENGINE:
        api_url = config_entry.data.get(CONF_KOKORO_URL)
        # API key might not be used by Kokoro, or could be a different type of auth
        # For now, we pass the OpenAI API key field, which might be None
    else: # OpenAI or compatible
        api_url = config_entry.data.get(CONF_URL)

    if not api_url:
        _LOGGER.error(
            "TTS API URL is not configured for engine type '%s'. Cannot setup OpenAI TTS.",
            engine_type
        )
        return

    # Get Kokoro-specific chunk_size from options if Kokoro engine is used
    # Options are preferred over data for user-configurable settings post-setup.
    kokoro_chunk_size = None
    if engine_type == KOKORO_FASTAPI_ENGINE:
        kokoro_chunk_size = config_entry.options.get(
            CONF_KOKORO_CHUNK_SIZE,
            config_entry.data.get(CONF_KOKORO_CHUNK_SIZE, DEFAULT_KOKORO_CHUNK_SIZE) # Fallback to data, then default
        )

    engine = OpenAITTSEngine(
        api_key=api_key,
        voice=config_entry.data[CONF_VOICE], # Initial voice from setup
        model=config_entry.data[CONF_MODEL], # Initial model from setup
        speed=config_entry.data.get(CONF_SPEED, 1.0), # Initial speed from setup
        url=api_url,
        chunk_size=kokoro_chunk_size # Pass chunk_size to engine
    )

    entity = OpenAITTSEntity(hass, config_entry, engine)
    async_add_entities([entity])

    # Register the streaming view
    hass.http.register_view(OpenAITTSStreamingView(hass, engine, config_entry))

# Need to import aiohttp.web for StreamResponse
import aiohttp.web

class OpenAITTSStreamingView(HomeAssistantView):
    """View to stream TTS audio."""

    requires_auth = False # Streaming URLs often need to be unauthenticated for media players
    url = STREAMING_VIEW_URL
    name = "api:tts_openai_stream" # Matches the /api/ part of the URL for Home Assistant

    def __init__(self, hass: HomeAssistant, engine: OpenAITTSEngine, config_entry: ConfigEntry):
        """Initialize the streaming view."""
        self.hass = hass
        self._engine = engine
        self._config = config_entry

    async def get(self, request: aiohttp.web.Request, entity_id: str, message_hash: str) -> aiohttp.web.StreamResponse:
        """Stream TTS audio."""

        message = request.query.get("message")
        if not message:
            _LOGGER.error("Streaming request for %s/%s missing 'message' query parameter.", entity_id, message_hash)
            # Return a plain text error, or could be JSON
            return aiohttp.web.Response(status=400, text="Missing 'message' query parameter")

        # Retrieve current voice and speed settings from config entry (options override data)
        # This ensures that if the user changes voice/speed in options, the stream uses them.
        effective_voice = self._config.options.get(CONF_VOICE, self._config.data.get(CONF_VOICE))
        current_speed = self._config.options.get(CONF_SPEED, self._config.data.get(CONF_SPEED, 1.0))
        # Instructions are generally not passed for simple streaming to avoid URL complexity.
        # If needed, they could be added to the query string or retrieved from a cache.
        # For now, we omit passing instructions to the engine in this streaming path.

        _LOGGER.debug(
            "Streaming request for entity_id: %s, message_hash: %s, voice: %s, speed: %s, message (first 30 chars): '%s'",
            entity_id, message_hash, effective_voice, current_speed, message[:30]
        )

        response = aiohttp.web.StreamResponse()
        # Set content type for the stream. Kokoro default is MP3.
        response.content_type = "audio/mpeg"
        # Set Cache-Control headers to prevent caching of the stream by intermediate proxies or the client.
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

        await response.prepare(request)

        try:
            async for chunk in self._engine.get_tts(
                text=message,
                speed=current_speed,
                voice=effective_voice,
                # instructions=effective_instructions, # Omitting for now
            ):
                if chunk: # Ensure chunk is not empty
                    await response.write(chunk)

            await response.write_eof() # Finalize the response stream
            return response

        except CancelledError:
            _LOGGER.debug("Streaming TTS request cancelled by client for entity_id: %s, message_hash: %s", entity_id, message_hash)
            # aiohttp handles client disconnects gracefully; re-raising allows it to do so.
            raise
        except Exception as e:
            _LOGGER.exception(
                "Error during TTS streaming for entity_id: %s, message_hash: %s - %s",
                entity_id, message_hash, str(e)
            )
            # If headers haven't been sent, we can try to send an error status.
            # However, if streaming has started, the connection might just break.
            # aiohttp's default error handling for views might take over if we re-raise.
            # For robustness, one might check `response.prepared` but for now, re-raise.
            raise


class OpenAITTSEntity(TextToSpeechEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: ConfigEntry, engine: OpenAITTSEngine) -> None:
        self.hass = hass
        self._engine = engine
        self._config = config
        self._attr_unique_id = config.data.get(UNIQUE_ID)
        if not self._attr_unique_id:
            self._attr_unique_id = f"{config.data.get(CONF_URL)}_{config.data.get(CONF_MODEL)}"
        base_name = self._config.data.get(CONF_MODEL, "").upper()
        self.entity_id = generate_entity_id("tts.openai_tts_{}", base_name.lower(), hass=hass)

    @property
    def default_language(self) -> str:
        return "en"

    @property
    def supported_options(self) -> list:
        # Add media_source support
        return ["instructions", "chime", "chime_sound", media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID]

    @property
    def supported_languages(self) -> list:
        return self._engine.get_supported_langs()

    @property
    def device_info(self) -> dict:
        engine_type = self._config.data.get(CONF_TTS_ENGINE, OPENAI_ENGINE)
        manufacturer = "OpenAI"
        if engine_type == KOKORO_FASTAPI_ENGINE:
            manufacturer = "Kokoro FastAPI"

        return {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "model": self._config.data.get(CONF_MODEL), # Model display can be kept as is
            "manufacturer": manufacturer,
            "name": self.name, # Add entity name to device name for clarity
            "sw_version": "1.0", # Example, can be dynamic if integration has versions
        }

    @property
    def name(self) -> str:
        # The title of the config entry is usually more descriptive and set in config_flow
        # This name property is for the entity itself.
        # Example: "OpenAI TTS tts-1" or "Kokoro TTS tts-1-hd"
        engine_type_display = "OpenAI"
        if self._config.data.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
            engine_type_display = "Kokoro FastAPI"

        model_name = self._config.data.get(CONF_MODEL, "Unknown Model")
        # return f"{engine_type_display} TTS {model_name.upper()}" # This might be too long
        return self._config.title or f"{engine_type_display} {model_name}"


import hashlib # For message hashing

# ... (other imports remain the same) ...

class OpenAITTSEntity(TextToSpeechEntity):
    # ... (other properties remain the same) ...

    async def get_tts_audio(
        self, message: str, language: str, options: dict | None = None
    ) -> media_source.PlayMedia | tuple[str | None, bytes | None]: # Updated return type
        overall_start = time.monotonic()
        options = options or {}

        _LOGGER.debug(" -------------------------------------------")
        _LOGGER.debug("|  OpenAI TTS                               |")
        _LOGGER.debug("|  https://github.com/sfortis/openai_tts    |")
        _LOGGER.debug(" -------------------------------------------")

        try:
            if media_source.is_media_source_id(message): # This checks if message is a media_source ID, not what we want.
                # We need to check if the *option* for media_source is requested.
                # The 'message' parameter here is the actual text to be spoken.
                pass # Placeholder, remove this block

            if options.get(media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID):
                _LOGGER.debug("Media source requested for message: %s", message[:50])
                # Generate a unique hash for the message to use in the URL,
                # or use the message itself if short enough and URL-safe.
                # Using a hash is generally safer.
                message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]

                # Construct the streaming URL
                # The message text needs to be passed to the view, typically as a query parameter.
                # Ensure message is URL-encoded.
                from urllib.parse import quote
                encoded_message = quote(message)

                stream_url_path = STREAMING_VIEW_URL.format(entity_id=self.entity_id, message_hash=message_hash)
                # Append actual message as query parameter
                # This is crucial: the view needs the text to synthesize.
                full_stream_url = f"{get_url(self.hass)}{stream_url_path}?message={encoded_message}"

                _LOGGER.debug("Generated streaming URL: %s", full_stream_url)

                # Warn if incompatible options are enabled
                chime_enabled_option = self._config.options.get(CONF_CHIME_ENABLE, self._config.data.get(CONF_CHIME_ENABLE, False))
                normalize_audio_option = self._config.options.get(CONF_NORMALIZE_AUDIO, self._config.data.get(CONF_NORMALIZE_AUDIO, False))
                if chime_enabled_option or normalize_audio_option:
                    _LOGGER.warning(
                        "Chime and/or normalization are enabled but will be bypassed for media_source streaming."
                    )

                return media_source.PlayMedia(url=full_stream_url, mime_type="audio/mpeg")

            # --- Fallback to existing non-streaming logic if media_source not requested ---
            if len(message) > 4096:
                raise MaxLengthExceeded("Message exceeds maximum allowed length")

            effective_voice = self._config.options.get(CONF_VOICE, self._config.data.get(CONF_VOICE))
            current_speed = self._config.options.get(CONF_SPEED, self._config.data.get(CONF_SPEED, 1.0))
            effective_instructions = options.get(CONF_INSTRUCTIONS, self._config.options.get(CONF_INSTRUCTIONS, self._config.data.get(CONF_INSTRUCTIONS)))

            _LOGGER.debug("Effective speed: %s", current_speed)
            _LOGGER.debug("Effective voice: %s", effective_voice)
            _LOGGER.debug("Effective instructions: %s", effective_instructions)

            _LOGGER.debug("Creating TTS API request (non-streaming path)")
            api_start = time.monotonic()

            audio_chunks = []
            async for chunk in self._engine.get_tts(
                text=message,
                speed=current_speed,
                voice=effective_voice,
                instructions=effective_instructions
            ):
                audio_chunks.append(chunk)
            audio_content = b"".join(audio_chunks)

            if not audio_content:
                _LOGGER.error("TTS API returned no audio content (non-streaming path).")
                return None, None

            api_duration = (time.monotonic() - api_start) * 1000
            _LOGGER.debug("TTS API call (non-streaming) completed in %.2f ms", api_duration)

            chime_enabled = options.get(CONF_CHIME_ENABLE,self._config.options.get(CONF_CHIME_ENABLE, self._config.data.get(CONF_CHIME_ENABLE, False)))
            normalize_audio = self._config.options.get(CONF_NORMALIZE_AUDIO, self._config.data.get(CONF_NORMALIZE_AUDIO, False))
            _LOGGER.debug("Chime enabled (non-streaming): %s", chime_enabled)
            _LOGGER.debug("Normalization option (non-streaming): %s", normalize_audio)

            if chime_enabled:
                # Write TTS audio to a temp file.
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tts_file:
                    tts_file.write(audio_content)
                    tts_path = tts_file.name
                _LOGGER.debug("TTS audio written to temp file: %s", tts_path)

                # Determine chime file path - check options first, then fall back to configured chime sound
                chime_file = options.get(CONF_CHIME_SOUND, self._config.options.get(CONF_CHIME_SOUND, self._config.data.get(CONF_CHIME_SOUND, "threetone.mp3")))
                # If no .mp3 extension, append it
                if not chime_file.lower().endswith('.mp3'):
                    chime_file = f"{chime_file}.mp3"
                chime_path = os.path.join(os.path.dirname(__file__), "chime", chime_file)
                _LOGGER.debug("Using chime file at: %s", chime_path)

                # Create a temporary output file.
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out_file:
                    merged_output_path = out_file.name

                if normalize_audio:
                    _LOGGER.debug("Both chime and normalization enabled; " +
                                  "using filter_complex to normalize TTS audio and merge with chime in one pass.")
                    # Use filter_complex to normalize the TTS audio and then concatenate with the chime.
                    # First input: chime audio, second input: TTS audio (to be normalized).
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i", chime_path,
                        "-i", tts_path,
                        "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1:LRA=5[tts_norm]; [0:a][tts_norm]concat=n=2:v=0:a=1[out]",
                        "-map", "[out]",
                        "-ac", "1",
                        "-ar", "24000",
                        "-b:a", "128k",
                        "-preset", "superfast",
                        "-threads", "4",
                        merged_output_path,
                    ]
                    _LOGGER.debug("Executing ffmpeg command: %s", " ".join(cmd))
                    await self.hass.async_add_executor_job(partial(subprocess.run, cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                else:
                    _LOGGER.debug("Chime enabled without normalization; merging using concat method.")
                    # Create a file list for concatenation.
                    with tempfile.NamedTemporaryFile(mode="w", delete=False) as list_file:
                        list_file.write(f"file '{chime_path}'\n")
                        list_file.write(f"file '{tts_path}'\n")
                        list_path = list_file.name
                    _LOGGER.debug("FFmpeg file list created: %s", list_path)
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", list_path,
                        "-ac", "1",
                        "-ar", "24000",
                        "-b:a", "128k",
                        "-preset", "superfast",
                        "-threads", "4",
                        merged_output_path,
                    ]
                    _LOGGER.debug("Executing ffmpeg command: %s", " ".join(cmd))
                    await self.hass.async_add_executor_job(partial(subprocess.run, cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    try:
                        os.remove(list_path)
                    except Exception:
                        pass

                with open(merged_output_path, "rb") as merged_file:
                    final_audio = merged_file.read()
                overall_duration = (time.monotonic() - overall_start) * 1000
                _LOGGER.debug("Overall TTS processing time: %.2f ms", overall_duration)
                # Cleanup temporary files.
                try:
                    os.remove(tts_path)
                    os.remove(merged_output_path)
                except Exception:
                    pass
                return "mp3", final_audio

            else:
                # Chime disabled.
                if normalize_audio:
                    _LOGGER.debug("Normalization enabled without chime; processing TTS audio via ffmpeg.")
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tts_file:
                        tts_file.write(audio_content)
                        norm_input_path = tts_file.name
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out_file:
                        norm_output_path = out_file.name
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i", norm_input_path,
                        "-ac", "1",
                        "-ar", "24000",
                        "-b:a", "128k",
                        "-preset", "superfast",
                        "-threads", "4",
                        "-af", "loudnorm=I=-16:TP=-1:LRA=5",
                        norm_output_path,
                    ]
                    _LOGGER.debug("Executing ffmpeg command: %s", " ".join(cmd))
                    await self.hass.async_add_executor_job(partial(subprocess.run, cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    with open(norm_output_path, "rb") as norm_file:
                        normalized_audio = norm_file.read()
                    overall_duration = (time.monotonic() - overall_start) * 1000
                    _LOGGER.debug("Overall TTS processing time: %.2f ms", overall_duration)
                    try:
                        os.remove(norm_input_path)
                        os.remove(norm_output_path)
                    except Exception:
                        pass
                    return "mp3", normalized_audio
                else:
                    _LOGGER.debug("Chime and normalization disabled; returning TTS MP3 audio only.")
                    overall_duration = (time.monotonic() - overall_start) * 1000
                    _LOGGER.debug("Overall TTS processing time: %.2f ms", overall_duration)
                    return "mp3", audio_content

        except CancelledError as ce:
            _LOGGER.exception("TTS task cancelled")
            return None, None
        except MaxLengthExceeded as mle:
            _LOGGER.exception("Maximum message length exceeded")
        except Exception as e:
            _LOGGER.exception("Unknown error in get_tts_audio")
        return None, None

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict | None = None,
    ) -> media_source.PlayMedia | tuple[str | None, bytes | None]: # Updated return type
        try:
            # Directly await the get_tts_audio method
            return await self.get_tts_audio(message, language, options=options)
        except CancelledError:
            _LOGGER.debug("async_get_tts_audio cancelled by client")
            raise
        except Exception:
            _LOGGER.exception("Error in async_get_tts_audio")
            # In case of PlayMedia, we can't return (None, None) directly if that path failed.
            # The get_tts_audio method itself should handle its errors and return (None, None) for byte path.
            # If PlayMedia path fails before returning PlayMedia object, it might raise, caught here.
            # If it's an error that means we can't provide audio, returning (None,None) is fallback.
            return None, None # Fallback for byte-based return if error occurs before PlayMedia object creation

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""
        _LOGGER.debug("Closing OpenAI TTS engine session.")
        if self._engine:
            await self._engine.close()
