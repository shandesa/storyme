import os
import re
import sys
import json
import base64
import cv2
import numpy as np
from PIL import Image
from openai import OpenAI

# =========================
# CONFIG
# =========================
OPENAI_API_KEY = "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"
MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================
# INPUT ARGS
# =========================
if len(sys.argv) < 3:
    print("Usage: python generate.py prompts.txt face.jpg")
    sys.exit(1)

PROMPT_FILE = sys.argv[1]
FACE_IMAGE_PATH = sys.argv[2]

# =========================
# INIT
# =========================
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# FACE DETECTION (INPUT FACE)
# =========================
def extract_face(face_path):
    img = cv2.imread(face_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    faces = face_cascade.detectMultiScale(gray, 1.3, 5)

    if len(faces) == 0:
        raise Exception("No face detected in input image")

    (x, y, w, h) = faces[0]
    face_crop = img[y:y+h, x:x+w]

    face_crop_path = os.path.join(OUTPUT_DIR, "face_crop.png")
    cv2.imwrite(face_crop_path, face_crop)

    return face_crop_path

# =========================
# PIXAR FACE GENERATION
# =========================
def generate_pixar_face(face_crop_path):
    prompt = """
    Convert this face into a Pixar-style 3D animated child face.
    Soft lighting, smooth skin, expressive, child-friendly.
    Keep resemblance but stylized.
    Clean background.
    """

    response = client.images.generate(
        model=MODEL,
        prompt=prompt,
        size=IMAGE_SIZE
    )

    image_base64 = response.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)

    pixar_face_path = os.path.join(OUTPUT_DIR, "pixar_face.png")

    with open(pixar_face_path, "wb") as f:
        f.write(image_bytes)

    return pixar_face_path

# =========================
# DYNAMIC FACE PLACEHOLDER DETECTION (NEW)
# =========================
def detect_face_placeholder(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return None

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Broad skin tone detection
    lower_skin = np.array([0, 30, 60], dtype=np.uint8)
    upper_skin = np.array([25, 200, 255], dtype=np.uint8)

    mask = cv2.inRange(hsv, lower_skin, upper_skin)

    # Clean mask
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.GaussianBlur(mask, (5, 5), 0)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_candidate = None
    max_score = 0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        area = w * h
        aspect_ratio = w / float(h)

        # Must look like a face circle
        if 0.7 < aspect_ratio < 1.3 and area > 2000:
            score = area

            if score > max_score:
                max_score = score
                best_candidate = (x, y, w, h)

    if best_candidate:
        x, y, w, h = best_candidate
        return {
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h)
        }

    return None

# =========================
# OVERLAY FACE
# =========================
def overlay_face(scene_path, face_path, coords):
    scene = Image.open(scene_path).convert("RGBA")
    face = Image.open(face_path).convert("RGBA")

    face = face.resize((coords["w"], coords["h"]))

    scene.paste(face, (coords["x"], coords["y"]), face)

    return scene

# =========================
# LOAD PROMPTS
# =========================
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    content = f.read()

pages = re.split(r"(Page \d+)", content)

structured_pages = []
for i in range(1, len(pages), 2):
    structured_pages.append((pages[i], pages[i+1]))

print(f"Found {len(structured_pages)} pages")

# =========================
# DEFAULT FALLBACK
# =========================
DEFAULT_FACE_CONFIG = {
    "x": 420,
    "y": 220,
    "w": 180,
    "h": 180
}

face_config = {}

# =========================
# PREPARE FACE
# =========================
face_crop = extract_face(FACE_IMAGE_PATH)
pixar_face = generate_pixar_face(face_crop)

# =========================
# MAIN LOOP
# =========================
for idx, (title, prompt) in enumerate(structured_pages, start=1):
    scene_base_name = f"scene_{idx:02d}"

    base_path = os.path.join(OUTPUT_DIR, f"{scene_base_name}_base.png")
    final_path = os.path.join(OUTPUT_DIR, f"{scene_base_name}_personalized.png")

    print(f"Generating {scene_base_name}...")

    try:
        # -------------------
        # 1. Generate Base Image (UNCHANGED)
        # -------------------
        response = client.images.generate(
            model=MODEL,
            prompt=prompt,
            size=IMAGE_SIZE
        )

        image_bytes = base64.b64decode(response.data[0].b64_json)

        with open(base_path, "wb") as f:
            f.write(image_bytes)

        # -------------------
        # 2. Detect Face Placeholder (NEW)
        # -------------------
        coords = detect_face_placeholder(base_path)

        if coords is None:
            print("⚠️ Face detection failed, using default")
            coords = DEFAULT_FACE_CONFIG.copy()

        # -------------------
        # 3. Overlay Face
        # -------------------
        final_img = overlay_face(base_path, pixar_face, coords)
        final_img.save(final_path)

        # -------------------
        # 4. Save Config
        # -------------------
        face_config[f"{scene_base_name}_personalized.png"] = coords

        print(f"Saved: {final_path}")

    except Exception as e:
        print(f"Error in {scene_base_name}: {e}")

# =========================
# SAVE JSON
# =========================
json_path = os.path.join(OUTPUT_DIR, "face_config.json")

with open(json_path, "w") as f:
    json.dump(face_config, f, indent=4)

print(f"\n✅ Done. Face config saved at {json_path}")