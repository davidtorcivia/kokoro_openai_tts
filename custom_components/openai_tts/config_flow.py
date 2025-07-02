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
from homeassistant.config_entries import ConfigFlow, OptionsFlow, ConfigEntry
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

DATA_SCHEMA_USER = vol.Schema({
    vol.Required(CONF_TTS_ENGINE, default=DEFAULT_TTS_ENGINE): selector({
        "select": {
            "options": TTS_ENGINES,
            "translation_key": "tts_engine"
        }
    })
})

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
    # CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL # Not used

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.init_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step where the user selects the TTS engine."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.init_data = user_input
            return await self.async_step_engine_specific_config()

        # If user_input is None, this is the first time the step is shown
        # self.init_data is already {} from __init__ or previous failed attempt of this step
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA_USER, errors=errors
        )

    async def async_step_engine_specific_config(self, user_input: dict[str, Any] | None = None):
        """Handle the engine-specific configuration step."""
        errors: dict[str, str] = {}
        current_engine = self.init_data.get(CONF_TTS_ENGINE)

        if not current_engine:
            _LOGGER.error("TTS Engine not found in init_data, returning to user step.")
            # Should ideally not happen if logic is correct
            return await self.async_step_user()

        if user_input is not None:
            full_data = {**self.init_data, **user_input}
            validation_errors = await validate_config_input(full_data)
            errors.update(validation_errors)

            if not errors:
                try:
                    entry_id = generate_entry_id()
                    full_data[UNIQUE_ID] = entry_id

                    title = "OpenAI TTS" # Default title
                    current_model_for_title = full_data.get(CONF_MODEL)

                    if full_data.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
                        current_model_for_title = KOKORO_MODEL # Model is fixed for Kokoro
                        kokoro_url_parsed = urlparse(full_data.get(CONF_KOKORO_URL, ""))
                        title = f"Kokoro FastAPI TTS ({kokoro_url_parsed.hostname}, {current_model_for_title})"
                        full_data.pop(CONF_API_KEY, None)
                        full_data.pop(CONF_URL, None)
                        full_data[CONF_MODEL] = KOKORO_MODEL
                    else:  # OpenAI or compatible
                        url_parsed = urlparse(full_data.get(CONF_URL, ""))
                        title = f"OpenAI TTS ({url_parsed.hostname}, {current_model_for_title})"
                        full_data.pop(CONF_KOKORO_URL, None)
                        # Ensure KOKORO specific config that might be in user_input from a previous attempt is removed
                        full_data.pop(CONF_KOKORO_CHUNK_SIZE, None)
                        full_data.pop(CONF_KOKORO_VOICE_ALLOW_BLENDING, None)

                    _LOGGER.debug("Attempting to create entry. Title: '%s'", title)
                    _LOGGER.debug("Full data for create_entry: %s", full_data)
                    if full_data.get(CONF_TTS_ENGINE) == KOKORO_FASTAPI_ENGINE:
                        _LOGGER.debug("Kokoro specific: CONF_KOKORO_URL: %s, CONF_MODEL: %s, CONF_VOICE: %s",
                                      full_data.get(CONF_KOKORO_URL),
                                      full_data.get(CONF_MODEL),
                                      full_data.get(CONF_VOICE))
                    return self.async_create_entry(title=title, data=full_data)
                except data_entry_flow.AbortFlow:
                    # AbortFlow is raised by async_create_entry if an entry with the same unique_id already exists
                    # This should ideally be caught by Home Assistant's config flow manager
                    # or by an earlier unique_id check if we were to implement one.
                    # For now, let it propagate or return a form with an error.
                    _LOGGER.warning("Config flow aborted, possibly due to existing entry.")
                    errors["base"] = "abort_flow_error" # Or a more specific error
                except Exception as e:
                    _LOGGER.exception("Detailed error creating entry (exc_info=True will show stack trace): %s", e, exc_info=True)
                    errors["base"] = "unknown" # Keep providing a generic UI error

        # Build schema dynamically based on current_engine
        # This part is executed if user_input is None (first time showing this step)
        # OR if user_input was provided but resulted in errors.
        data_schema_engine = {}
        # Get the current state of allow_blending from user_input if available, otherwise default to False
        allow_blending = user_input.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False) if user_input else False

        if current_engine == OPENAI_ENGINE:
            data_schema_engine.update({
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
                        "options": OPENAI_VOICES,
                        "mode": "dropdown", "sort": True, "custom_value": True, "translation_key": "voice"
                    }
                }),
            })
        elif current_engine == KOKORO_FASTAPI_ENGINE:
            data_schema_engine.update({
                vol.Required(CONF_KOKORO_URL, default=user_input.get(CONF_KOKORO_URL) if user_input else KOKORO_DEFAULT_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Optional(CONF_KOKORO_VOICE_ALLOW_BLENDING, default=allow_blending): bool,
            })
            # Dynamically set voice field
            if allow_blending:
                data_schema_engine[vol.Required(
                    CONF_VOICE,
                    default=user_input.get(CONF_VOICE, "") if user_input else ""
                )] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
            else:
                data_schema_engine[vol.Required(
                    CONF_VOICE,
                    default=user_input.get(CONF_VOICE, KOKORO_VOICES[0]) if user_input else KOKORO_VOICES[0]
                )] = selector({
                    "select": {
                        "options": KOKORO_VOICES,
                        "mode": "dropdown", "sort": True, "custom_value": False
                    }
                })
            # Add chunk size for Kokoro
            data_schema_engine[vol.Optional(
                CONF_KOKORO_CHUNK_SIZE,
                default=user_input.get(CONF_KOKORO_CHUNK_SIZE, DEFAULT_KOKORO_CHUNK_SIZE) if user_input else DEFAULT_KOKORO_CHUNK_SIZE
            )] = vol.Coerce(int)


        # Common field for both engines - Speed
        # Default handling: if user_input exists (form re-shown due to error), use its value, else use default.
        data_schema_engine.update({
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
            step_id="engine_specific_config",
            data_schema=vol.Schema(data_schema_engine),
            errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OpenAITTSOptionsFlow: # Added type hint
        """Get the options flow for this handler."""
        return OpenAITTSOptionsFlow(config_entry)

class OpenAITTSOptionsFlow(OptionsFlow):
    """Handle options flow for OpenAI TTS."""

    def __init__(self, config_entry: ConfigEntry) -> None: # Added type hint
        """Initialize options flow."""
        # self.config_entry is automatically available from the base OptionsFlow class
        pass

    async def async_step_init(self, user_input: dict | None = None):
        """Handle options flow."""
        errors: dict[str, str] = {}
        engine_type = self.config_entry.data.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE)

        # Determine current_allow_blending based on the source:
        # 1. User input from the current form submission (if any field was changed).
        # 2. Existing options if no user input yet for this specific field.
        # 3. Default to False if not in options.

        # Store previous blending state to detect changes
        prev_allow_blending = self.config_entry.options.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False)

        if user_input is not None:
            current_allow_blending = user_input.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, prev_allow_blending)
            # If blending mode changed, we might need to re-show the form immediately
            # For now, we'll let it validate and then the next display of the form will be correct.
            # A more advanced setup would re-show here if only the checkbox changed.

            if engine_type == KOKORO_FASTAPI_ENGINE:
                chunk_size = user_input.get(CONF_KOKORO_CHUNK_SIZE)
                if chunk_size is not None and (not isinstance(chunk_size, int) or chunk_size <= 0):
                    errors[CONF_KOKORO_CHUNK_SIZE] = "invalid_chunk_size"

            # If CONF_KOKORO_VOICE_ALLOW_BLENDING was just changed, we might want to clear the voice
            # field if the type changed, or ensure its value is valid for the new type.
            # For simplicity, we'll rely on Voluptuous to raise error if type is wrong on submission.
            # A better UX might clear CONF_VOICE if the type changes.

            if not errors:
                # Ensure all relevant data is included for create_entry
                # user_input might only contain changed fields.
                # We need to merge with existing options.
                final_options = self.config_entry.options.copy()
                final_options.update(user_input)
                return self.async_create_entry(title="", data=final_options)
        else:
            # First time showing the form, or re-showing after an error from a previous attempt (where user_input would not be None)
            current_allow_blending = self.config_entry.options.get(CONF_KOKORO_VOICE_ALLOW_BLENDING, False)
            # Populate user_input with existing options to pre-fill the form
            user_input = {**self.config_entry.options}


        chime_options = await self.hass.async_add_executor_job(get_chime_options)
        options_schema_dict = {}

        # Engine-specific options first
        if engine_type == KOKORO_FASTAPI_ENGINE:
            options_schema_dict.update({
                vol.Optional(
                    CONF_KOKORO_VOICE_ALLOW_BLENDING,
                    default=current_allow_blending # Use the most up-to-date value
                ): bool,
                vol.Optional(
                    CONF_KOKORO_CHUNK_SIZE,
                    default=user_input.get(CONF_KOKORO_CHUNK_SIZE, DEFAULT_KOKORO_CHUNK_SIZE)
                ): vol.Coerce(int),
            })

            # Default voice: try from user_input (if re-showing form), then options, then data, then default
            default_voice_for_field = user_input.get(CONF_VOICE, self.config_entry.data.get(CONF_VOICE, KOKORO_VOICES[0]))

            if current_allow_blending:
                # If blending is now allowed, but previous voice was from selector, it might not be a good default.
                # If previous was text, it's a good default.
                # If the type changed, it might be better to default to empty string for text field.
                if not prev_allow_blending: # If we just switched to blending
                     default_voice_for_field = user_input.get(CONF_VOICE, "") # Default to empty if switching to text
                else: # Sticking with blending or form re-shown with blending already on
                     default_voice_for_field = user_input.get(CONF_VOICE, default_voice_for_field)

                options_schema_dict[vol.Optional(CONF_VOICE, default=default_voice_for_field)] = cv.string
            else:
                # If blending is not allowed, ensure default is one of KOKORO_VOICES
                if default_voice_for_field not in KOKORO_VOICES:
                    default_voice_for_field = KOKORO_VOICES[0] # Fallback to first predefined voice
                options_schema_dict[vol.Optional(CONF_VOICE, default=default_voice_for_field)] = vol.In(KOKORO_VOICES)
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
