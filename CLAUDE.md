# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Nomina-server is the backend for the Nomina mobile app: the app sends a photo, the server asks Gemini to name the main object in it and returns that name translated into two languages. It is a single-file Flask app (`server.py`) deployed as a container on Google Cloud Run. There are no tests, linter config, or build steps beyond the Dockerfile.

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
```

## Architecture

- **Two Google clients, two auth mechanisms.** `genai.Client` (Gemini) authenticates with `GEMINI_API_KEY`, injected on Cloud Run from Secret Manager. `translate_v2.Client` (Cloud Translation) uses Application Default Credentials, i.e. the Cloud Run service account. Both clients are created at module import, so the server fails to start without the API key.
- **`POST /get_data_2`**: multipart form with `image_file`, `source_language_code`, `target_language_code`. Language codes are stripped of quotes (the client may send them JSON-quoted) and validated against `LANGUAGE_CODE_PATTERN`. `prepare_image` applies EXIF orientation, converts to RGB, and downsizes to `MAX_IMAGE_SIDE` (384px) JPEG before sending to Gemini. Gemini returns structured JSON via the `Translations` pydantic schema (`source_language_translation`, `target_language_translation`), which the app consumes directly; if parsing fails the route still returns 200 with a "No object detected" fallback.
- **`GET /download_translation_languages/<app_language_code>`**: wraps Cloud Translation `get_languages`, renaming keys to `languageCode` / `translatedName` and adding `appLanguage`. The mobile app depends on these key names.
- **Configuration**: `GEMINI_MODEL` env var overrides the model (default in `server.py`). `GEMINI_TIMEOUT_MS` and `MAX_IMAGE_SIDE` are constants in code.
- **Deployment**: the Dockerfile runs gunicorn with 1 worker × 8 threads bound to `$PORT`; Cloud Run handles scaling and request timeouts.

## Gotchas

- `translate_text()` in `server.py` is currently unused.
- Some user-facing error strings are in Portuguese (e.g. in `/download_translation_languages`).
