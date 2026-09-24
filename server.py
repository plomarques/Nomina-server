import io
import json
import logging
import os
import re
import time

from flask import Flask, jsonify, request
from google import genai
from google.cloud import translate_v2 as translate
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel

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

# Accepts codes like "en", "pt", "zh-CN", "haw"
LANGUAGE_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# Flask server
app = Flask(__name__)

# Gemini API client (uses the API key)
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
)

# Google Cloud Translation API client (uses the Cloud Run service account)
translate_client = translate.Client()


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

    # Building prompt string for Gemini
    prompt = (
        "Identify the main object in the attached picture, translate its name to the source and target languages "
        f"defined by the ISO-639 codes {source_language_code} and {target_language_code} "
        "and return the JSON defined by the schema.\n"
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
        languages_list = get_translation_languages_list(app_language_code)
        log.info("Download finished in %.2f s", time.time() - t1)

        return jsonify(languages_list), 200

    except Exception as e:
        log.exception("Error getting languages list: %s", e)
        return jsonify({"error": "Erro interno ao processar a solicitação."}), 500


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
def translate_text(text: str, language_code: str):
    language_code = language_code.replace('"', "")

    if language_code == "en":
        return text
    else:
        result = translate_client.translate(text, target_language=language_code)
        return result["translatedText"]


# - Download translation languages list
def get_translation_languages_list(target_language_code: str) -> list:
    results = translate_client.get_languages(target_language=target_language_code)

    # Inserting appLanguage into the dicts inside results
    for item in results:
        item["appLanguage"] = target_language_code
        item["languageCode"] = item.pop("language")
        item["translatedName"] = item.pop("name")

    return results
