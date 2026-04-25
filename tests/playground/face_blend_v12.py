import os
import argparse
import json
import replicate
import requests
import numpy as np
from PIL import Image
from io import BytesIO

# =========================
# CLI ARGUMENTS
# =========================
parser = argparse.ArgumentParser()
parser.add_argument("--user", required=True)
parser.add_argument("--story", required=True)
args = parser.parse_args()

# =========================
# PATHS
# =========================
BASE_DIR = "tests\\playground\\"
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
JSON_PATH = os.path.join(BASE_DIR, "forest_of_smiles_v8_final.json")

# =========================
# CONFIG
# =========================
CONFIG = {
    "face_size": (220, 260),
    "style_prompt": "Pixar-style child face, soft lighting, clean cartoon style",
    "negative_prompt": "distorted, blurry, extra eyes, deformed",
}

# =========================
# UTILS
# =========================
def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def download_image(url):
    response = requests.get(url)
    return Image.open(BytesIO(response.content)).convert("RGBA")


def save_image(img, path):
    img.save(path)


# =========================
# INPUT IMAGE
# =========================
def get_user_input_image(user):
    path = os.path.join(USER_DIR, user, f"{user}.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ User image not found at: {path}")
    return path


# =========================
# AI GENERATION (WORKING MODEL)
# =========================
def generate_base_face(input_path):
    print("🎨 Generating base face...")

    output = replicate.run(
        "cjwbw/sdxl-turbo",
        input={
            "image": open(input_path, "rb"),
            "prompt": CONFIG["style_prompt"],
            "negative_prompt": CONFIG["negative_prompt"],
            "strength": 0.6,
            "num_inference_steps": 4,
            "guidance_scale": 0,
        }
    )

    return output[0]


def generate_angle_face(base_url, angle):
    if angle == "left":
        prompt = "face turned 30 degrees left"
    elif angle == "right":
        prompt = "face turned 30 degrees right"
    else:
        prompt = "front portrait"

    output = replicate.run(
        "cjwbw/sdxl-turbo",
        input={
            "image": base_url,
            "prompt": f"{CONFIG['style_prompt']}, {prompt}",
            "negative_prompt": CONFIG["negative_prompt"],
            "strength": 0.5,
            "num_inference_steps": 4,
            "guidance_scale": 0,
        }
    )

    return output[0]


# =========================
# BUILD FACE ASSETS
# =========================
def build_user_faces(user):
    input_path = get_user_input_image(user)

    user_output_dir = os.path.join(USER_DIR, user, "generated_faces")
    ensure_dir(user_output_dir)

    face_assets = {}

    base_url = generate_base_face(input_path)
    base_img = download_image(base_url)

    base_path = os.path.join(user_output_dir, "front.png")
    save_image(base_img, base_path)
    face_assets["front"] = base_path

    for angle in ["left", "right"]:
        print(f"🔄 Generating {angle} face...")
        url = generate_angle_face(base_url, angle)
        img = download_image(url)

        path = os.path.join(user_output_dir, f"{angle}.png")
        save_image(img, path)
        face_assets[angle] = path

    return face_assets


# =========================
# BLENDING ENGINE
# =========================
def resize_face(face):
    return face.resize(CONFIG["face_size"], Image.LANCZOS)


def alpha_blend(face_img, base_img, position):
    face_np = np.array(face_img)
    base_np = np.array(base_img)

    x, y = position
    h, w = face_np.shape[:2]

    alpha = face_np[:, :, 3] / 255.0

    for c in range(3):
        base_np[y:y+h, x:x+w, c] = (
            alpha * face_np[:, :, c] +
            (1 - alpha) * base_np[y:y+h, x:x+w, c]
        )

    return Image.fromarray(base_np)


# =========================
# ANGLE LOGIC
# =========================
def get_angle(description):
    desc = description.lower()
    if "left" in desc:
        return "left"
    elif "right" in desc:
        return "right"
    return "front"


# =========================
# LOAD STORY JSON
# =========================
def load_story():
    if not os.path.exists(JSON_PATH):
        raise FileNotFoundError(f"❌ JSON not found: {JSON_PATH}")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# MAIN PIPELINE
# =========================
def render_story(user, story):
    print("🚀 Starting StoryMe pipeline...")

    face_assets = build_user_faces(user)

    story_data = load_story()
    scenes = story_data["pages"]

    output_story_dir = os.path.join(OUTPUT_DIR, user, story)
    ensure_dir(output_story_dir)

    for idx, scene in enumerate(scenes):
        print(f"🎬 Scene {idx+1}")

        bg_path = os.path.join(TEMPLATES_DIR, scene["background"])
        body_path = os.path.join(TEMPLATES_DIR, scene["body"])

        if not os.path.exists(bg_path):
            raise FileNotFoundError(f"❌ Missing background: {bg_path}")
        if not os.path.exists(body_path):
            raise FileNotFoundError(f"❌ Missing body: {body_path}")

        bg = Image.open(bg_path).convert("RGBA")
        body = Image.open(body_path).convert("RGBA")

        canvas = Image.alpha_composite(bg, body)

        if scene.get("character_present", True):
            angle = get_angle(scene.get("description", ""))

            face_path = face_assets[angle]
            face = Image.open(face_path).convert("RGBA")
            face = resize_face(face)

            position = tuple(scene.get("face_position", (300, 180)))

            canvas = alpha_blend(face, canvas, position)

        out_path = os.path.join(output_story_dir, f"scene_{idx+1}.png")
        canvas.save(out_path)

    print(f"✅ All {len(scenes)} scenes generated at: {output_story_dir}")


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    render_story(args.user, args.story)