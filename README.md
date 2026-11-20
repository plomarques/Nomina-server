# Nomina-server

Backend for **Nomina**, an Android app for learning vocabulary from photos: you take a picture of an object, the app shows its name in the language you are learning, saves it as a flashcard and can pronounce it.

The server is a small Flask app deployed as a container on Google Cloud Run. It:

- asks **Gemini** to identify the main object in a photo and name it in two languages (`POST /get_data_2`);
- serves the list of languages the app offers, filtered to the languages Gemini officially supports, with curated regional variants (en-GB, pt-PT, es-419…) and a flag saying which ones have pronunciation (`GET /download_translation_languages/<app_language>`);
- generates the **pronunciation** of a word as an MP3 with Google Cloud Text-to-Speech (`POST /pronounce`).

All Google credentials stay on the server: the app never calls Google directly.

## Endpoints

| Route | Input | Output |
|---|---|---|
| `POST /get_data_2` | multipart: `image_file`, `source_language_code`, `target_language_code` | `{"source_language_translation": "...", "target_language_translation": "..."}` |
| `GET /download_translation_languages/<app_language>` | app UI language (`pt`, `en`) | `[{"appLanguage", "languageCode", "translatedName", "ttsSupported"}, ...]` |
| `POST /pronounce` | form: `text` (1–100 chars), `language_code` | `200 audio/mpeg` (header `X-Nomina-Voice`), `400` invalid input, `422` no voice for the language, `500` error |
| `GET /hello_world` | — | health check |

Language codes are BCP-47 tags as used by the app (`en-GB`, `es-419`, `zh-TW`, `iw`, `mni-Mtei`…). How they map to Text-to-Speech locales and voices is in [`language_support.py`](language_support.py).

## Google Cloud setup

1. A Google Cloud project with billing enabled.
2. Enable the APIs: **Cloud Translation API** and **Cloud Text-to-Speech API**.
3. A **Gemini API key**, stored in Secret Manager and exposed to the service as `GEMINI_API_KEY`.
4. The Cloud Run service account is used for Translation and Text-to-Speech (Application Default Credentials). If Text-to-Speech answers 403, check that account's permissions.
5. Recommended: a **budget alert** on the billing account.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | yes | — | Gemini authentication |
| `GEMINI_MODEL` | no | set in `server.py` | Gemini model |
| `TTS_VOICE_TIERS` | no | `Chirp3-HD,Neural2,Wavenet,Standard` | Allowed voice models, best first. Also decides which languages get `ttsSupported`. |

## Running locally

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gcloud auth application-default login     # credentials for Translation and Text-to-Speech
GEMINI_API_KEY=... flask --app server run --port 8080
```

Smoke tests:

```bash
curl localhost:8080/hello_world
curl localhost:8080/download_translation_languages/en
curl -F image_file=@photo.jpg -F source_language_code=pt-BR -F target_language_code=en-GB localhost:8080/get_data_2
curl -d text=biscuit -d language_code=en-GB localhost:8080/pronounce -o biscuit.mp3
```

### Text-to-Speech coverage check

Before a release, list the voice chosen for every language and synthesize a short sample with each one into `tts_samples/`:

```bash
python check_tts_coverage.py            # list + samples
python check_tts_coverage.py --dry-run  # list only
```

## Deploy

The `Dockerfile` runs gunicorn (1 worker × 8 threads) on `$PORT`. Deploy it to Cloud Run with the environment variables above.
