import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.exceptions import HomeAssistantError

# Adjust the import path according to your project structure
from custom_components.openai_tts.openaitts_engine import OpenAITTSEngine
from custom_components.openai_tts.const import (
    KOKORO_MODEL,  # Actual model name for Kokoro
    OPENAI_ENGINE,
    DEFAULT_KOKORO_CHUNK_SIZE, # Added for testing
)

class TestOpenAITTSEngine(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.api_key = "test_api_key"
        self.openai_voice = "alloy"
        self.openai_model = "tts-1" # Example OpenAI model
        self.openai_speed = 1.0
        self.openai_url = "https://api.openai.com/v1/audio/speech"

        self.kokoro_voice = "af_alloy" # Example Kokoro voice
        # self.kokoro_model is KOKORO_MODEL from const now
        self.kokoro_speed = 1.2
        self.kokoro_url = "http://localhost:8002/tts" # Example Kokoro URL

    async def test_init_openai_engine_default_chunk_size(self):
        """Test engine initialization with OpenAI config, chunk_size should be None."""
        engine = OpenAITTSEngine(
            api_key=self.api_key,
            voice=self.openai_voice,
            model=self.openai_model,
            speed=self.openai_speed,
            url=self.openai_url
            # No chunk_size provided, should default to None in __init__
        )
        self.assertIsNotNone(engine._session)
        self.assertEqual(engine._api_key, self.api_key)
        self.assertEqual(engine._url, self.openai_url)
        self.assertIsNone(engine._chunk_size) # Default chunk_size
        await engine.close()

    async def test_init_kokoro_engine_with_chunk_size(self):
        """Test engine initialization with Kokoro config and specific chunk_size."""
        test_chunk_size = 512
        engine = OpenAITTSEngine(
            api_key=None,
            voice=self.kokoro_voice,
            model=KOKORO_MODEL, # Use the constant
            speed=self.kokoro_speed,
            url=self.kokoro_url,
            chunk_size=test_chunk_size
        )
        self.assertIsNotNone(engine._session)
        self.assertIsNone(engine._api_key)
        self.assertEqual(engine._url, self.kokoro_url)
        self.assertEqual(engine._chunk_size, test_chunk_size)
        await engine.close()


    @patch("aiohttp.ClientSession")
    async def test_kokoro_request_with_chunk_size_and_blended_voice(self, MockClientSession):
        """Test Kokoro request includes chunk_size and unmodified blended voice."""
        mock_session_instance = MockClientSession.return_value
        mock_post_response = AsyncMock()
        mock_post_response.status = 200
        mock_post_response.content.iter_any = AsyncMock(return_value=[b"audio_data"])
        mock_session_instance.post = AsyncMock(return_value=mock_post_response)

        blended_voice_str = "af_child(1.5)+af_nova(0.5)"
        test_chunk_size = 256
        engine = OpenAITTSEngine(
            api_key=None,
            voice="this_is_default_voice_should_be_overridden", # Default voice in engine
            model=KOKORO_MODEL, # Important for engine to know it's Kokoro logic
            speed=self.kokoro_speed,
            url=self.kokoro_url,
            chunk_size=test_chunk_size
        )

        text_to_speak = "Hello blended Kokoro"
        # Call get_tts with the blended voice string directly
        async for _ in engine.get_tts(text_to_speak, voice=blended_voice_str):
            pass

        mock_session_instance.post.assert_called_once()
        args, kwargs = mock_session_instance.post.call_args

        self.assertEqual(args[0], self.kokoro_url) # Correct URL
        self.assertNotIn("Authorization", kwargs["headers"]) # No API key

        payload = kwargs["json"]
        self.assertEqual(payload["input"], text_to_speak)
        self.assertEqual(payload["voice"], blended_voice_str) # Blended voice string passed unmodified
        self.assertEqual(payload["model"], KOKORO_MODEL)
        self.assertEqual(payload["chunk_size"], test_chunk_size) # Chunk size included

        await engine.close()

    @patch("aiohttp.ClientSession")
    async def test_kokoro_request_no_chunk_size_if_none(self, MockClientSession):
        """Test Kokoro request does not include chunk_size if it's None."""
        mock_session_instance = MockClientSession.return_value
        mock_post_response = AsyncMock()
        mock_post_response.status = 200
        mock_post_response.content.iter_any = AsyncMock(return_value=[b"audio_data"])
        mock_session_instance.post = AsyncMock(return_value=mock_post_response)

        engine = OpenAITTSEngine(
            api_key=None,
            voice=self.kokoro_voice,
            model=KOKORO_MODEL,
            speed=self.kokoro_speed,
            url=self.kokoro_url,
            chunk_size=None # Explicitly None
        )

        async for _ in engine.get_tts("Test text"):
            pass

        payload = mock_session_instance.post.call_args.kwargs["json"]
        self.assertNotIn("chunk_size", payload)
        await engine.close()


    @patch("aiohttp.ClientSession")
    async def test_openai_request_with_key(self, MockClientSession):
        """Test that OpenAI engine makes requests to the correct URL with API key and no chunk_size."""
        mock_session_instance = MockClientSession.return_value
        mock_post_response = AsyncMock()
        mock_post_response.status = 200
        mock_post_response.content.iter_any = AsyncMock(return_value=[b"chunk1", b"chunk2"])
        mock_session_instance.post = AsyncMock(return_value=mock_post_response)

        engine = OpenAITTSEngine(
            api_key=self.api_key,
            voice=self.openai_voice,
            model=self.openai_model,
            speed=self.openai_speed,
            url=self.openai_url
        )

        text_to_speak = "Hello OpenAI"
        async for _ in engine.get_tts(text_to_speak):
            pass

        mock_session_instance.post.assert_called_once()
        args, kwargs = mock_session_instance.post.call_args
        self.assertEqual(args[0], self.openai_url)
        self.assertIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {self.api_key}")
        self.assertEqual(kwargs["json"]["input"], text_to_speak)
        await engine.close()


    @patch("aiohttp.ClientSession")
    async def test_streaming_success(self, MockClientSession):
        """Test successful streaming of audio chunks."""
        mock_session_instance = MockClientSession.return_value
        mock_post_response = AsyncMock()
        mock_post_response.status = 200
        # Simulate iter_any() behavior
        async def dummy_iter_any():
            yield b"stream_chunk_1"
            yield b"stream_chunk_2"
        mock_post_response.content.iter_any = dummy_iter_any
        mock_session_instance.post = AsyncMock(return_value=mock_post_response)

        engine = OpenAITTSEngine(self.api_key, self.openai_voice, self.openai_model, self.openai_speed, self.openai_url)

        collected_chunks = []
        async for chunk in engine.get_tts("test streaming"):
            collected_chunks.append(chunk)

        self.assertEqual(collected_chunks, [b"stream_chunk_1", b"stream_chunk_2"])
        await engine.close()

    @patch("aiohttp.ClientSession")
    async def test_api_error_handling_streaming(self, MockClientSession):
        """Test API error (ClientResponseError) handling during streaming."""
        mock_session_instance = MockClientSession.return_value
        mock_session_instance.post = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=MagicMock(),
                status=400,
                message="Test API Error"
            )
        )

        engine = OpenAITTSEngine(self.api_key, self.openai_voice, self.openai_model, self.openai_speed, self.openai_url)

        with self.assertRaises(HomeAssistantError) as context:
            async for _ in engine.get_tts("test api error"):
                pass
        self.assertIn("Network error occurred while fetching TTS audio: Test API Error", str(context.exception))
        await engine.close()

    @patch("aiohttp.ClientSession")
    async def test_network_error_handling_streaming(self, MockClientSession):
        """Test general network error (ClientError) handling during streaming."""
        mock_session_instance = MockClientSession.return_value
        mock_session_instance.post = AsyncMock(side_effect=aiohttp.ClientError("Test Network Connection Error"))

        engine = OpenAITTSEngine(self.api_key, self.openai_voice, self.openai_model, self.openai_speed, self.openai_url)

        with self.assertRaises(HomeAssistantError) as context:
            async for _ in engine.get_tts("test network error"):
                pass
        self.assertIn("Network error occurred while fetching TTS audio: Test Network Connection Error", str(context.exception))
        await engine.close()

    @patch("aiohttp.ClientSession")
    async def test_cancelled_error_handling(self, MockClientSession):
        """Test CancelledError propagation."""
        mock_session_instance = MockClientSession.return_value
        mock_session_instance.post = AsyncMock(side_effect=asyncio.CancelledError)

        engine = OpenAITTSEngine(self.api_key, self.openai_voice, self.openai_model, self.openai_speed, self.openai_url)

        with self.assertRaises(asyncio.CancelledError):
            async for _ in engine.get_tts("test cancellation"):
                pass
        # Note: We don't call await engine.close() here as the operation was cancelled.
        # Depending on how session is managed, it might be closed by a higher level or GC.
        # For this test, we confirm CancelledError propagates.
        # If there's a specific cleanup expected even on cancellation, that needs testing.
        # Manually close if necessary for subsequent tests if session is reused by test runner
        if engine._session and not engine._session.closed:
             await engine._session.close()


    @patch("aiohttp.ClientSession")
    async def test_close_method(self, MockClientSession):
        """Test that the close method correctly closes the aiohttp session."""
        mock_session_instance = MockClientSession.return_value
        mock_session_instance.close = AsyncMock() # Make close an AsyncMock

        engine = OpenAITTSEngine(self.api_key, self.openai_voice, self.openai_model, self.openai_speed, self.openai_url)
        await engine.close()

        mock_session_instance.close.assert_called_once()

if __name__ == '__main__':
    unittest.main()
