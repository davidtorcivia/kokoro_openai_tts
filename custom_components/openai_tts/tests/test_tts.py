import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

# Adjust import paths as necessary
from custom_components.openai_tts.tts import OpenAITTSEntity, async_setup_entry
from custom_components.openai_tts.openaitts_engine import OpenAITTSEngine
from custom_components.openai_tts.const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_VOICE,
    CONF_SPEED,
    CONF_URL,
    CONF_TTS_ENGINE,
    OPENAI_ENGINE,
    KOKORO_FASTAPI_ENGINE,
    CONF_KOKORO_URL,
    KOKORO_MODEL,
    UNIQUE_ID,
    CONF_KOKORO_CHUNK_SIZE,
    DEFAULT_KOKORO_CHUNK_SIZE,
    CONF_CHIME_ENABLE, # Added for testing warning
    CONF_NORMALIZE_AUDIO, # Added for testing warning
    # CONF_KOKORO_VOICE_ALLOW_BLENDING not directly tested here, but in config_flow tests
)
from homeassistant.components import media_source # Added
import hashlib # Added
from urllib.parse import quote # Added
from custom_components.openai_tts.tts import STREAMING_VIEW_URL # Added


# Minimal HomeAssistant mock
class MockHomeAssistant(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data = {}
        # Mock async_add_executor_job to run functions directly for simplicity in these tests
        # For more complex scenarios, you might need a proper event loop and executor.
        self.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))


class TestOpenAITTSEntity(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.hass = MockHomeAssistant()

        self.openai_config_data = {
            CONF_TTS_ENGINE: OPENAI_ENGINE,
            CONF_API_KEY: "fake_openai_key",
            CONF_URL: "https://api.openai.com/v1/audio/speech",
            CONF_MODEL: "tts-1",
            CONF_VOICE: "alloy",
            CONF_SPEED: 1.0,
            UNIQUE_ID: "openai-test-unique-id"
        }
        self.kokoro_config_data = {
            CONF_TTS_ENGINE: KOKORO_FASTAPI_ENGINE,
            CONF_KOKORO_URL: "http://localhost:8002/tts",
            CONF_MODEL: KOKORO_MODEL, # Use the constant for consistency
            CONF_VOICE: "af_alloy", # Example Kokoro voice
            CONF_SPEED: 1.0,
            UNIQUE_ID: "kokoro-test-unique-id",
            # No API key for Kokoro in this test setup
        }
        self.mock_engine = AsyncMock(spec=OpenAITTSEngine)
        # Default title for config entry, can be overridden in tests
        self.config_entry_title = "Test TTS Config"


    def _setup_entity(self, config_data: dict) -> OpenAITTSEntity:
        """Helper to create an entity instance with mocked ConfigEntry and engine."""
        mock_config_entry = MagicMock(spec=ConfigEntry)
        mock_config_entry.data = config_data
        mock_config_entry.options = {} # Start with empty options
        # Mock the title property of the config_entry
        type(mock_config_entry).title = PropertyMock(return_value=self.config_entry_title)

        # The engine is now created inside async_setup_entry, so we patch OpenAITTSEngine directly
        # or we can pass a pre-mocked engine if we refactor entity creation slightly for tests
        # For now, let's assume we pass the engine in if testing entity methods directly.
        # If testing async_setup_entry, we'd patch the engine's constructor.

        entity = OpenAITTSEntity(self.hass, mock_config_entry, self.mock_engine)
        return entity

    async def test_device_info_openai(self):
        """Test device_info for OpenAI configuration."""
        self.config_entry_title = "OpenAI TTS tts-1" # Match expected name format
        entity = self._setup_entity(self.openai_config_data)
        device_info = entity.device_info
        self.assertEqual(device_info["manufacturer"], "OpenAI")
        self.assertEqual(device_info["model"], self.openai_config_data[CONF_MODEL])
        self.assertEqual(device_info["name"], self.config_entry_title)


    async def test_device_info_kokoro(self):
        """Test device_info for Kokoro FastAPI configuration."""
        self.config_entry_title = f"Kokoro FastAPI TTS {KOKORO_MODEL}"
        entity = self._setup_entity(self.kokoro_config_data)
        device_info = entity.device_info
        self.assertEqual(device_info["manufacturer"], "Kokoro FastAPI")
        self.assertEqual(device_info["model"], KOKORO_MODEL) # Check against constant
        self.assertEqual(device_info["name"], self.config_entry_title)

    async def test_name_property_openai(self):
        """Test name property for OpenAI configuration."""
        self.config_entry_title = "OpenAI TTS tts-1"
        entity = self._setup_entity(self.openai_config_data)
        self.assertEqual(entity.name, self.config_entry_title)

    async def test_name_property_kokoro(self):
        """Test name property for Kokoro FastAPI configuration."""
        self.config_entry_title = f"Kokoro FastAPI TTS {KOKORO_MODEL}"
        entity = self._setup_entity(self.kokoro_config_data)
        self.assertEqual(entity.name, self.config_entry_title)

    async def test_async_get_tts_audio_kokoro_blended_voice(self):
        """Test audio streaming with Kokoro and a blended voice string."""
        blended_voice_str = "af_child(0.7)+af_nova(0.3)"
        kokoro_config_with_options = self.kokoro_config_data.copy()

        entity = self._setup_entity(kokoro_config_with_options)
        # Simulate that the blended voice is set in options by the user
        entity._config.options = {CONF_VOICE: blended_voice_str}

        test_audio_chunks = [b"Blended", b" ", b"Audio"]
        async def mock_stream_audio(text, voice, **kwargs): # Capture voice arg
            self.assertEqual(voice, blended_voice_str) # Assert blended voice is passed
            for chunk in test_audio_chunks:
                yield chunk
        self.mock_engine.get_tts = mock_stream_audio

        fmt, audio_data = await entity.async_get_tts_audio("Test blended audio", "en-US", options={})

        self.assertEqual(fmt, "mp3")
        self.assertEqual(audio_data, b"Blended Audio")
        self.mock_engine.get_tts.assert_called_once() # More detailed args check in mock_stream_audio


    @patch("subprocess.run")
    async def test_async_get_tts_audio_with_ffmpeg_processing(self, mock_subprocess_run):
        """Test audio streaming with ffmpeg (chime/normalization) correctly called."""
        # Setup mock for subprocess.run
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")

        # Enable chime to trigger ffmpeg processing
        entity = self._setup_entity(self.kokoro_config_data)
        entity._config.options = { # Simulate options being set
            "chime": True,
            "chime_sound": "threetone.mp3",
            "normalize_audio": True
        }

        test_audio_chunks = [b"raw_audio_chunk1", b"raw_audio_chunk2"]
        expected_raw_audio = b"raw_audio_chunk1raw_audio_chunk2"

        async def mock_stream_audio(*args, **kwargs):
            for chunk in test_audio_chunks:
                yield chunk
        self.mock_engine.get_tts = mock_stream_audio

        # Mock tempfile operations
        mock_temp_file_tts = MagicMock()
        mock_temp_file_tts.name = "/tmp/fake_tts.mp3"
        mock_temp_file_tts.__enter__.return_value = mock_temp_file_tts # For 'with' statement

        mock_temp_file_merged = MagicMock()
        mock_temp_file_merged.name = "/tmp/fake_merged.mp3"
        mock_temp_file_merged.__enter__.return_value = mock_temp_file_merged

        # Patch tempfile.NamedTemporaryFile and open
        with patch("tempfile.NamedTemporaryFile", side_effect=[mock_temp_file_tts, mock_temp_file_merged]) as mock_tempfile_creator, \
             patch("builtins.open", MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"processed_audio")))) as mock_open, \
             patch("os.path.join", MagicMock(return_value="/mock/path/to/chime.mp3")), \
             patch("os.path.dirname", MagicMock(return_value="/mock/path")), \
             patch("os.remove") as mock_os_remove:

            fmt, audio_data = await entity.async_get_tts_audio("Test message", "en-US", options={})

            self.assertEqual(fmt, "mp3")
            self.assertEqual(audio_data, b"processed_audio") # Audio comes from mocked open after ffmpeg

            # Check that tempfile.NamedTemporaryFile was called to create tts and merged files
            self.assertEqual(mock_tempfile_creator.call_count, 2)

            # Check that tts_file.write was called with the concatenated raw audio
            mock_temp_file_tts.write.assert_called_once_with(expected_raw_audio)

            # Check that hass.async_add_executor_job was used for subprocess.run
            self.hass.async_add_executor_job.assert_called()
            # Check that subprocess.run was called (args depend on chime/norm options)
            mock_subprocess_run.assert_called()
            # Check that temp files were removed
            self.assertGreaterEqual(mock_os_remove.call_count, 2)


    async def test_async_get_tts_audio_engine_error(self):
        """Test error handling when the TTS engine's get_tts fails."""
        entity = self._setup_entity(self.openai_config_data)
        self.mock_engine.get_tts = AsyncMock(side_effect=HomeAssistantError("Engine failed"))

        fmt, audio_data = await entity.async_get_tts_audio("Test error", "en-US", options={})

        self.assertIsNone(fmt)
        self.assertIsNone(audio_data)
        # Add log check if possible/needed: _LOGGER.exception("Unknown error in get_tts_audio")

    async def test_async_will_remove_from_hass(self):
        """Test that async_will_remove_from_hass calls engine.close()."""
        entity = self._setup_entity(self.openai_config_data)
        self.mock_engine.close = AsyncMock() # Ensure close is an AsyncMock

        await entity.async_will_remove_from_hass()
        self.mock_engine.close.assert_called_once()

    @patch('custom_components.openai_tts.tts.get_url') # Mock get_url
    @patch('custom_components.openai_tts.tts._LOGGER') # Mock logger
    async def test_async_get_tts_audio_media_source_requested(self, mock_logger, mock_get_url):
        """Test get_tts_audio returns PlayMedia when media_source option is true."""
        mock_get_url.return_value = "http://hass_base_url" # Mock base URL

        entity = self._setup_entity(self.openai_config_data)
        entity.entity_id = "tts.test_openai_tts_entity" # Set a mock entity_id for URL generation

        message = "Hello streaming world"
        options = {media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID: True}

        # Mock engine's get_tts to avoid actual API call, not strictly needed for URL gen but good practice
        async def dummy_audio_stream(*args, **kwargs):
            yield b"dummy"
        self.mock_engine.get_tts = dummy_audio_stream

        result = await entity.async_get_tts_audio(message, "en-US", options=options)

        self.assertIsInstance(result, media_source.PlayMedia)
        self.assertEqual(result.mime_type, "audio/mpeg")

        message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
        expected_path = STREAMING_VIEW_URL.format(entity_id=entity.entity_id, message_hash=message_hash)
        expected_url = f"http://hass_base_url{expected_path}?message={quote(message)}"
        self.assertEqual(result.url, expected_url)

        # Test warning log if chime or normalization is enabled
        entity._config.options = {CONF_CHIME_ENABLE: True}
        await entity.async_get_tts_audio(message, "en-US", options=options)
        mock_logger.warning.assert_called_with(
            "Chime and/or normalization are enabled but will be bypassed for media_source streaming."
        )
        mock_logger.reset_mock() # Reset for next assertion

        entity._config.options = {CONF_NORMALIZE_AUDIO: True}
        await entity.async_get_tts_audio(message, "en-US", options=options)
        mock_logger.warning.assert_called_with(
            "Chime and/or normalization are enabled but will be bypassed for media_source streaming."
        )

    async def test_async_get_tts_audio_fallback_to_bytes(self):
        """Test get_tts_audio falls back to returning bytes when media_source is not requested."""
        entity = self._setup_entity(self.openai_config_data)

        test_audio_chunks = [b"Hello", b" ", b"World"]
        async def mock_stream_audio(*args, **kwargs):
            for chunk in test_audio_chunks:
                yield chunk
        self.mock_engine.get_tts = mock_stream_audio

        # Case 1: media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID is False
        options_false = {media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID: False}
        fmt, audio_data = await entity.async_get_tts_audio("Test message", "en-US", options=options_false)
        self.assertEqual(fmt, "mp3")
        self.assertEqual(audio_data, b"Hello World")

        # Case 2: media_source.TTS_SPEAK_OPTIONS_KEY_MEDIA_SOURCE_ID is not in options
        options_absent = {}
        fmt_absent, audio_data_absent = await entity.async_get_tts_audio("Test message", "en-US", options=options_absent)
        self.assertEqual(fmt_absent, "mp3")
        self.assertEqual(audio_data_absent, b"Hello World")


    @patch('custom_components.openai_tts.tts.OpenAITTSEngine')
    async def test_async_setup_entry_kokoro_with_chunk_size_option(self, MockOpenAITTSEngineConstructor):
        """Test async_setup_entry for Kokoro with chunk_size in options."""
        mock_engine_instance = MockOpenAITTSEngineConstructor.return_value
        self.hass.data[DOMAIN] = {}

        test_chunk_size = 300
        kokoro_config_with_options = self.kokoro_config_data.copy()
        # Simulate chunk_size being set in options (e.g., by user via UI)
        mock_config_entry = MagicMock(spec=ConfigEntry)
        mock_config_entry.data = kokoro_config_with_options
        mock_config_entry.options = {CONF_KOKORO_CHUNK_SIZE: test_chunk_size}

        async_add_entities_mock = MagicMock()

        await async_setup_entry(self.hass, mock_config_entry, async_add_entities_mock)

        MockOpenAITTSEngineConstructor.assert_called_once_with(
            api_key=None,
            voice=kokoro_config_with_options[CONF_VOICE],
            model=KOKORO_MODEL, # Ensure it uses the fixed KOKORO_MODEL
            speed=kokoro_config_with_options[CONF_SPEED],
            url=kokoro_config_with_options[CONF_KOKORO_URL],
            chunk_size=test_chunk_size # Verify chunk_size is passed
        )
        async_add_entities_mock.assert_called_once()

    @patch('custom_components.openai_tts.tts.OpenAITTSEngine')
    async def test_async_setup_entry_kokoro_default_chunk_size(self, MockOpenAITTSEngineConstructor):
        """Test async_setup_entry for Kokoro with default chunk_size (from const)."""
        mock_engine_instance = MockOpenAITTSEngineConstructor.return_value
        self.hass.data[DOMAIN] = {}

        # No chunk_size in data or options, should use DEFAULT_KOKORO_CHUNK_SIZE
        mock_config_entry = MagicMock(spec=ConfigEntry)
        mock_config_entry.data = self.kokoro_config_data
        mock_config_entry.options = {} # No options set

        async_add_entities_mock = MagicMock()

        await async_setup_entry(self.hass, mock_config_entry, async_add_entities_mock)

        MockOpenAITTSEngineConstructor.assert_called_once_with(
            api_key=None,
            voice=self.kokoro_config_data[CONF_VOICE],
            model=KOKORO_MODEL,
            speed=self.kokoro_config_data[CONF_SPEED],
            url=self.kokoro_config_data[CONF_KOKORO_URL],
            chunk_size=DEFAULT_KOKORO_CHUNK_SIZE # Verify default chunk_size
        )
        async_add_entities_mock.assert_called_once()


    @patch('custom_components.openai_tts.tts.OpenAITTSEngine')
    async def test_async_setup_entry_openai_no_chunk_size(self, MockOpenAITTSEngineConstructor):
        """Test async_setup_entry for OpenAI configuration."""
        mock_engine_instance = MockOpenAITTSEngineConstructor.return_value
        self.hass.data[DOMAIN] = {}

        mock_config_entry = MagicMock(spec=ConfigEntry)
        mock_config_entry.data = self.openai_config_data
        mock_config_entry.options = {}

        async_add_entities_mock = MagicMock()

        await async_setup_entry(self.hass, mock_config_entry, async_add_entities_mock)

        MockOpenAITTSEngineConstructor.assert_called_once_with(
            api_key=self.openai_config_data[CONF_API_KEY],
            voice=self.openai_config_data[CONF_VOICE],
            model=self.openai_config_data[CONF_MODEL],
            speed=self.openai_config_data[CONF_SPEED],
            url=self.openai_config_data[CONF_URL]
        )
        async_add_entities_mock.assert_called_once()

# Need aiohttp.web for mocking request/response in view tests
import aiohttp.web

# Test class for the OpenAITTSStreamingView
class TestOpenAITTSStreamingView(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.hass = MockHomeAssistant()
        self.mock_engine = AsyncMock(spec=OpenAITTSEngine)

        self.mock_config_entry = MagicMock(spec=ConfigEntry)
        # Provide default data and options that the view might access
        self.mock_config_entry.data = {
            CONF_VOICE: "alloy", # Default voice from data
            CONF_SPEED: 1.0,   # Default speed from data
            # Add other fields if your view's logic depends on them from data
        }
        self.mock_config_entry.options = {
            # Options can override data, e.g., if user configured differently
            # CONF_VOICE: "echo",
            # CONF_SPEED: 1.2,
        }


        from custom_components.openai_tts.tts import OpenAITTSStreamingView # Import here
        self.view = OpenAITTSStreamingView(self.hass, self.mock_engine, self.mock_config_entry)

    async def test_view_get_successful_stream(self):
        """Test successful streaming from the view."""
        test_audio_chunks = [b"chunk1", b"chunk2", b"chunk3"]

        # Configure the mock engine to return our test chunks
        async def mock_engine_tts_stream(*args, **kwargs):
            for chunk in test_audio_chunks:
                yield chunk
        self.mock_engine.get_tts = mock_engine_tts_stream

        # Mock aiohttp.web.Request
        mock_request = MagicMock(spec=aiohttp.web.Request)
        mock_request.query = {"message": "Test stream message"} # Message passed via query

        # Mock aiohttp.web.StreamResponse
        # We need to mock its methods like prepare, write, write_eof
        mock_stream_response_instance = AsyncMock(spec=aiohttp.web.StreamResponse)
        mock_stream_response_instance.headers = {} # Initialize headers attribute

        # Patch the StreamResponse constructor to return our mock instance
        with patch("aiohttp.web.StreamResponse", return_value=mock_stream_response_instance) as MockStreamResponseCls:

            response_from_view = await self.view.get(mock_request, "test_entity_id", "test_message_hash")

            MockStreamResponseCls.assert_called_once() # Verify constructor was called

            # Check headers set on the response instance
            self.assertEqual(mock_stream_response_instance.content_type, "audio/mpeg")
            self.assertEqual(mock_stream_response_instance.headers['Cache-Control'], 'no-cache, no-store, must-revalidate')

            # Check methods called on the response instance
            mock_stream_response_instance.prepare.assert_called_once_with(mock_request)

            self.assertEqual(mock_stream_response_instance.write.call_count, len(test_audio_chunks))
            for i, chunk in enumerate(test_audio_chunks):
                self.assertEqual(mock_stream_response_instance.write.call_args_list[i][0][0], chunk)

            mock_stream_response_instance.write_eof.assert_called_once()
            self.assertEqual(response_from_view, mock_stream_response_instance)

    async def test_view_get_missing_message_parameter(self):
        """Test view response when 'message' query parameter is missing."""
        mock_request = MagicMock(spec=aiohttp.web.Request)
        mock_request.query = {} # 'message' parameter is missing

        # We expect a plain aiohttp.web.Response, not StreamResponse, for this error
        with patch("aiohttp.web.Response", spec=aiohttp.web.Response) as MockPlainResponseCls:
            # Call the view's get method
            await self.view.get(mock_request, "test_entity_id", "test_message_hash")
            # Assert that aiohttp.web.Response was called with status 400
            MockPlainResponseCls.assert_called_once_with(status=400, text="Missing 'message' query parameter")

    @patch('custom_components.openai_tts.tts._LOGGER')
    async def test_view_get_engine_error_before_stream_prepare(self, mock_logger):
        """Test view handling when the TTS engine raises an error before stream preparation."""
        self.mock_engine.get_tts.side_effect = HomeAssistantError("Engine TTS pre-stream failure")

        mock_request = MagicMock(spec=aiohttp.web.Request)
        mock_request.query = {"message": "Test error case"}

        # Mock StreamResponse, but its methods shouldn't be called if error is early
        mock_stream_response_instance = AsyncMock(spec=aiohttp.web.StreamResponse)
        mock_stream_response_instance.headers = {}
        mock_stream_response_instance.prepared = False # Simulate headers not yet sent

        with patch("aiohttp.web.StreamResponse", return_value=mock_stream_response_instance):
            # We expect the HomeAssistantError to propagate if it happens before response.prepare
            # Or, if the view catches it and returns a 500, we'd test for that.
            # Based on current view code, it re-raises if response.prepared is False.
            with self.assertRaises(HomeAssistantError):
                 await self.view.get(mock_request, "test_entity_id", "test_message_hash")

            mock_logger.exception.assert_called() # Check that an error was logged
            mock_stream_response_instance.prepare.assert_not_called() # Stream should not have been prepared

    @patch('custom_components.openai_tts.tts._LOGGER')
    async def test_view_get_cancelled_error_during_streaming(self, mock_logger):
        """Test view handling for CancelledError during streaming."""
        # Simulate CancelledError after some chunks have been sent
        test_audio_chunks = [b"chunk1", b"cancelled_after_this"]
        async def mock_engine_tts_cancel(*args, **kwargs):
            yield test_audio_chunks[0]
            yield test_audio_chunks[1]
            raise asyncio.CancelledError("Stream cancelled by client")
        self.mock_engine.get_tts = mock_engine_tts_cancel

        mock_request = MagicMock(spec=aiohttp.web.Request)
        mock_request.query = {"message": "Test cancellation"}

        mock_stream_response_instance = AsyncMock(spec=aiohttp.web.StreamResponse)
        mock_stream_response_instance.headers = {}

        with patch("aiohttp.web.StreamResponse", return_value=mock_stream_response_instance):
            with self.assertRaises(asyncio.CancelledError): # Expect CancelledError to propagate
                await self.view.get(mock_request, "test_entity_id", "test_message_hash")

            mock_stream_response_instance.prepare.assert_called_once_with(mock_request)
            # Check that write was called for chunks before cancellation
            self.assertEqual(mock_stream_response_instance.write.call_count, len(test_audio_chunks))
            mock_stream_response_instance.write_eof.assert_not_called() # EOF should not be sent
            mock_logger.debug.assert_called_with(
                "Streaming TTS request cancelled by client for entity_id: %s, message_hash: %s",
                "test_entity_id", "test_message_hash"
            )

if __name__ == '__main__':
    unittest.main()
