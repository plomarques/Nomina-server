import io
import json
import logging
import os
import re
import time

from flask import Flask, Response, jsonify, request
from google import genai
from google.cloud import texttospeech
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel

import language_support as ls

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("nomina")

# --------------------------------- #
# CONFIGURATION
# --------------------------------- #

# Gemini API key comes from the environment (Secret Manager on Cloud Run).
# Never hardcode it here.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Environment variable GEMINI_API_KEY is not set.")

# Model can be changed without touching the code (env var on the Cloud Run service).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Timeout for each Gemini call, in milliseconds
GEMINI_TIMEOUT_MS = 30_000

# Max size (in pixels) of the longest side of the picture sent to Gemini
MAX_IMAGE_SIDE = 384

# Max length of the text sent to /pronounce. Protects the TTS quota: one word or a short expression
MAX_PRONOUNCE_CHARS = 100

# Accepts codes like "en", "pt", "zh-CN", "haw", "en-GB", "es-419", "mni-Mtei"
LANGUAGE_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# Flask server
app = Flask(__name__)

# Gemini API client (uses the API key)
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
)

# The Cloud Translation and Cloud Text-to-Speech clients live in language_support.py
# (created on first use, authenticated with the Cloud Run service account).


# Class to get structured JSON response from Gemini
class Translations(BaseModel):
    source_language_translation: str
    target_language_translation: str


# --------------------------------- #
# ROUTES
# --------------------------------- #

# Code to ignore the favicon warning
@app.route("/favicon.ico")
def favicon():
    return "", 204


# Hello world route just for testing the server
@app.route("/hello_world")
def hello_world():
    return "Hello, world!"


# - OBJECT DETECTION AND TRANSLATION -- #
@app.route("/get_data_2", methods=["POST"])
def get_data_2():
    # Data from app - Picture and language codes
    image_file = request.files.get("image_file")
    source_language_code = clean_language_code(request.form.get("source_language_code"))
    target_language_code = clean_language_code(request.form.get("target_language_code"))

    if image_file is None:
        return jsonify({"error": "Missing 'image_file'."}), 400
    if source_language_code is None or target_language_code is None:
        return jsonify({"error": "Missing or invalid language code."}), 400

    # Building prompt string for Gemini. Code AND English name reduce ambiguity,
    # and a region in the tag (en-GB, pt-PT...) asks for that region's vocabulary.
    source_label = ls.english_label(source_language_code)   # e.g. "English (United Kingdom)"
    target_label = ls.english_label(target_language_code)   # e.g. "Portuguese (Brazil)"
    prompt = (
        "Identify the main object in the attached picture and give its common name in two languages, "
        "identified by BCP-47 language tags:\n"
        f"- source: {source_language_code} ({source_label})\n"
        f"- target: {target_language_code} ({target_label})\n"
        "When a tag includes a region (for example en-GB or pt-PT), use the vocabulary and spelling "
        "of that region. Return the JSON defined by the schema.\n"
        'If no particular object is detected, translate "No object detected" to both languages.\n'
        'If the process somehow fails, translate "Analysis failed" to both languages.'
    )

    try:
        image_part = prepare_image(image_file)

        # Sending request to Gemini API
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[image_part, prompt],
            config={
                "response_mime_type": "application/json",
                "response_schema": Translations,
            },
        )
    except Exception as e:
        log.exception("Error processing picture or calling Gemini: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    # Try parsing the JSON safely
    try:
        parsed_response = json.loads(response.text)
        return jsonify(parsed_response), 200
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("Could not parse Gemini response (%s). Returning fallback translation.", e)
        fallback = {
            "source_language_translation": "No object detected",
            "target_language_translation": "No object detected",
        }
        return jsonify(fallback), 200


# DOWNLOAD TRANSLATION LANGUAGES LIST
@app.route("/download_translation_languages/<string:app_language_code>", methods=["GET"])
def get_translation_languages(app_language_code):
    try:
        log.info("Downloading languages list for '%s'...", app_language_code)
        t1 = time.time()
        languages_list = ls.build_language_list(app_language_code)
        log.info("Download finished in %.2f s (%d languages)", time.time() - t1, len(languages_list))

        return jsonify(languages_list), 200

    except Exception as e:
        log.exception("Error getting languages list: %s", e)
        return jsonify({"error": "Erro interno ao processar a solicitação."}), 500


# PRONUNCIATION (Cloud Text-to-Speech)
# Form fields: text (1 to MAX_PRONOUNCE_CHARS characters) and language_code (the app's code).
# 200 audio/mpeg with the MP3 bytes (header X-Nomina-Voice = voice used),
# 400 invalid text or code, 422 language without a TTS voice, 500 Google or internal error.
@app.route("/pronounce", methods=["POST"])
def pronounce():
    text = (request.form.get("text") or "").strip()
    language_code = clean_language_code(request.form.get("language_code"))

    if not text or len(text) > MAX_PRONOUNCE_CHARS:
        return jsonify({"error": f"'text' must have 1 to {MAX_PRONOUNCE_CHARS} characters."}), 400
    if language_code is None:
        return jsonify({"error": "Missing or invalid language code."}), 400

    try:
        locale, voice = ls.voice_for(language_code)
        if voice is None:
            return jsonify({"error": "Pronunciation not available for this language."}), 422

        response = ls.tts_client().synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code=locale, name=voice),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
        )
    except Exception as e:
        log.exception("Error generating pronunciation: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    log.info("Pronunciation: '%s' [%s -> %s, %s]", text, language_code, locale, voice)
    return Response(response.audio_content, mimetype="audio/mpeg",
                    headers={"X-Nomina-Voice": voice})


# --------------------------------- #
# HELPER FUNCTIONS
# --------------------------------- #

# - Removes quotes/spaces around a language code and validates it. Returns None if invalid
def clean_language_code(code):
    if code is None:
        return None
    code = code.replace('"', "").strip()
    return code if LANGUAGE_CODE_PATTERN.match(code) else None


# - Reads the uploaded picture, fixes orientation, shrinks it and packs it for Gemini
def prepare_image(image_file) -> types.Part:
    image_pil = Image.open(image_file.stream)
    image_pil = ImageOps.exif_transpose(image_pil).convert("RGB")
    log.info("Image size: %s", image_pil.size)

    # Shrinks keeping the aspect ratio (never enlarges)
    image_pil.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))

    # Save image to JPEG format in memory
    buffer = io.BytesIO()
    image_pil.save(buffer, format="JPEG")

    return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg")


# - Text translation
# Not used by any route (Gemini translates in /get_data_2). Commented out for now;
# delete it once we are sure it is not needed.
# def translate_text(text: str, language_code: str):
#     language_code = language_code.replace('"', "")
#
#     if language_code == "en":
#         return text
#     else:
#         result = ls.translate_client().translate(text, target_language=language_code)
#         return result["translatedText"]
