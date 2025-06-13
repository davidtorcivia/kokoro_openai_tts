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
    "af_heart", "af_alloy", "af_echo", "af_fable", "af_onyx", "af_nova", "af_shimmer", "af_nova_dip", "af_radio", "af_crate",
    "ar_heart", "ar_alloy", "ar_echo", "ar_fable", "ar_onyx", "ar_nova", "ar_shimmer", "ar_nova_dip", "ar_radio", "ar_crate",
    "bg_heart", "bg_alloy", "bg_echo", "bg_fable", "bg_onyx", "bg_nova", "bg_shimmer", "bg_nova_dip", "bg_radio", "bg_crate",
    "bn_heart", "bn_alloy", "bn_echo", "bn_fable", "bn_onyx", "bn_nova", "bn_shimmer", "bn_nova_dip", "bn_radio", "bn_crate",
    "ca_heart", "ca_alloy", "ca_echo", "ca_fable", "ca_onyx", "ca_nova", "ca_shimmer", "ca_nova_dip", "ca_radio", "ca_crate",
    "cs_heart", "cs_alloy", "cs_echo", "cs_fable", "cs_onyx", "cs_nova", "cs_shimmer", "cs_nova_dip", "cs_radio", "cs_crate",
    "da_heart", "da_alloy", "da_echo", "da_fable", "da_onyx", "da_nova", "da_shimmer", "da_nova_dip", "da_radio", "da_crate",
    "de_heart", "de_alloy", "de_echo", "de_fable", "de_onyx", "de_nova", "de_shimmer", "de_nova_dip", "de_radio", "de_crate", "de_creep", "de_child", "de_franken", "de_robot", "de_zombie", "de_santa",
    "el_heart", "el_alloy", "el_echo", "el_fable", "el_onyx", "el_nova", "el_shimmer", "el_nova_dip", "el_radio", "el_crate",
    "es_heart", "es_alloy", "es_echo", "es_fable", "es_onyx", "es_nova", "es_shimmer", "es_nova_dip", "es_radio", "es_crate", "es_creep", "es_child", "es_franken", "es_robot", "es_zombie", "es_santa",
    "fi_heart", "fi_alloy", "fi_echo", "fi_fable", "fi_onyx", "fi_nova", "fi_shimmer", "fi_nova_dip", "fi_radio", "fi_crate",
    "fr_heart", "fr_alloy", "fr_echo", "fr_fable", "fr_onyx", "fr_nova", "fr_shimmer", "fr_nova_dip", "fr_radio", "fr_crate", "fr_creep", "fr_child", "fr_franken", "fr_robot", "fr_zombie", "fr_santa",
    "he_heart", "he_alloy", "he_echo", "he_fable", "he_onyx", "he_nova", "he_shimmer", "he_nova_dip", "he_radio", "he_crate",
    "hi_heart", "hi_alloy", "hi_echo", "hi_fable", "hi_onyx", "hi_nova", "hi_shimmer", "hi_nova_dip", "hi_radio", "hi_crate",
    "hu_heart", "hu_alloy", "hu_echo", "hu_fable", "hu_onyx", "hu_nova", "hu_shimmer", "hu_nova_dip", "hu_radio", "hu_crate",
    "id_heart", "id_alloy", "id_echo", "id_fable", "id_onyx", "id_nova", "id_shimmer", "id_nova_dip", "id_radio", "id_crate",
    "it_heart", "it_alloy", "it_echo", "it_fable", "it_onyx", "it_nova", "it_shimmer", "it_nova_dip", "it_radio", "it_crate", "it_creep", "it_child", "it_franken", "it_robot", "it_zombie", "it_santa",
    "ja_heart", "ja_alloy", "ja_echo", "ja_fable", "ja_onyx", "ja_nova", "ja_shimmer", "ja_nova_dip", "ja_radio", "ja_crate", "ja_creep", "ja_child", "ja_franken", "ja_robot", "ja_zombie", "ja_santa",
    "ko_heart", "ko_alloy", "ko_echo", "ko_fable", "ko_onyx", "ko_nova", "ko_shimmer", "ko_nova_dip", "ko_radio", "ko_crate", "ko_creep", "ko_child", "ko_franken", "ko_robot", "ko_zombie", "ko_santa",
    "nl_heart", "nl_alloy", "nl_echo", "nl_fable", "nl_onyx", "nl_nova", "nl_shimmer", "nl_nova_dip", "nl_radio", "nl_crate", "nl_creep", "nl_child", "nl_franken", "nl_robot", "nl_zombie", "nl_santa",
    "no_heart", "no_alloy", "no_echo", "no_fable", "no_onyx", "no_nova", "no_shimmer", "no_nova_dip", "no_radio", "no_crate",
    "pl_heart", "pl_alloy", "pl_echo", "pl_fable", "pl_onyx", "pl_nova", "pl_shimmer", "pl_nova_dip", "pl_radio", "pl_crate", "pl_creep", "pl_child", "pl_franken", "pl_robot", "pl_zombie", "pl_santa",
    "pt_heart", "pt_alloy", "pt_echo", "pt_fable", "pt_onyx", "pt_nova", "pt_shimmer", "pt_nova_dip", "pt_radio", "pt_crate", "pt_creep", "pt_child", "pt_franken", "pt_robot", "pt_zombie", "pt_santa",
    "ro_heart", "ro_alloy", "ro_echo", "ro_fable", "ro_onyx", "ro_nova", "ro_shimmer", "ro_nova_dip", "ro_radio", "ro_crate",
    "ru_heart", "ru_alloy", "ru_echo", "ru_fable", "ru_onyx", "ru_nova", "ru_shimmer", "ru_nova_dip", "ru_radio", "ru_crate", "ru_creep", "ru_child", "ru_franken", "ru_robot", "ru_zombie", "ru_santa",
    "sk_heart", "sk_alloy", "sk_echo", "sk_fable", "sk_onyx", "sk_nova", "sk_shimmer", "sk_nova_dip", "sk_radio", "sk_crate",
    "sv_heart", "sv_alloy", "sv_echo", "sv_fable", "sv_onyx", "sv_nova", "sv_shimmer", "sv_nova_dip", "sv_radio", "sv_crate",
    "th_heart", "th_alloy", "th_echo", "th_fable", "th_onyx", "th_nova", "th_shimmer", "th_nova_dip", "th_radio", "th_crate",
    "tr_heart", "tr_alloy", "tr_echo", "tr_fable", "tr_onyx", "tr_nova", "tr_shimmer", "tr_nova_dip", "tr_radio", "tr_crate",
    "uk_heart", "uk_alloy", "uk_echo", "uk_fable", "uk_onyx", "uk_nova", "uk_shimmer", "uk_nova_dip", "uk_radio", "uk_crate",
    "vi_heart", "vi_alloy", "vi_echo", "vi_fable", "vi_onyx", "vi_nova", "vi_shimmer", "vi_nova_dip", "vi_radio", "vi_crate",
    "zh_heart", "zh_alloy", "zh_echo", "zh_fable", "zh_onyx", "zh_nova", "zh_shimmer", "zh_nova_dip", "zh_radio", "zh_crate", "zh_creep", "zh_child", "zh_franken", "zh_robot", "zh_zombie", "zh_santa",
    "en_us_military", "en_us_child", "en_us_robot", "en_us_pirate", "en_us_santa", "en_us_zombie", "en_us_news", "en_us_ghost", "en_us_alien", "en_us_monster", "en_us_goblin", "en_us_witch", "en_us_ogre", "en_us_leprechaun", "en_us_elf", "en_us_fairy", "en_us_dragon", "en_us_orc", "en_us_demon", "en_us_vampire", "en_us_werewolf", "en_us_mummy", "en_us_skeleton", "en_us_frank", "en_us_freddy", "en_us_hal", "en_us_terminator", "en_us_jigsaw", "en_us_scream", "en_us_darth",
    "pm_alloy", "pm_echo", "pm_fable", "pm_onyx", "pm_nova", "pm_shimmer", "pm_creep", "pm_child", "pm_franken", "pm_robot", "pm_zombie", "pm_santa"
]


MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"] # Note: gpt-4o-mini-tts may be custom
# Global OpenAI voices, KOKORO_VOICES are separate
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]


CONF_CHIME_ENABLE = "chime"
CONF_CHIME_SOUND = "chime_sound"
CONF_NORMALIZE_AUDIO = "normalize_audio"
CONF_INSTRUCTIONS = "instructions"
