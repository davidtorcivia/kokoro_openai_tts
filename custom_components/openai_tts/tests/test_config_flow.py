import unittest
from unittest.mock import patch, MagicMock

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigFlow, ConfigEntry
from homeassistant.helpers import config_validation as cv

# Adjust these imports to your actual component structure
from custom_components.openai_tts.config_flow import OpenAITTSConfigFlow, OpenAITTSOptionsFlow
from custom_components.openai_tts.const import (
    DOMAIN,
    CONF_TTS_ENGINE,
    OPENAI_ENGINE,
    KOKORO_FASTAPI_ENGINE,
    CONF_API_KEY,
    CONF_URL,
    CONF_KOKORO_URL,
    KOKORO_DEFAULT_URL,
    CONF_MODEL,
    KOKORO_MODEL,
    CONF_VOICE,
    KOKORO_VOICES,
    OPENAI_VOICES,
    MODELS,
    CONF_SPEED,
    CONF_KOKORO_CHUNK_SIZE,
    DEFAULT_KOKORO_CHUNK_SIZE,
    CONF_KOKORO_VOICE_ALLOW_BLENDING,
    TTS_ENGINES, # Make sure this is imported if used directly
    DEFAULT_TTS_ENGINE
)

class MockConfigEntry(ConfigEntry):
    def __init__(self, *, data=None, options=None, entry_id="test_entry_id", domain=DOMAIN, title="Test Title"):
        super().__init__(entry_id=entry_id, domain=domain, title=title, data=data or {}, source="user", options=options or {})


class TestOpenAITTSConfigFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.hass = MagicMock(spec=HomeAssistant)
        # Mock get_chime_options as it involves file system access
        self.patch_get_chime_options = patch(
            "custom_components.openai_tts.config_flow.get_chime_options",
            return_value=[{"value": "threetone.mp3", "label": "Threetone"}]
        )
        self.mock_get_chime_options = self.patch_get_chime_options.start()

    async def asyncTearDown(self):
        self.patch_get_chime_options.stop()

    async def test_user_step_default_openai(self):
        """Test user step with default engine (OpenAI)."""
        flow = OpenAITTSConfigFlow()
        flow.hass = self.hass # Assign hass to the flow instance

        result = await flow.async_step_user()
        self.assertEqual(result["type"], data_entry_flow.RESULT_TYPE_FORM)
        self.assertEqual(result["step_id"], "user")

        schema = result["data_schema"].schema
        self.assertEqual(schema[CONF_TTS_ENGINE].default(), OPENAI_ENGINE)
        self.assertIn(CONF_API_KEY, schema)
        self.assertIn(CONF_URL, schema)
        self.assertNotIn(CONF_KOKORO_URL, schema) # Should not be there by default
        self.assertEqual(schema[CONF_MODEL].default, "tts-1") # Default OpenAI model
        self.assertEqual(schema[CONF_VOICE].default, OPENAI_VOICES[0])


    async def test_user_step_select_kokoro_engine(self):
        """Test user step when Kokoro engine is selected, checking schema."""
        flow = OpenAITTSConfigFlow()
        flow.hass = self.hass

        # First, show the form with engine selection
        result = await flow.async_step_user(user_input=None)

        # Now, simulate user selecting Kokoro engine
        user_input_kokoro_selected = {
            CONF_TTS_ENGINE: KOKORO_FASTAPI_ENGINE
        }
        result_kokoro = await flow.async_step_user(user_input_kokoro_selected)

        self.assertEqual(result_kokoro["type"], data_entry_flow.RESULT_TYPE_FORM)
        self.assertEqual(result_kokoro["step_id"], "user")

        schema_kokoro = result_kokoro["data_schema"].schema
        self.assertEqual(schema_kokoro[CONF_TTS_ENGINE].default(), KOKORO_FASTAPI_ENGINE)
        self.assertNotIn(CONF_API_KEY, schema_kokoro) # API key should be hidden
        self.assertNotIn(CONF_URL, schema_kokoro)     # OpenAI URL should be hidden
        self.assertIn(CONF_KOKORO_URL, schema_kokoro)
        self.assertEqual(schema_kokoro[CONF_KOKORO_URL].default, KOKORO_DEFAULT_URL)

        # Model should be disabled and defaulted to KOKORO_MODEL
        self.assertEqual(schema_kokoro[CONF_MODEL].default, KOKORO_MODEL)
        self.assertIsInstance(schema_kokoro[CONF_MODEL], cv.disabled)

        # Voice should be a text field (cv.string) defaulting to the first Kokoro voice
        self.assertEqual(schema_kokoro[CONF_VOICE].default, KOKORO_VOICES[0])
        self.assertIs(schema_kokoro[CONF_VOICE], cv.string) # Check type is string

    async def test_user_step_kokoro_submit_success(self):
        """Test successful submission of Kokoro config."""
        flow = OpenAITTSConfigFlow()
        flow.hass = self.hass

        user_input = {
            CONF_TTS_ENGINE: KOKORO_FASTAPI_ENGINE,
            CONF_KOKORO_URL: "http://my.kokoro.local:8000/tts",
            CONF_MODEL: KOKORO_MODEL, # Although disabled, it might be submitted
            CONF_VOICE: KOKORO_VOICES[1], # e.g., af_alloy
            CONF_SPEED: 1.2,
        }

        # Mock validate_config_input to return no errors for this test
        with patch("custom_components.openai_tts.config_flow.validate_config_input", return_value={}):
            result = await flow.async_step_user(user_input)

        self.assertEqual(result["type"], data_entry_flow.RESULT_TYPE_CREATE_ENTRY)
        self.assertEqual(result["data"][CONF_TTS_ENGINE], KOKORO_FASTAPI_ENGINE)
        self.assertEqual(result["data"][CONF_KOKORO_URL], "http://my.kokoro.local:8000/tts")
        self.assertEqual(result["data"][CONF_MODEL], KOKORO_MODEL) # Should be forced to KOKORO_MODEL
        self.assertEqual(result["data"][CONF_VOICE], KOKORO_VOICES[1])
        self.assertNotIn(CONF_API_KEY, result["data"])
        self.assertNotIn(CONF_URL, result["data"])


    async def test_options_flow_kokoro_defaults_and_dynamic_voice(self):
        """Test options flow for Kokoro: defaults and dynamic voice field."""
        # Initial config data for Kokoro engine
        config_data = {
            CONF_TTS_ENGINE: KOKORO_FASTAPI_ENGINE,
            CONF_KOKORO_URL: KOKORO_DEFAULT_URL,
            CONF_MODEL: KOKORO_MODEL,
            CONF_VOICE: KOKORO_VOICES[0], # Initial voice
        }
        config_entry = MockConfigEntry(data=config_data, options={})

        options_flow = OpenAITTSOptionsFlow()
        options_flow.config_entry = config_entry
        options_flow.hass = self.hass # Assign hass if options flow uses it

        # --- Step 1: Show form with blending OFF (default) ---
        result_form_blend_off = await options_flow.async_step_init(user_input=None)
        self.assertEqual(result_form_blend_off["type"], data_entry_flow.RESULT_TYPE_FORM)
        schema_blend_off = result_form_blend_off["data_schema"].schema

        self.assertEqual(
            schema_blend_off[CONF_KOKORO_CHUNK_SIZE].default,
            DEFAULT_KOKORO_CHUNK_SIZE
        )
        self.assertEqual(
            schema_blend_off[CONF_KOKORO_VOICE_ALLOW_BLENDING].default,
            False
        )
        # Voice should be vol.In (dropdown)
        self.assertIsInstance(schema_blend_off[CONF_VOICE], vol.In)
        self.assertEqual(schema_blend_off[CONF_VOICE].container, KOKORO_VOICES)
        self.assertEqual(schema_blend_off[CONF_VOICE].default, KOKORO_VOICES[0]) # Default from initial config

        # --- Step 2: Simulate user enabling blending ---
        user_input_blend_on = {
            # These are the fields from the schema when blending is OFF
            CONF_KOKORO_VOICE_ALLOW_BLENDING: True, # User enables blending
            CONF_KOKORO_CHUNK_SIZE: DEFAULT_KOKORO_CHUNK_SIZE,
            CONF_VOICE: KOKORO_VOICES[0], # Current voice selection
            # Other common options like speed, instructions etc. would be here too
            CONF_SPEED: 1.0,
        }
        # Re-trigger the form display by providing user_input.
        # The options flow re-evaluates the schema based on this input.
        # Note: The actual saving happens when user_input makes it past validation and `async_create_entry` is called.
        # Here we are testing the form generation *before* final submission.
        # We pass user_input that includes the change to CONF_KOKORO_VOICE_ALLOW_BLENDING
        # to simulate the form being re-rendered after this toggle.

        # To test the dynamic schema, we need to simulate how the options flow would
        # present the form again if a field (like allow_blending) changed *before* submission.
        # This might require manually setting current_allow_blending in the flow for this test step,
        # or ensuring the flow's logic correctly re-evaluates on *any* input.
        # The current OptionsFlow structure re-evaluates schema *after* user_input is processed for saving.
        # Let's test saving options with blending ON.

        # --- Test saving options with blending ON ---
        options_flow_save = OpenAITTSOptionsFlow() # New instance for clean test
        options_flow_save.config_entry = config_entry
        options_flow_save.hass = self.hass

        user_input_to_save_blend_on = {
            CONF_KOKORO_VOICE_ALLOW_BLENDING: True,
            CONF_KOKORO_CHUNK_SIZE: 256,
            CONF_VOICE: "en_us_child,0.5,en_us_military,0.5", # Blended voice string
            CONF_SPEED: 1.1,
        }
        result_save = await options_flow_save.async_step_init(user_input_to_save_blend_on)
        self.assertEqual(result_save["type"], data_entry_flow.RESULT_TYPE_CREATE_ENTRY)
        saved_options = result_save["data"]
        self.assertTrue(saved_options[CONF_KOKORO_VOICE_ALLOW_BLENDING])
        self.assertEqual(saved_options[CONF_KOKORO_CHUNK_SIZE], 256)
        self.assertEqual(saved_options[CONF_VOICE"], "en_us_child,0.5,en_us_military,0.5")

        # --- Now, re-init the options flow with blending ON in existing options to check form ---
        config_entry_blending_on = MockConfigEntry(data=config_data, options=saved_options)
        options_flow_reopen = OpenAITTSOptionsFlow()
        options_flow_reopen.config_entry = config_entry_blending_on
        options_flow_reopen.hass = self.hass

        result_form_blend_on = await options_flow_reopen.async_step_init(user_input=None)
        schema_blend_on = result_form_blend_on["data_schema"].schema
        self.assertTrue(schema_blend_on[CONF_KOKORO_VOICE_ALLOW_BLENDING].default)
        # Voice should be cv.string (text field)
        self.assertIs(schema_blend_on[CONF_VOICE], cv.string)
        self.assertEqual(schema_blend_on[CONF_VOICE].default, "en_us_child,0.5,en_us_military,0.5")


    async def test_options_flow_kokoro_chunk_size_validation(self):
        """Test chunk size validation in Kokoro options flow."""
        config_entry = MockConfigEntry(data={CONF_TTS_ENGINE: KOKORO_FASTAPI_ENGINE}, options={})
        options_flow = OpenAITTSOptionsFlow()
        options_flow.config_entry = config_entry
        options_flow.hass = self.hass

        user_input_invalid_chunk = {
            CONF_KOKORO_CHUNK_SIZE: "not-an-int", # Invalid
            CONF_KOKORO_VOICE_ALLOW_BLENDING: False,
            CONF_VOICE: KOKORO_VOICES[0],
        }
        # For Coerce(int), voluptuous will raise vol.MultipleInvalid.
        # The error message check depends on how your flow translates that.
        # Here, we assume it results in the "invalid_chunk_size" error key.
        # Note: vol.Coerce(int) might raise error before custom validation logic if not a number
        # If it's a number but <=0, then custom validation `errors[CONF_KOKORO_CHUNK_SIZE] = "invalid_chunk_size"` applies

        # Test with zero chunk size
        user_input_zero_chunk = {
            CONF_KOKORO_CHUNK_SIZE: 0,
            CONF_KOKORO_VOICE_ALLOW_BLENDING: False,
            CONF_VOICE: KOKORO_VOICES[0],
        }
        result_zero = await options_flow.async_step_init(user_input_zero_chunk)
        self.assertEqual(result_zero["type"], data_entry_flow.RESULT_TYPE_FORM)
        self.assertEqual(result_zero["errors"][CONF_KOKORO_CHUNK_SIZE], "invalid_chunk_size")


if __name__ == "__main__":
    unittest.main()
