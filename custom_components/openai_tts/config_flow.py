"""
Config flow for OpenAI TTS.
"""
from __future__ import annotations
from typing import Any
import os
import voluptuous as vol
import logging
from urllib.parse import urlparse
import uuid

from homeassistant import data_entry_flow
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.helpers.selector import selector
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_API_KEY,
    CONF_MODEL,
    CONF_VOICE,
    CONF_SPEED,
    CONF_URL,
    DOMAIN,
    MODELS, # Default OpenAI models
    OPENAI_VOICES, # Renamed from VOICES
    UNIQUE_ID,
    CONF_CHIME_ENABLE,
    CONF_CHIME_SOUND,
    CONF_NORMALIZE_AUDIO,
    CONF_INSTRUCTIONS,
    # New constants
    CONF_TTS_ENGINE,
    OPENAI_ENGINE,
    KOKORO_FASTAPI_ENGINE,
    TTS_ENGINES,
    DEFAULT_TTS_ENGINE,
    CONF_KOKORO_URL,
    KOKORO_DEFAULT_URL,
    KOKORO_MODEL,
    KOKORO_VOICES,
    CONF_KOKORO_CHUNK_SIZE,                # Added
    DEFAULT_KOKORO_CHUNK_SIZE,           # Added
    CONF_KOKORO_VOICE_ALLOW_BLENDING,    # Added
)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

# Removed class-level data_schema, it will be dynamic

def generate_entry_id() -> str:
    return str(uuid.uuid4())

async def validate_config_input(user_input: dict):
    """Validate common and engine-specific fields."""
    errors = {}
    # Common validations are now mostly handled by schema defaults and types (e.g. vol.In)
    # Specific logic validation:
    engine_type = user_input.get(CONF_TTS_ENGINE)

    if engine_type == OPENAI_ENGINE:
        if not user_input.get(CONF_MODEL): # Still check if empty, though schema has default
            errors[CONF_MODEL] = "model_required"
        if not user_input.get(CONF_VOICE): # Still check if empty
            errors[CONF_VOICE] = "voice_required"
        if not user_input.get(CONF_URL):
            errors[CONF_URL] = "url_required_openai"
    elif engine_type == KOKORO_FASTAPI_ENGINE:
        # Model is fixed via cv.disabled, so no need to validate its presence.
        # Voice is from a vol.In list, ensuring it's one of the valid Kokoro voices.
        if not user_input.get(CONF_VOICE): # Should be caught by schema if required
             errors[CONF_VOICE] = "voice_required" # Redundant if schema makes it vol.Required
        if not user_input.get(CONF_KOKORO_URL):
            errors[CONF_KOKORO_URL] = "kokoro_url_required"
    return errors

def get_chime_options() -> list[dict[str, str]]:
    """
    Scans the "chime" folder (located in the same directory as this file)
    and returns a list of options for the dropdown selector.
    Each option is a dict with 'value' (the file name) and 'label' (the file name without extension).
    """
    chime_folder = os.path.join(os.path.dirname(__file__), "chime")
    try:
        files = os.listdir(chime_folder)
    except Exception as err:
        _LOGGER.error("Error listing chime folder: %s", err)
        files = []
    options = []
    for file in files:
        if file.lower().endswith(".mp3"):
            label = os.path.splitext(file)[0].title()  # e.g. "Signal1.mp3" -> "Signal1"
            options.append({"value": file, "label": label})
    options.sort(key=lambda x: x["label"])
    return options

class OpenAITTSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenAI TTS."""
    VERSION = 1
    # Connection class and data not needed for this version of config flow
    # CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    # data: dict[str, Any] = {} # To store data across steps if needed

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store current input to repopulate form if errors occur
            # self.data.update(user_input) # If using self.data for multi-step

            # Validate common and engine-specific fields
            validation_errors = await validate_config_input(user_input)
            errors.update(validation_errors)

            if not errors:
                try:
                    entry_id = generate_entry_id()
                    # await self.async_set_unique_id(entry_id) # Deprecated, unique_id handled by data
                    user_input[UNIQUE_ID] = entry_id

                    title = "OpenAI TTS"
                    current_model_for_title = user_input.get(CONF_MODEL)

                    if user_input.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
                        # For Kokoro, model is fixed by schema (cv.disabled)
                        # but user_input might not contain it if disabled fields are not submitted.
                        # So, we use KOKORO_MODEL directly for title consistency.
                        current_model_for_title = KOKORO_MODEL
                        kokoro_url_parsed = urlparse(user_input.get(CONF_KOKORO_URL, ""))
                        title = f"Kokoro FastAPI TTS ({kokoro_url_parsed.hostname}, {current_model_for_title})"
                        # Clean up: Remove OpenAI specific fields, ensure API key is not stored
                        user_input.pop(CONF_API_KEY, None)
                        user_input.pop(CONF_URL, None)
                        # Ensure model is set to the fixed Kokoro model in saved data
                        user_input[CONF_MODEL] = KOKORO_MODEL
                    else: # OpenAI or compatible
                        url_parsed = urlparse(user_input.get(CONF_URL, ""))
                        title = f"OpenAI TTS ({url_parsed.hostname}, {current_model_for_title})"
                        # Clean up: Remove Kokoro specific fields
                        user_input.pop(CONF_KOKORO_URL, None)

                    return self.async_create_entry(title=title, data=user_input)
                except data_entry_flow.AbortFlow:
                except Exception as e:
                    _LOGGER.exception("Unexpected error creating entry: %s", e)
                    errors["base"] = "unknown" # Use "unknown" from strings.json

        # Determine current engine for schema or default
        current_engine = user_input.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE) if user_input else DEFAULT_TTS_ENGINE

        # Build schema dynamically
        data_schema_user = {
            vol.Required(CONF_TTS_ENGINE, default=current_engine): selector({
                "select": {
                    "options": TTS_ENGINES,
                    "translation_key": "tts_engine" # Uses selector.<domain>.<translation_key>
                }
            }),
        }

        if current_engine == OPENAI_ENGINE:
            data_schema_user.update({
                vol.Optional(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required(CONF_URL, default=user_input.get(CONF_URL) if user_input else "https://api.openai.com/v1/audio/speech"): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(CONF_MODEL, default=user_input.get(CONF_MODEL, "tts-1") if user_input else "tts-1"): selector({
                    "select": {
                        "options": MODELS,
                        "mode": "dropdown", "sort": True, "custom_value": True, "translation_key": "model"
                    }
                }),
                vol.Required(CONF_VOICE, default=user_input.get(CONF_VOICE, OPENAI_VOICES[0]) if user_input else OPENAI_VOICES[0]): selector({
                    "select": {
                        "options": OPENAI_VOICES, # Use specific OpenAI voices
                        "mode": "dropdown", "sort": True, "custom_value": True, "translation_key": "voice" # Assuming generic voice selector for now
                    }
                }),
            })
        elif current_engine == KOKORO_FASTAPI_ENGINE:
            data_schema_user.update({
                vol.Required(CONF_KOKORO_URL, default=user_input.get(CONF_KOKORO_URL) if user_input else KOKORO_DEFAULT_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(CONF_MODEL, default=KOKORO_MODEL): cv.disabled(KOKORO_MODEL),
                # Voice is now a text field for Kokoro in user step, to allow future blending input.
                # Default to first Kokoro voice. Description in strings.json will guide user.
                vol.Required(CONF_VOICE, default=user_input.get(CONF_VOICE, KOKORO_VOICES[0]) if user_input else KOKORO_VOICES[0]): cv.string,
            })

        # Common fields - Speed is always applicable.
        data_schema_user.update({
            vol.Optional(CONF_SPEED, default=user_input.get(CONF_SPEED, 1.0) if user_input else 1.0): selector({
                "number": {
                    "min": 0.25,
                    "max": 4.0,
                    "step": 0.05,
                    "mode": "slider"
                }
            }),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema_user),
            errors=errors,
            # description_placeholders can be used if needed, e.g. for API key hints
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OpenAITTSOptionsFlow: # Added type hint
        """Get the options flow for this handler."""
        return OpenAITTSOptionsFlow(config_entry)

class OpenAITTSOptionsFlow(OptionsFlow):
    """Handle options flow for OpenAI TTS."""

    def __init__(self, config_entry: ConfigEntry) -> None: # Added type hint
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        """Handle options flow."""
        errors: dict[str, str] = {}
        engine_type = self.config_entry.data.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE)

        # Determine current allow_blending setting (from user_input or existing options)
        # This is needed to dynamically set the voice field type
        if user_input is not None:
            current_allow_blending = user_input.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False)
        else:
            current_allow_blending = self.config_entry.options.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False)

        if user_input is not None:
            if engine_type == KOKORO_FASTAPI_ENGINE:
                chunk_size = user_input.get(CONF_KOKORO_CHUNK_SIZE)
                if chunk_size is not None and (not isinstance(chunk_size, int) or chunk_size <= 0):
                    errors[CONF_KOKORO_CHUNK_SIZE] = "invalid_chunk_size"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        chime_options = await self.hass.async_add_executor_job(get_chime_options)

        options_schema_dict = {}
        # Engine-specific options first
        if engine_type == KOKORO_FASTAPI_ENGINE:
            options_schema_dict.update({
                vol.Optional(
                    CONF_KOKORO_VOICE_ALLOW_BLENDING,
                    default=self.config_entry.options.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False)
                ): bool, # Simple boolean toggle
                vol.Optional(
                    CONF_KOKORO_CHUNK_SIZE,
                    default=self.config_entry.options.get(CONF_KOKORO_CHUNK_SIZE, DEFAULT_KOKORO_CHUNK_SIZE)
                ): vol.Coerce(int), # Integer input for chunk size
            })
            # Dynamically set voice field type based on blending option
            if current_allow_blending:
                options_schema_dict[vol.Optional(
                    CONF_VOICE,
                    default=self.config_entry.options.get(CONF_VOICE, self.config_entry.data.get(CONF_VOICE, KOKORO_VOICES[0]))
                )] = cv.string
            else:
                options_schema_dict[vol.Optional(
                    CONF_VOICE,
                    default=self.config_entry.options.get(CONF_VOICE, self.config_entry.data.get(CONF_VOICE, KOKORO_VOICES[0]))
                )] = vol.In(KOKORO_VOICES)

            options_schema_dict[vol.Optional(CONF_MODEL, default=KOKORO_MODEL)] = cv.disabled(KOKORO_MODEL)

        else: # OpenAI
            options_schema_dict.update({
                vol.Optional(CONF_MODEL, default=self.config_entry.options.get(CONF_MODEL, self.config_entry.data.get(CONF_MODEL, "tts-1"))): selector({
                    "select": {"options": MODELS, "mode": "dropdown", "sort": True, "custom_value": True, "translation_key": "model"}
                }),
                vol.Optional(CONF_VOICE, default=self.config_entry.options.get(CONF_VOICE, self.config_entry.data.get(CONF_VOICE, OPENAI_VOICES[0]))): selector({
                    "select": {"options": OPENAI_VOICES, "mode": "dropdown", "sort": True, "custom_value": True, "translation_key": "voice"}
                }),
            })

        # Common options applicable to both
        options_schema_dict.update({
            vol.Optional(CONF_SPEED, default=self.config_entry.options.get(CONF_SPEED, self.config_entry.data.get(CONF_SPEED, 1.0))): selector({
                "number": {"min": 0.25, "max": 4.0, "step": 0.05, "mode": "slider"}
            }),
            vol.Optional(CONF_INSTRUCTIONS, default=self.config_entry.options.get(CONF_INSTRUCTIONS, self.config_entry.data.get(CONF_INSTRUCTIONS, ""))): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
            vol.Optional(CONF_CHIME_ENABLE, default=self.config_entry.options.get(CONF_CHIME_ENABLE, self.config_entry.data.get(CONF_CHIME_ENABLE, False))): selector({"boolean": {}}),
            vol.Optional(CONF_CHIME_SOUND, default=self.config_entry.options.get(CONF_CHIME_SOUND, self.config_entry.data.get(CONF_CHIME_SOUND, "threetone.mp3"))): selector({
                "select": {"options": chime_options}
            }),
            vol.Optional(CONF_NORMALIZE_AUDIO, default=self.config_entry.options.get(CONF_NORMALIZE_AUDIO, self.config_entry.data.get(CONF_NORMALIZE_AUDIO, False))): selector({"boolean": {}})
        })

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema_dict),
            errors=errors,
            description_placeholders={CONF_KOKORO_VOICE_ALLOW_BLENDING: current_allow_blending} # Pass this to show_form if needed by descriptions
        )
