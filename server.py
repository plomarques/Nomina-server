import time
import io
import json
import psutil
from flask import Flask, request, jsonify, send_file
from google import genai
from google.genai import types
from google.cloud import translate_v2 as translate
from PIL import Image
from pydantic import BaseModel

# import google_cloud_translation as translation_api
# import detection_and_translation as combined_api

# Variable for Flask server
app = Flask(__name__)

# Variable for Google Cloud Translation API
translate_client = translate.Client()

# Code to ignore the favicon warning
@app.route('/favicon.ico')
def favicon():
    return '', 204

# Hello world route just for testing the server
@app.route("/hello_world")
def hello_world():
    return "Hello, world!"

# - OBJECT DETECTION AND TRANSLATION -- #
@app.route('/get_data_2', methods=['POST'])
def get_data_2():

    # Class to get structured JSON response from Gemini
    class Translations(BaseModel):
        source_language_translation: str
        target_language_translation: str

    # Data from app - Picture and language codes
    image_file = request.files.get('image_file')
    source_language_code:str = request.form.get('source_language_code')
    target_language_code:str = request.form.get('target_language_code')

    # Building prompt string for Gemini
    prompt = ("""Identify the main object in the attached picture, translate its name to the source and target languages 
    defined by the ISO-639 codes %s and %s and return the JSON defined by the schema.
    If no particular object is detected, translate "No object detected" to both languages.
    If no picture is attached, translate "No picture found" to both languages.
    If the process somehow fails, translate "Analysis failed" to both languages.""" % (
    source_language_code, target_language_code))
    try:
        # Reading and resizing image
        image_pil = Image.open(image_file.stream).convert("RGB")
        print(f"Image format: {image_pil.format}, size: {image_pil.size}, mode: {image_pil.mode}")
        print(image_pil.size[0])
        new_x_dim = min(384, image_pil.size[0])
        print(image_pil.size[1])
        new_y_dim = min(384, image_pil.size[1])
        print(new_x_dim)
        print(new_y_dim)
        resized_image = image_pil.resize(size=(new_x_dim, new_y_dim))

        # Save image to JPEG format in memory
        buffer = io.BytesIO()
        resized_image.save(buffer, format="JPEG")
        buffer.seek(0)  # Reset buffer pointer

        # Prepare image for Gemini
        image_part = types.Part.from_bytes(data=buffer.read(), mime_type="image/jpeg")

        # Sending request to Gemini API
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[image_part, prompt],
            config={
                "response_mime_type": "application/json",
                "response_schema": Translations
            }
        )

        # Deleting previously used variables from memory
        del image_file, image_pil, image_part, resized_image

        # Try parsing the JSON safely
        try:
            parsed_response = json.loads(response.text)
            return jsonify(parsed_response)
        except json.JSONDecodeError as e:
            print("JSON parsing error:", e)
            print("Returning fallback translation.")
            fallback = {
                "source_language_translation": "No object detected",
                "target_language_translation": "No object detected"
            }
            return jsonify(fallback), 200

    except Exception as e:
        print("Server error:", e)
        return jsonify({"error": "Internal server error"}), 500
# ------------------------------------- #

# # UPLOAD PICTURE AND LANGUAGE CODES, RETURN DETECTED OBJECT'S NAME IN BOTH LANGUAGES
# @app.route('/get_data_2', methods=['POST'])
# def get_data_2():
#     image = request.files.get('image_file')
#     source_language_code:str = request.form.get('source_language_code')
#     target_language_code:str = request.form.get('target_language_code')
#     # image.save(os.path.join(UPLOAD_FOLDER, 'received.jpg'))

#     # Converting image to appropriate PIL format for YOLO model
#     log_memory_usage("Before opening image")
#     image_pil = Image.open(image.stream)
#     log_memory_usage("After opening image")
#     print(f"Image format: {image_pil.format}, size: {image_pil.size}, mode: {image_pil.mode}")

#     # Codigo para usar foto do app na detect_object
#     log_memory_usage("Before detecting object")
#     [image_name_en, accuracy] = detect_object(image_pil)
#     log_memory_usage("After detecting object")

#     # Clean up
#     image_pil.close()
#     del image_pil
    
#     # Traducao
#     source_language_name = translate_text(image_name_en, source_language_code)
#     target_language_name = translate_text(image_name_en, target_language_code)
#     return jsonify({
#         'source_language_translation': source_language_name,
#         'target_language_translation': target_language_name,
#         'accuracy': accuracy
#     })

# DOWNLOAD TRANSLATION LANGUAGES LIST
@app.route('/download_translation_languages/<string:app_language_code>', methods=['GET'])
def get_translation_languages(app_language_code):
    try:
        print(f"Fazendo download da lista de idiomas para '{app_language_code}'...")
        t1 = time.time()
        languages_list = get_translation_languages_list(app_language_code)
        t2 = time.time()
        print(f"Download concluído. Tempo decorrido: {t2 - t1:.2f} s")

        return jsonify(languages_list), 200

    except Exception as e:
        print(f"Erro ao obter lista de idiomas: {e}")
        return jsonify({"error": "Erro interno ao processar a solicitação."}), 500


# @app.route('/static/sample.jpg', methods=['GET'])
# def serve_image():
#     return send_file('static/sample.jpg', mimetype='image/jpeg')

# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=5000, debug=True)

# --------------------------------- #
# FUNCTIONS TO HANDLE OBJECT DETECTION, TRANSLATION AND LANGUAGES DOWNLOAD
# --------------------------------- #

# # - Object detection using YOLO
# def detect_object(image):
#     results = get_model().predict(image, save=False, max_det = 1)
#     result = results[0]
#     #####
#     obj_dict = result.summary()[0]
#     obj_name:str = obj_dict['name']
#     obj_name = str(obj_name.replace("_", " "))
#     obj_conf:float = obj_dict['confidence']
#     #obj_conf = str(obj_conf)

#     # Deletando resultados anteriores para liberar espaco na memoria
#     del result, results, obj_dict

#     # Devolvendo nome do objeto em EN e acuracia da deteccao
#     return obj_name, obj_conf
#     #####

#     ## ChatGPT suggestion - Check later if necessary, uncomment this and comment code block between ##### to test it
#     # names = model.names
#     # boxes = result.boxes
#     # if boxes is not None and len(boxes) > 0:
#     #     class_id = int(boxes.cls[0])
#     #     confidence = float(boxes.conf[0])
#     #     obj_name = names[class_id].replace("_", " ")
#     #     return obj_name, confidence
#     # else:
#     #     return "object", 0.0

# - Text translation
def translate_text(text: str, language_code: str):
    language_code = language_code.replace("\"","")

    if (language_code == "en"):
        return text
    else:
        result = translate_client.translate(text, target_language=language_code)
        return result["translatedText"]

# - Download translation languages list
def get_translation_languages_list(target_language_code: str) -> list:
    results = translate_client.get_languages(target_language = target_language_code)

    # Inserindo appLanguage nos dicts dentro de results
    for item in results:
        item["appLanguage"] = target_language_code
        item["languageCode"] = item.pop("language")
        item["translatedName"] = item.pop("name")

    return results

# # - COLD STARTING YOLO MODEL ONLY WHEN NEEDED
# model = None

# def get_model():
#     global model
#     if model is None:
#         print("⚙️ Loading YOLO model...")
#         from ultralytics import YOLO
#         model = YOLO("yolo11m.pt")
#     return model

# - Debugging - Measuring memory usage
def log_memory_usage(note=""):
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / (1024 * 1024)  # MB
    print(f"[MEMORY] {note} - RAM used: {mem:.2f} MB")