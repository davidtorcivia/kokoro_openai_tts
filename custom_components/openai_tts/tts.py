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
    CONF_KOKORO_CHUNK_SIZE, # Added
    DEFAULT_KOKORO_CHUNK_SIZE, # Added
    # CONF_KOKORO_VOICE_ALLOW_BLENDING is not directly used in tts.py, it's for config_flow
)
from .openaitts_engine import OpenAITTSEngine
from homeassistant.exceptions import MaxLengthExceeded

_LOGGER = logging.getLogger(__name__)

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
    async_add_entities([OpenAITTSEntity(hass, config_entry, engine)])

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
        return ["instructions", "chime", "chime_sound"]
        
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


    async def get_tts_audio(
        self, message: str, language: str, options: dict | None = None
    ) -> tuple[str, bytes] | tuple[None, None]:
        overall_start = time.monotonic()

        _LOGGER.debug(" -------------------------------------------")
        _LOGGER.debug("|  OpenAI TTS                               |")
        _LOGGER.debug("|  https://github.com/sfortis/openai_tts    |")
        _LOGGER.debug(" -------------------------------------------")

        try:
            if len(message) > 4096:
                raise MaxLengthExceeded("Message exceeds maximum allowed length")
            # Retrieve settings. Voice, speed, and instructions can be overridden by options or service call 'options'.
            # Voice is taken from options first, then from initial config data.
            # This allows options flow to change the voice.
            effective_voice = self._config.options.get(CONF_VOICE, self._config.data.get(CONF_VOICE))
            # Speed can also be configured in options.
            current_speed = self._config.options.get(CONF_SPEED, self._config.data.get(CONF_SPEED, 1.0))
            # Instructions can be configured in options or passed in service call.
            # Service call 'options' override component options.
            effective_instructions = options.get(CONF_INSTRUCTIONS, self._config.options.get(CONF_INSTRUCTIONS, self._config.data.get(CONF_INSTRUCTIONS)))

            _LOGGER.debug("Effective speed: %s", current_speed)
            _LOGGER.debug("Effective voice: %s", effective_voice)
            _LOGGER.debug("Effective instructions: %s", effective_instructions)

            # Note: chunk_size is configured in the engine during init, not passed per call to get_tts.

            _LOGGER.debug("Creating TTS API request")
            api_start = time.monotonic()

            audio_chunks = []
            # Pass effective voice, speed, and instructions to the engine's get_tts method.
            async for chunk in self._engine.get_tts(
                text=message,
                speed=current_speed,
                voice=effective_voice,
                instructions=effective_instructions
            ):
                audio_chunks.append(chunk)
            audio_content = b"".join(audio_chunks)

            if not audio_content:
                _LOGGER.error("TTS API returned no audio content.")
                return None, None

            api_duration = (time.monotonic() - api_start) * 1000
            _LOGGER.debug("TTS API call and streaming completed in %.2f ms", api_duration)

            # Retrieve options.
            chime_enabled = options.get(CONF_CHIME_ENABLE,self._config.options.get(CONF_CHIME_ENABLE, self._config.data.get(CONF_CHIME_ENABLE, False)))
            normalize_audio = self._config.options.get(CONF_NORMALIZE_AUDIO, self._config.data.get(CONF_NORMALIZE_AUDIO, False))
            _LOGGER.debug("Chime enabled: %s", chime_enabled)
            _LOGGER.debug("Normalization option: %s", normalize_audio)

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
    ) -> tuple[str, bytes] | tuple[None, None]:
        try:
            # Directly await the now asynchronous get_tts_audio method
            return await self.get_tts_audio(message, language, options=options)
        except CancelledError: # Changed from asyncio.CancelledError to just CancelledError
            _LOGGER.debug("async_get_tts_audio cancelled") # Changed from .exception to .debug
            raise
        except Exception: # Catch any other exception from get_tts_audio
            _LOGGER.exception("Error in async_get_tts_audio")
            return None, None

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""
        _LOGGER.debug("Closing OpenAI TTS engine session.")
        if self._engine:
            await self._engine.close()
