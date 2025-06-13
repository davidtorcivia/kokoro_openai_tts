"""
Constants for OpenAI TTS custom component
"""

DOMAIN = "openai_tts"
CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_VOICE = "voice"
CONF_SPEED = "speed"
CONF_URL = "url"
UNIQUE_ID = "unique_id"

# Engine selection
CONF_TTS_ENGINE = "tts_engine"
OPENAI_ENGINE = "openai"
KOKORO_FASTAPI_ENGINE = "kokoro_fastapi"
TTS_ENGINES = [OPENAI_ENGINE, KOKORO_FASTAPI_ENGINE]
DEFAULT_TTS_ENGINE = OPENAI_ENGINE

# Kokoro specific
CONF_KOKORO_URL = "kokoro_url"
KOKORO_DEFAULT_URL = "http://localhost:8880/v1/audio/speech"
KOKORO_MODEL = "kokoro" # Fixed model name for Kokoro
CONF_KOKORO_CHUNK_SIZE = "kokoro_chunk_size"
DEFAULT_KOKORO_CHUNK_SIZE = 400 # Based on Kokoro FastAPI README example
CONF_KOKORO_VOICE_ALLOW_BLENDING = "kokoro_voice_allow_blending"

KOKORO_VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jadzia", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "af_v0", "af_v0bella", "af_v0irulan", "af_v0nicole", "af_v0sarah", "af_v0sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa", "am_v0adam", "am_v0gurney", "am_v0michael",
    "bf_alice", "bf_emma", "bf_lily", "bf_v0emma", "bf_v0isabella",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "bm_v0george", "bm_v0lewis",
    "ef_dora", "em_alex", "em_santa", "ff_siwis", "hf_alpha", "hf_beta",
    "hm_omega", "hm_psi", "if_sara", "im_nicola", "jf_alpha", "jf_gongitsune",
    "jf_nezumi", "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian",
    "zm_yunxi", "zm_yunxia", "zm_yunyang",
]


MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"] # Note: gpt-4o-mini-tts may be custom
# Global OpenAI voices, KOKORO_VOICES are separate
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]


CONF_CHIME_ENABLE = "chime"
CONF_CHIME_SOUND = "chime_sound"
CONF_NORMALIZE_AUDIO = "normalize_audio"
CONF_INSTRUCTIONS = "instructions"
