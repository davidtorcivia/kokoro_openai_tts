"""End to end: boot Home Assistant with this integration, set it up through the config flow, and stream speech
through HA's TTS pipeline to FLAC (the format a Voice PE asks for). Kokoro is replaced by a small HTTP server
that answers with real ffmpeg-made MP3s, each starting with an ID3 tag as Kokoro's do."""
import asyncio
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

from aiohttp import web
from homeassistant import bootstrap, runner
from homeassistant.components import tts

REPO = Path(__file__).resolve().parents[3]
STREAM_OPTIONS = {"preferred_format": "flac", "preferred_sample_rate": 48000, "preferred_sample_channels": 1}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mp3(seconds: float) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=d={seconds}", "-f", "mp3", "-"],
                          check=True, capture_output=True).stdout


def decode(audio: bytes) -> tuple[float, float]:
    """Seconds and mean volume (dB) of `audio`; fails on any decoder error."""
    out = subprocess.run(["ffmpeg", "-i", "-", "-af", "volumedetect", "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                         input=audio, capture_output=True)
    assert out.returncode == 0, out.stderr
    volume = float(out.stderr.decode().split("mean_volume: ")[1].split(" dB")[0])
    return len(out.stdout) / 2 / 48000, volume


async def run() -> None:
    requests: list[dict] = []
    first_request = asyncio.Event()

    async def speech(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        requests.append(body)
        first_request.set()
        audio = await asyncio.to_thread(mp3, 1.0)
        response = web.StreamResponse()
        await response.prepare(request)
        for piece in (audio[:4], audio[4:20], audio[20:]):   # the ID3 header arrives split across chunks
            await response.write(piece)
        return response

    app = web.Application()
    app.router.add_post("/v1/audio/speech", speech)
    server = web.AppRunner(app)
    await server.setup()
    kokoro_port = free_port()
    await web.TCPSite(server, "127.0.0.1", kokoro_port).start()

    config_dir = Path(tempfile.mkdtemp())
    shutil.copytree(REPO / "custom_components", config_dir / "custom_components")
    (config_dir / "configuration.yaml").write_text(f"http:\n  server_port: {free_port()}\n")
    hass = await bootstrap.async_setup_hass(runner.RuntimeConfig(config_dir=str(config_dir), skip_pip=True))
    await hass.async_start()
    try:
        flow = await hass.config_entries.flow.async_init("openai_tts", context={"source": "user"})
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"tts_engine": "kokoro_fastapi"})
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {
            "kokoro_url": f"http://127.0.0.1:{kokoro_port}/v1/audio/speech", "voice": "bf_lily"})
        assert flow["type"] == "create_entry", flow
        entry = flow["result"]
        await hass.async_block_till_done()

        # Streaming: each sentence goes to Kokoro as soon as the reply text completes it.
        async def reply():
            yield "It is currently sunny and sev"
            yield "enty degrees outside. "
            await asyncio.wait_for(first_request.wait(), 10)   # spoken before the rest of the reply exists
            yield "The evening should cool to a pleasant fifty eight."

        stream = tts.async_create_stream(hass, "tts.openai_tts_kokoro", "en", STREAM_OPTIONS)
        assert stream.supports_streaming_input
        stream.async_set_message_stream(reply())
        audio = b"".join([chunk async for chunk in stream.async_stream_result()])
        assert [r["input"] for r in requests] == ["It is currently sunny and seventy degrees outside.",
                                                  "The evening should cool to a pleasant fifty eight."], requests
        # No audio lost where the clips join (a mid-stream ID3 tag costs a frame there).
        one_clip, quiet = decode(mp3(1.0))
        seconds, _ = decode(audio)
        assert abs(seconds - 2 * one_clip) < 0.005, (seconds, one_clip)

        # Normalization needs the whole clip: one request, run through ffmpeg loudnorm. The chunk size is only
        # read when the engine is built, so its new value proves the options change reloaded the entry.
        requests.clear()
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"normalize_audio": True, "kokoro_chunk_size": 123})
        assert flow["type"] == "create_entry", flow
        await hass.async_block_till_done()
        stream = tts.async_create_stream(hass, "tts.openai_tts_kokoro", "en", STREAM_OPTIONS)
        stream.async_set_message("First sentence of a normalized reply. Second sentence.")
        audio = b"".join([chunk async for chunk in stream.async_stream_result()])
        assert [(r["input"], r["chunk_size"]) for r in requests] == [
            ("First sentence of a normalized reply. Second sentence.", 123)], requests
        seconds, volume = decode(audio)
        assert abs(seconds - one_clip) < 0.05 and volume > quiet + 3, (seconds, volume, quiet)
    finally:
        await hass.async_stop()
        await server.cleanup()
        shutil.rmtree(config_dir, ignore_errors=True)


def test_e2e() -> None:
    asyncio.run(run())
