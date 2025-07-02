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
    
    # ---- START DEBUG ----
    _LOGGER.error("DEBUG: Attempting to instantiate KokoroOpenAITTSEntity.")
    _LOGGER.error("DEBUG: Type of KokoroOpenAITTSEntity variable in this scope: %s", type(KokoroOpenAITTSEntity))
    try:
        our_class_from_mro = KokoroOpenAITTSEntity.mro()[0] # Should be custom_components.openai_tts.tts.KokoroOpenAITTSEntity
        _LOGGER.error("DEBUG: MRO[0] is: %s", our_class_from_mro)
        _LOGGER.error("DEBUG: MRO[0].__init__ signature: %s", inspect.signature(our_class_from_mro.__init__))
        
        # Also inspect the __init__ of the variable KokoroOpenAITTSEntity directly, as before
        _LOGGER.error("DEBUG: Direct KokoroOpenAITTSEntity __init__ signature: %s", inspect.signature(KokoroOpenAITTSEntity.__init__))

    except Exception as e_inspect:
        _LOGGER.error("DEBUG: Error inspecting KokoroOpenAITTSEntity: %s", e_inspect)
    # ---- END DEBUG ----

    entity = KokoroOpenAITTSEntity(hass, config_entry, engine)
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

# ---- START DEBUG ----
import inspect
# _LOGGER.error("DEBUG: About to define KokoroOpenAITTSEntity. Current globals: %s", 'KokoroOpenAITTSEntity' in globals()) # Removed to reduce noise
# ---- END DEBUG ----

import hashlib # For message hashing

class KokoroOpenAITTSEntity(TextToSpeechEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: ConfigEntry, engine: OpenAITTSEngine) -> None:
        self.hass = hass
        self._engine = engine
        self._config = config
        self._attr_unique_id = config.data.get(UNIQUE_ID)
        if not self._attr_unique_id:
            # Fallback unique ID using URL and model if specific UNIQUE_ID isn't set
            # This helps ensure stability even if UNIQUE_ID was missed during initial setup for some reason.
            url_part = config.data.get(CONF_URL, "unknown_url")
            model_part = config.data.get(CONF_MODEL, "unknown_model")
            self._attr_unique_id = f"{url_part}_{model_part}"

        # Ensure entity_id is generated correctly using the base name.
        # The base name could be derived from the model or a more generic name if model is not descriptive.
        base_name = self._config.data.get(CONF_MODEL, "openai_tts").replace("-", "_").lower() # Sanitize for entity ID
        self.entity_id = generate_entity_id(
            "tts.{}", # Use the platform name prefix for consistency
            f"{DOMAIN}_{base_name}", # Combine domain and sanitized base name
            hass=hass
        )
        _LOGGER.debug("Initialized KokoroOpenAITTSEntity with entity_id: %s and unique_id: %s", self.entity_id, self._attr_unique_id)


    @property
    def default_language(self) -> str:
        return "en" # OpenAI models generally default to English or auto-detect

    @property
    def supported_options(self) -> list:
        # Add media_source support and other existing options
        return [
            "instructions",
            "chime",
            "chime_sound",
            media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID
        ]

    @property
    def supported_languages(self) -> list:
        # Delegate to the engine if it has a method for this, otherwise return a sensible default.
        if hasattr(self._engine, 'get_supported_langs'):
            return self._engine.get_supported_langs()
        return ["en"] # Fallback if engine doesn't specify

    @property
    def device_info(self) -> dict:
        engine_type = self._config.data.get(CONF_TTS_ENGINE, OPENAI_ENGINE)
        manufacturer = "OpenAI"
        model_identifier = self._config.data.get(CONF_MODEL, "Generic TTS")

        if engine_type == KOKORO_FASTAPI_ENGINE:
            manufacturer = "Kokoro FastAPI"
            # For Kokoro, the model might be more abstract or tied to the Kokoro instance
            model_identifier = f"Kokoro ({model_identifier})"


        return {
            "identifiers": {(DOMAIN, self._attr_unique_id)}, # Use the unique_id for device identification
            "name": self.name, # The entity name, which is usually descriptive
            "manufacturer": manufacturer,
            "model": model_identifier,
            "sw_version": "1.0", # Placeholder, could be dynamic
        }

    @property
    def name(self) -> str:
        # Attempt to use the config entry's title for a user-friendly name.
        # Fallback to a generated name if title is not available.
        if self._config.title:
            return self._config.title

        engine_type_display = "OpenAI"
        if self._config.data.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
            engine_type_display = "Kokoro FastAPI"
        model_name = self._config.data.get(CONF_MODEL, "TTS")
        return f"{engine_type_display} {model_name}"

    async def get_tts_audio(
        self, message: str, language: str, options: dict | None = None
    ) -> media_source.PlayMedia | tuple[str | None, bytes | None]:
        overall_start = time.monotonic()
        options = options or {}

        _LOGGER.debug(" -------------------------------------------")
        _LOGGER.debug("|  Kokoro OpenAI TTS                        |")
        _LOGGER.debug("|  https://github.com/davidtorcivia/kokoro_openai_tts |")
        _LOGGER.debug(" -------------------------------------------")
        _LOGGER.debug("get_tts_audio called with message (first 50 chars): '%s', lang: %s, options: %s", message[:50], language, options)


        try:
            # Check if media_source streaming is requested via options
            if options.get(media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID):
                _LOGGER.debug("Media source streaming requested for message: %s", message[:50])

                message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
                from urllib.parse import quote
                encoded_message = quote(message)

                # Use self.entity_id which is now correctly initialized
                stream_url_path = STREAMING_VIEW_URL.format(entity_id=self.entity_id, message_hash=message_hash)
                # Ensure full URL is correctly formed using Home Assistant's get_url helper
                full_stream_url = f"{get_url(self.hass, prefer_external=True)}{stream_url_path}?message={encoded_message}"
                # Added prefer_external=True for broader player compatibility if HA is behind a proxy

                _LOGGER.debug("Generated streaming URL: %s", full_stream_url)

                chime_enabled_option = self._config.options.get(CONF_CHIME_ENABLE, self._config.data.get(CONF_CHIME_ENABLE, False))
                normalize_audio_option = self._config.options.get(CONF_NORMALIZE_AUDIO, self._config.data.get(CONF_NORMALIZE_AUDIO, False))
                if chime_enabled_option or normalize_audio_option:
                    _LOGGER.warning(
                        "Chime and/or normalization are enabled but will be BYPASSED for media_source streaming."
                    )
                # Return PlayMedia object for streaming
                return media_source.PlayMedia(url=full_stream_url, mime_type="audio/mpeg") # Assuming MP3 for OpenAI/Kokoro

            # --- Fallback to existing non-streaming logic (direct byte generation) ---
            if len(message) > 4096: # Max length check for non-streaming
                _LOGGER.error("Message length %d exceeds maximum allowed 4096 characters.", len(message))
                raise MaxLengthExceeded(f"Message length {len(message)} exceeds maximum allowed 4096 characters for non-streaming TTS.")


            # Retrieve current settings from config entry (options override data)
            effective_voice = self._config.options.get(CONF_VOICE, self._config.data.get(CONF_VOICE))
            current_speed = self._config.options.get(CONF_SPEED, self._config.data.get(CONF_SPEED, 1.0))
            # Instructions can come from service call options, then config options, then config data
            effective_instructions = options.get(
                CONF_INSTRUCTIONS,
                self._config.options.get(CONF_INSTRUCTIONS, self._config.data.get(CONF_INSTRUCTIONS))
            )

            _LOGGER.debug(
                "Non-streaming path. Effective settings: Voice: %s, Speed: %s, Instructions: %s",
                effective_voice, current_speed, "Present" if effective_instructions else "Not set"
            )

            api_start = time.monotonic()
            audio_chunks = []
            # Call the engine's get_tts method (which should be async)
            async for chunk in self._engine.get_tts(
                text=message,
                speed=current_speed,
                voice=effective_voice,
                instructions=effective_instructions
                # language=language, # Pass language if engine supports it, OpenAI typically infers or uses voice setting
            ):
                if chunk: # Ensure chunk is not empty
                    audio_chunks.append(chunk)
            audio_content = b"".join(audio_chunks)

            if not audio_content:
                _LOGGER.error("TTS API returned no audio content (non-streaming path).")
                return "mp3", None # Consistent with HA docs for error cases

            api_duration = (time.monotonic() - api_start) * 1000
            _LOGGER.debug("TTS API call (non-streaming) completed in %.2f ms, received %d bytes", api_duration, len(audio_content))

            # Determine if chime or normalization is needed from config (options override data)
            chime_enabled = options.get(CONF_CHIME_ENABLE, self._config.options.get(CONF_CHIME_ENABLE, self._config.data.get(CONF_CHIME_ENABLE, False)))
            normalize_audio = self._config.options.get(CONF_NORMALIZE_AUDIO, self._config.data.get(CONF_NORMALIZE_AUDIO, False))

            _LOGGER.debug("Chime enabled (non-streaming): %s", chime_enabled)
            _LOGGER.debug("Normalization option (non-streaming): %s", normalize_audio)

            # FFmpeg processing for chime and/or normalization
            if chime_enabled or normalize_audio:
                # Write original TTS audio to a temporary file for FFmpeg input
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tts_file:
                    tts_file.write(audio_content)
                    tts_input_path = tts_file.name
                _LOGGER.debug("TTS audio for FFmpeg written to temp file: %s", tts_input_path)

                processed_output_path = "" # Path for FFmpeg output

                try:
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as out_file:
                        processed_output_path = out_file.name

                    ffmpeg_cmd_list = ["ffmpeg", "-y"] # Base command

                    if chime_enabled:
                        chime_file_name = options.get(CONF_CHIME_SOUND, self._config.options.get(CONF_CHIME_SOUND, self._config.data.get(CONF_CHIME_SOUND, "threetone.mp3")))
                        if not chime_file_name.lower().endswith('.mp3'):
                            chime_file_name = f"{chime_file_name}.mp3"
                        chime_file_path = os.path.join(os.path.dirname(__file__), "chime", chime_file_name)
                        _LOGGER.debug("Using chime file: %s", chime_file_path)

                        if not os.path.exists(chime_file_path):
                            _LOGGER.error("Chime file not found at %s. Skipping chime.", chime_file_path)
                            # If chime file is missing, proceed as if chime was disabled for this part
                            chime_enabled = False # Effectively disable chime if file is missing
                        else:
                            ffmpeg_cmd_list.extend(["-i", chime_file_path]) # Input 0 (chime)

                    ffmpeg_cmd_list.extend(["-i", tts_input_path]) # Input 1 (or 0 if no chime) (TTS)

                    filter_complex_parts = []
                    input_label_tts = "[1:a]" if chime_enabled else "[0:a]" # TTS audio stream label

                    if normalize_audio:
                        filter_complex_parts.append(f"{input_label_tts}loudnorm=I=-16:TP=-1:LRA=5[norm_tts]")
                        input_label_tts = "[norm_tts]" # Next operation uses normalized TTS

                    if chime_enabled: # If chime file was found and chime is still enabled
                        # Prepend chime: [0:a] is chime, input_label_tts is (possibly normalized) TTS
                        filter_complex_parts.append(f"[0:a]{input_label_tts}concat=n=2:v=0:a=1[out]")
                    elif normalize_audio: # Only normalization, no chime
                        filter_complex_parts.append(f"{input_label_tts}copy[out]") # Just pass through the normalized audio

                    if filter_complex_parts: # If any filtering/concatenation was done
                        ffmpeg_cmd_list.extend(["-filter_complex", ";".join(filter_complex_parts), "-map", "[out]"])
                    # If neither chime nor normalization (but somehow ended up in this block),
                    # ffmpeg will just copy the input tts_input_path to processed_output_path.
                    # This case should ideally be handled by the outer if, but as a safeguard:
                    elif not chime_enabled and not normalize_audio:
                         _LOGGER.warning("FFmpeg processing block entered without chime or normalize. This is unexpected.")
                         # Fallback to just copying the TTS audio if this path is somehow hit
                         # This shouldn't happen if the outer 'if chime_enabled or normalize_audio:' is correct

                    # Common output parameters
                    ffmpeg_cmd_list.extend([
                        "-ac", "1", "-ar", "24000", "-b:a", "128k",
                        "-preset", "superfast", "-threads", "4", # Consider making threads configurable or auto-detected
                        processed_output_path
                    ])

                    _LOGGER.debug("Executing FFmpeg command: %s", " ".join(ffmpeg_cmd_list))
                    ffmpeg_start_time = time.monotonic()
                    # Use partial for subprocess.run to ensure it's run in executor
                    process = await self.hass.async_add_executor_job(
                        partial(subprocess.run, ffmpeg_cmd_list, check=False, capture_output=True, text=True) # check=False to inspect errors
                    )
                    ffmpeg_duration = (time.monotonic() - ffmpeg_start_time) * 1000
                    _LOGGER.debug("FFmpeg processing completed in %.2f ms. Return code: %d", ffmpeg_duration, process.returncode)

                    if process.returncode != 0:
                        _LOGGER.error("FFmpeg failed. Stdout: %s. Stderr: %s", process.stdout, process.stderr)
                        # Fallback to original audio content if FFmpeg fails
                        audio_content_to_return = audio_content
                    else:
                        with open(processed_output_path, "rb") as merged_file:
                            audio_content_to_return = merged_file.read()
                finally:
                    # Cleanup temporary files
                    if os.path.exists(tts_input_path):
                        try:
                            os.remove(tts_input_path)
                        except Exception as e_remove:
                            _LOGGER.warning("Could not remove temp TTS input file %s: %s", tts_input_path, e_remove)
                    if processed_output_path and os.path.exists(processed_output_path):
                        try:
                            os.remove(processed_output_path)
                        except Exception as e_remove:
                             _LOGGER.warning("Could not remove temp FFmpeg output file %s: %s", processed_output_path, e_remove)

                final_audio_content = audio_content_to_return # Use the processed audio (or original if FFmpeg failed)

            else: # No chime, no normalization
                _LOGGER.debug("Chime and normalization disabled; returning TTS MP3 audio directly.")
                final_audio_content = audio_content

            overall_duration = (time.monotonic() - overall_start) * 1000
            _LOGGER.debug("Overall TTS processing (non-streaming) completed in %.2f ms. Returning %d bytes.", overall_duration, len(final_audio_content))
            return "mp3", final_audio_content # Return format and bytes

        except MaxLengthExceeded as mle:
            _LOGGER.error("TTS Error: %s", mle)
            # HA expects (None, None) or (extension, None) for errors handled by TTS platform
            return "mp3", None # Or raise if HA handles MaxLengthExceeded specifically
        except CancelledError:
            _LOGGER.info("TTS task was cancelled.")
            raise # Re-raise for Home Assistant to handle
        except subprocess.CalledProcessError as spe:
            _LOGGER.error("FFmpeg processing failed: %s. Stderr: %s", spe, spe.stderr)
            return "mp3", None # Fallback: return None if FFmpeg fails
        except Exception as e:
            _LOGGER.exception("Unknown error during TTS generation in get_tts_audio: %s", e)
            return "mp3", None # Generic error fallback

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict | None = None,
    ) -> media_source.PlayMedia | tuple[str | None, bytes | None]:
        """Proxy to the synchronous get_tts_audio method, executed in executor."""
        # This method is called by Home Assistant and should be async.
        # The actual audio generation, especially if it involves blocking I/O or CPU-bound tasks (like FFmpeg),
        # should be run in an executor.
        # However, `get_tts_audio` itself uses `hass.async_add_executor_job` for FFmpeg
        # and its core API call to `self._engine.get_tts` is async.
        # So, direct await should be fine.
        try:
            return await self.get_tts_audio(message, language, options=options)
        except CancelledError:
            _LOGGER.debug("async_get_tts_audio cancelled by client (re-raising).")
            raise
        except Exception as e:
            _LOGGER.exception("Error caught in async_get_tts_audio wrapper: %s", e)
            # Fallback if get_tts_audio itself doesn't return (None, None) or (ext, None) on error.
            return "mp3", None


    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from Home Assistant."""
        _LOGGER.debug("KokoroOpenAITTSEntity is being removed. Closing engine session for entity: %s", self.entity_id)
        if self._engine and hasattr(self._engine, 'close'): # Check if engine has close method
            await self._engine.close()
        _LOGGER.debug("Engine session closed for %s.", self.entity_id)
