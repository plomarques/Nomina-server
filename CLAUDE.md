# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Nomina-server is the backend for the Nomina mobile app: the app sends a photo, the server asks Gemini to name the main object in it and returns that name translated into two languages. It also serves the app's language list and generates word pronunciations (MP3) with Cloud Text-to-Speech. It is a small Flask app (`server.py` for routes, `language_support.py` for languages and TTS voices) deployed as a container on Google Cloud Run. There are no tests, linter config, or build steps beyond the Dockerfile. `check_tts_coverage.py` is a local pre-release check, not part of the deploy.

## Commands

```bash
# Local setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run locally (GEMINI_API_KEY is required at import time; the Translation client
# needs Google Cloud credentials, e.g. `gcloud auth application-default login`)
GEMINI_API_KEY=... flask --app server run --port 8080
# or, as in production:
GEMINI_API_KEY=... gunicorn --bind :8080 --workers 1 --threads 8 --timeout 0 server:app

# Container
docker build -t nomina-server .
docker run -p 8080:8080 -e GEMINI_API_KEY=... nomina-server

# Smoke tests
curl localhost:8080/hello_world
curl -F image_file=@photo.jpg -F source_language_code=en -F target_language_code=pt localhost:8080/get_data_2
curl localhost:8080/download_translation_languages/en
curl -d text=biscuit -d language_code=en-GB localhost:8080/pronounce -o biscuit.mp3

# TTS coverage check (local, real API): voice per language + samples in tts_samples/
python check_tts_coverage.py [--dry-run]
```

## Architecture

- **Google clients, two auth mechanisms.** `genai.Client` (Gemini) authenticates with `GEMINI_API_KEY`, injected on Cloud Run from Secret Manager, and is created at import, so the server fails to start without the key. `translate_v2.Client` (Cloud Translation) and `TextToSpeechClient` (Cloud TTS) use Application Default Credentials, i.e. the Cloud Run service account; they live in `language_support.py` and are created on first use.
- **Language codes.** The app uses one code per language: Translate's code normalized to one spelling (`iw`, `fil`, `jv`), plus curated regional variants (`REGIONAL_VARIANTS`: en-US/en-GB/en-AU, es-ES/es-419, pt-BR/pt-PT, fr-FR/fr-CA) that replace the generic code. Only languages in `GEMINI_SUPPORTED_LANGUAGES` (hand-maintained from the Gemini docs) are offered. The mapping to TTS locales (`to_tts_locale`) exists only on the server. `voice_for()` is used by both `/pronounce` and the `ttsSupported` flag, so they always agree.
- **`POST /get_data_2`**: multipart form with `image_file`, `source_language_code`, `target_language_code`. Language codes are stripped of quotes (the client may send them JSON-quoted) and validated against `LANGUAGE_CODE_PATTERN`. `prepare_image` applies EXIF orientation, converts to RGB, and downsizes to `MAX_IMAGE_SIDE` (384px) JPEG before sending to Gemini. Gemini returns structured JSON via the `Translations` pydantic schema (`source_language_translation`, `target_language_translation`), which the app consumes directly; if parsing fails the route still returns 200 with a "No object detected" fallback.
  The prompt sends each language as BCP-47 tag plus English name (`ls.english_label`) and asks for regional vocabulary when the tag has a region.
- **`GET /download_translation_languages/<app_language_code>`**: `ls.build_language_list()`: Translate names, filtered by Gemini, with regional variants (named with Babel) and `ttsSupported`. Returns objects with `appLanguage`, `languageCode`, `translatedName`, `ttsSupported`; the app's Room entity depends on these key names. If the TTS voice list fails to load, the route fails on purpose: the app caches the list, so a `ttsSupported = false` fallback would stick.
- **`POST /pronounce`**: form `text` (1–`MAX_PRONOUNCE_CHARS`) and `language_code`; returns `audio/mpeg` with header `X-Nomina-Voice`, 422 when the language has no voice. Voice choice is deterministic: first tier in `TTS_VOICE_TIERS` that has a voice for the locale, then alphabetical.
- **Configuration**: `GEMINI_MODEL` env var overrides the model (default in `server.py`). `TTS_VOICE_TIERS` (default `Chirp3-HD,Neural2,Wavenet,Standard`) sets the allowed voice models. `GEMINI_TIMEOUT_MS`, `MAX_IMAGE_SIDE` and `MAX_PRONOUNCE_CHARS` are constants in code.
- **Deployment**: the Dockerfile runs gunicorn with 1 worker × 8 threads bound to `$PORT`; Cloud Run handles scaling and request timeouts.

## Gotchas

- `translate_text()` in `server.py` is commented out (unused); delete it once confirmed it is not needed.
- Some user-facing error strings are in Portuguese (e.g. in `/download_translation_languages`).
