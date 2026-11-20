"""
Language support for Nomina: which languages the app offers, how they are named,
and how an app language code maps to a Cloud Text-to-Speech voice.

Rules:
- The app's language codes are Translate-style codes (from translate_v2.get_languages),
  normalized to one spelling each (iw, fil, jv), plus curated regional variants (en-GB, es-419, ...).
- A language is offered only if it is in Gemini's official language list.
- The mapping to Cloud TTS locales lives ONLY here (server side). The app never sees TTS codes.
"""

import logging
import os
from functools import lru_cache

from babel import Locale as BabelLocale
from google.cloud import texttospeech
from google.cloud import translate_v2 as translate

log = logging.getLogger("nomina")

# ------------------------------------------------------------------ #
# GEMINI: official list of supported languages (109)
# Source: Vertex AI docs, "Google models" > "Gemini language support"
# https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models (checked Nov 2026)
# There is no API that returns this list: update it by hand when the docs change.
# ------------------------------------------------------------------ #
GEMINI_SUPPORTED_LANGUAGES = frozenset({
    "af", "sq", "am", "ar", "hy", "as", "az", "eu", "be", "bn", "bs", "bg", "ca", "ceb",
    "zh", "co", "hr", "cs", "da", "dv", "nl", "en", "eo", "et", "fil", "fi", "fr", "fy",
    "gl", "ka", "de", "el", "gu", "ht", "ha", "haw", "iw", "hi", "hmn", "hu", "is", "ig",
    "id", "ga", "it", "ja", "jv", "kn", "kk", "km", "ko", "kri", "ku", "ky", "lo", "la",
    "lv", "lt", "lb", "mk", "mg", "ms", "ml", "mt", "mi", "mr", "mni-Mtei", "mn", "my",
    "ne", "no", "ny", "or", "ps", "fa", "pl", "pt", "pa", "ro", "ru", "sm", "gd", "sr",
    "st", "sn", "sd", "si", "sk", "sl", "so", "es", "su", "sw", "sv", "tg", "ta", "te",
    "th", "tr", "uk", "ur", "ug", "uz", "vi", "cy", "xh", "yi", "yo", "zu",
})

# Alternative spellings Translate returns -> spelling used by the app (= Gemini list).
# Translate currently returns BOTH "he" and "iw", BOTH "jw" and "jv", and only "tl" (Nov 2026).
CANONICAL_CODE = {"he": "iw", "tl": "fil", "jw": "jv"}

# Gemini lists "zh" for both Simplified and Traditional Chinese.
# Translate returns "zh", "zh-CN" and "zh-TW": the generic "zh" is dropped.
CHINESE_CODES = {"zh-CN", "zh-TW"}

# Curated regional variants: they REPLACE the generic code in the app's list.
# BCP-47 codes chosen by hand (not TTS codes: "es-419" does not exist in TTS).
# Edit freely; to_tts_locale() decides whether each one has a voice.
REGIONAL_VARIANTS = {
    "en": ["en-US", "en-GB", "en-AU"],
    "es": ["es-ES", "es-419"],   # 419 = Latin America
    "pt": ["pt-BR", "pt-PT"],
    "fr": ["fr-FR", "fr-CA"],
}
VARIANT_CODES = {code for variants in REGIONAL_VARIANTS.values() for code in variants}

# ------------------------------------------------------------------ #
# CLOUD TTS: app code -> TTS locale
# ------------------------------------------------------------------ #
# Language subtag differences between Translate and TTS
TTS_LANGUAGE_ALIASES = {"zh": "cmn", "iw": "he", "tl": "fil", "no": "nb", "jw": "jv"}
# Full-code exceptions
TTS_LOCALE_OVERRIDES = {"es-419": "es-US"}   # TTS's Latin American Spanish voice is es-US
# Default locale when the app code has no region
TTS_DEFAULT_LOCALE = {"en": "en-US", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR",
                      "ar": "ar-XA", "cmn": "cmn-CN"}
# Voice models the server may use, best quality first. Configurable on Cloud Run without
# code changes, e.g. TTS_VOICE_TIERS="Chirp3-HD" to use only Chirp 3: HD voices.
# Languages without a voice in the allowed models get ttsSupported = False automatically.
VOICE_TIER_ORDER = tuple(
    tier.strip()
    for tier in os.environ.get("TTS_VOICE_TIERS", "Chirp3-HD,Neural2,Wavenet,Standard").split(",")
    if tier.strip()
)


# ------------------------------------------------------------------ #
# Google clients and cached lookups
# ------------------------------------------------------------------ #
_translate_client = None
_tts_client = None


def translate_client():
    """Cloud Translation client (Application Default Credentials), created on first use."""
    global _translate_client
    if _translate_client is None:
        _translate_client = translate.Client()
    return _translate_client


def tts_client():
    """Cloud Text-to-Speech client, created on first use.
    Uses the global endpoint, which offers Chirp 3: HD voices."""
    global _tts_client
    if _tts_client is None:
        _tts_client = texttospeech.TextToSpeechClient()
    return _tts_client


def _translate_languages(target_language: str) -> list:
    """Raw Translate list: [{'language': 'en', 'name': 'Inglês'}, ...]"""
    return translate_client().get_languages(target_language=target_language)


@lru_cache(maxsize=1)
def _tts_voice_names_by_locale() -> dict:
    """{'en-GB': ['en-GB-Chirp3-HD-Achernar', ...], ...}. Cached per instance.
    lru_cache does not cache exceptions, so a failed call is retried next time."""
    voices = {}
    for voice in tts_client().list_voices().voices:
        for locale in voice.language_codes:
            voices.setdefault(locale.replace("_", "-"), []).append(voice.name)
    log.info("Loaded Cloud TTS voices for %d locales", len(voices))
    return voices


@lru_cache(maxsize=1)
def _english_names() -> dict:
    """English names keyed by the app's (canonical) code, used in the Gemini prompt."""
    return {CANONICAL_CODE.get(item["language"], item["language"]): item["name"]
            for item in _translate_languages("en")}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def is_gemini_supported(code: str) -> bool:
    return code in GEMINI_SUPPORTED_LANGUAGES or code in CHINESE_CODES


def variant_display_name(code: str, display_language: str) -> str:
    """'en-GB' in 'pt' -> 'Inglês (Reino Unido)'. Falls back to the code itself."""
    try:
        name = BabelLocale.parse(code, sep="-").get_display_name(
            BabelLocale.parse(display_language, sep="-"))
    except Exception:
        log.warning("Babel could not name '%s' in '%s'", code, display_language)
        return code
    return name[:1].upper() + name[1:] if name else code


def to_tts_locale(code: str):
    """App code -> Cloud TTS locale with at least one voice, or None."""
    locales = _tts_voice_names_by_locale()
    if code in TTS_LOCALE_OVERRIDES:
        locale = TTS_LOCALE_OVERRIDES[code]
        return locale if locale in locales else None

    parts = code.split("-")
    lang = TTS_LANGUAGE_ALIASES.get(parts[0].lower(), parts[0].lower())

    if len(parts) > 1:
        # Region or script given (zh-TW, pt-PT, mni-Mtei...): only an exact match is safe.
        # A script mismatch would read the text with the wrong voice.
        locale = f"{lang}-{parts[1]}"
        return locale if locale in locales else None

    candidates = sorted(loc for loc in locales if loc.split("-")[0].lower() == lang)
    if not candidates:
        return None
    for preferred in (TTS_DEFAULT_LOCALE.get(lang), f"{lang}-{lang.upper()}"):
        if preferred in candidates:
            return preferred
    return candidates[0]


def pick_voice(locale: str):
    """Best available voice for a locale, deterministic (same language -> same voice)."""
    names = _tts_voice_names_by_locale().get(locale, [])
    for tier in VOICE_TIER_ORDER:
        tiered = sorted(name for name in names if f"-{tier}-" in name)
        if tiered:
            return tiered[0]
    return None


def voice_for(code: str):
    """App code -> (tts_locale, voice_name), or (None, None) if there is no usable voice.
    Used by BOTH /pronounce and ttsSupported, so the app never shows a speaker
    for a language the server would refuse."""
    locale = to_tts_locale(code)
    voice = pick_voice(locale) if locale else None
    return (locale, voice) if voice else (None, None)


def english_label(code: str) -> str:
    """Name used in the Gemini prompt: 'en-GB' -> 'English (United Kingdom)'."""
    if code in VARIANT_CODES:
        return variant_display_name(code, "en")
    try:
        return _english_names().get(code, code)
    except Exception:
        log.exception("Could not load English language names")
        return code


def build_language_list(app_language_code: str) -> list:
    """List sent to the phone: Translate names, filtered by Gemini, with regional
    variants and the ttsSupported flag.

    If the TTS voice list cannot be loaded, this raises on purpose (the route answers 500).
    Do NOT fall back to ttsSupported = False: the app caches the list and only downloads it
    again when its cache is empty, so a temporary TTS failure would hide pronunciation for good.
    """
    raw = _translate_languages(app_language_code)
    raw_codes = {item["language"] for item in raw}

    result, seen = [], set()
    for item in raw:
        code = CANONICAL_CODE.get(item["language"], item["language"])
        if code == "zh" and raw_codes & CHINESE_CODES:
            continue   # zh-CN / zh-TW already cover it
        if not is_gemini_supported(code):
            continue

        if code in REGIONAL_VARIANTS:
            entries = [(v, variant_display_name(v, app_language_code)) for v in REGIONAL_VARIANTS[code]]
        else:
            entries = [(code, item["name"])]

        for entry_code, name in entries:
            if entry_code in seen:
                continue
            seen.add(entry_code)
            result.append({
                "appLanguage": app_language_code,
                "languageCode": entry_code,
                "translatedName": name,
                "ttsSupported": voice_for(entry_code)[1] is not None,
            })
    return result
