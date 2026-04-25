import os
import uuid
import replicate
import requests
import cv2
import numpy as np
from PIL import Image
from io import BytesIO

# =========================
# CONFIG (CLEANED V10 STYLE)
# =========================
CONFIG = {
    "output_dir": "outputs",
    "assets_dir": "assets",
    "angles": ["front", "left", "right"],
    "style_prompt": "Pixar-style child face, soft lighting, smooth skin, clean background",
    "negative_prompt": "distorted, extra eyes, deformed face, blurry",
    "face_size": (220, 260),
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


def save_pil(img, path):
    img.save(path)


# =========================
# AI: FACE GENERATION
# =========================
def generate_base_face(input_path):
    output = replicate.run(
        "stability-ai/sdxl:latest",
        input={
            "image": open(input_path, "rb"),
            "prompt": CONFIG["style_prompt"],
            "negative_prompt": CONFIG["negative_prompt"],
            "strength": 0.6,
        }
    )
    return output[0]


def generate_angle_face(base_url, angle):
    if angle == "left":
        prompt = "face turned 30 degrees left"
    elif angle == "right":
        prompt = "face turned 30 degrees right"
    else:
        prompt = "front facing portrait"

    output = replicate.run(
        "stability-ai/sdxl:latest",
        input={
            "image": base_url,
            "prompt": f"{CONFIG['style_prompt']}, {prompt}",
            "negative_prompt": CONFIG["negative_prompt"],
            "strength": 0.5,
        }
    )
    return output[0]


# =========================
# ASSET GENERATION (ONE-TIME)
# =========================
def build_character_assets(input_image):
    user_id = str(uuid.uuid4())[:8]
    user_dir = os.path.join(CONFIG["output_dir"], user_id)
    ensure_dir(user_dir)

    print("🎨 Generating base face...")
    base_url = generate_base_face(input_image)
    base_img = download_image(base_url)

    base_path = os.path.join(user_dir, "front.png")
    save_pil(base_img, base_path)

    assets = {"front": base_path}

    for angle in ["left", "right"]:
        print(f"🔄 Generating {angle} face...")
        url = generate_angle_face(base_url, angle)
        img = download_image(url)

        path = os.path.join(user_dir, f"{angle}.png")
        save_pil(img, path)
        assets[angle] = path

    return assets


# =========================
# FACE BLEND ENGINE
# =========================
def alpha_blend(face_img, body_img, position):
    face_np = np.array(face_img)
    body_np = np.array(body_img)

    x, y = position
    h, w = face_np.shape[:2]

    alpha = face_np[:, :, 3] / 255.0

    for c in range(3):
        body_np[y:y+h, x:x+w, c] = (
            alpha * face_np[:, :, c] +
            (1 - alpha) * body_np[y:y+h, x:x+w, c]
        )

    return Image.fromarray(body_np)


def resize_face(face_img):
    return face_img.resize(CONFIG["face_size"], Image.LANCZOS)


# =========================
# SCENE ENGINE
# =========================
def compose_scene(face_assets, scene_config):
    """
    scene_config example:
    {
        "background": "assets/bg_forest.png",
        "body": "assets/body_standing.png",
        "face_angle": "left",
        "face_position": (300, 180)
    }
    """

    bg = Image.open(scene_config["background"]).convert("RGBA")
    body = Image.open(scene_config["body"]).convert("RGBA")

    # merge bg + body
    canvas = Image.alpha_composite(bg, body)

    # pick face
    face_path = face_assets[scene_config["face_angle"]]
    face = Image.open(face_path).convert("RGBA")
    face = resize_face(face)

    # blend
    final = alpha_blend(face, canvas, scene_config["face_position"])

    return final


# =========================
# SCENE LOGIC (SMART SELECTION)
# =========================
def get_face_angle_for_scene(scene_type):
    mapping = {
        "looking_left": "left",
        "looking_right": "right",
        "neutral": "front",
    }
    return mapping.get(scene_type, "front")


# =========================
# MAIN PIPELINE
# =========================
def run_storyme_pipeline(input_image):
    print("🚀 Step 1: Build character assets")
    assets = build_character_assets(input_image)

    print("🎬 Step 2: Compose scenes")

    scenes = [
        {
            "background": "assets/bg_forest.png",
            "body": "assets/body_standing.png",
            "scene_type": "neutral",
            "face_position": (300, 180)
        },
        {
            "background": "assets/bg_tree.png",
            "body": "assets/body_looking_up.png",
            "scene_type": "looking_left",
            "face_position": (320, 150)
        }
    ]

    outputs = []

    for i, scene in enumerate(scenes):
        angle = get_face_angle_for_scene(scene["scene_type"])

        config = {
            "background": scene["background"],
            "body": scene["body"],
            "face_angle": angle,
            "face_position": scene["face_position"]
        }

        img = compose_scene(assets, config)

        out_path = f"outputs/scene_{i}.png"
        ensure_dir("outputs")
        img.save(out_path)

        outputs.append(out_path)

    print("✅ Story scenes generated:", outputs)


# =========================
# RUN
# =========================
if __name__ == "__main__":
    run_storyme_pipeline("input.jpg")