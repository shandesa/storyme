import os
import argparse
import json
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

# =========================
# OPTIONAL REPLICATE
# =========================
USE_AI = False  # ← set True only after you confirm a working model

try:
    if USE_AI:
        import replicate
        REPLICATE_AVAILABLE = True
    else:
        REPLICATE_AVAILABLE = False
except:
    REPLICATE_AVAILABLE = False

# =========================
# CLI
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
JSON_PATH = os.path.join(BASE_DIR, "forest_of_smiles_v8_final.json")

CONFIG = {
    "face_size": (220, 260)
}

# =========================
# UTILS
# =========================
def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def safe_open_image(path, label):
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing {label}: {path}")
    return Image.open(path).convert("RGBA")

def get_user_input_image(user):
    path = os.path.join(USER_DIR, user, f"{user}.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing user image: {path}")
    return path

# =========================
# FALLBACK FACE GENERATION
# =========================
def simple_cartoonize(img):
    img = img.filter(ImageFilter.SMOOTH_MORE)
    img = ImageEnhance.Color(img).enhance(1.4)
    img = ImageEnhance.Sharpness(img).enhance(1.2)
    return img

def generate_faces_fallback(input_path, out_dir):
    print("⚠️ Using deterministic fallback (no AI)")

    base = Image.open(input_path).convert("RGBA")
    base = simple_cartoonize(base)

    assets = {}

    front = base
    left = base.rotate(8, expand=True)
    right = base.rotate(-8, expand=True)

    front_path = os.path.join(out_dir, "front.png")
    left_path = os.path.join(out_dir, "left.png")
    right_path = os.path.join(out_dir, "right.png")

    front.save(front_path)
    left.save(left_path)
    right.save(right_path)

    assets["front"] = front_path
    assets["left"] = left_path
    assets["right"] = right_path

    return assets

# =========================
# BUILD FACE ASSETS
# =========================
def build_user_faces(user):
    input_path = get_user_input_image(user)
    out_dir = os.path.join(USER_DIR, user, "generated_faces")
    ensure_dir(out_dir)

    # For now, always fallback (stable)
    return generate_faces_fallback(input_path, out_dir)

# =========================
# BLENDING
# =========================
def resize_face(face):
    return face.resize(CONFIG["face_size"], Image.LANCZOS)

def alpha_blend(face_img, base_img, position):
    face_np = np.array(face_img)
    base_np = np.array(base_img)

    x, y = position
    h, w = face_np.shape[:2]

    # Bounds safety
    if y + h > base_np.shape[0] or x + w > base_np.shape[1]:
        return base_img

    alpha = face_np[:, :, 3] / 255.0

    for c in range(3):
        base_np[y:y+h, x:x+w, c] = (
            alpha * face_np[:, :, c] +
            (1 - alpha) * base_np[y:y+h, x:x+w, c]
        )

    return Image.fromarray(base_np)

# =========================
# JSON HANDLING (ROBUST)
# =========================
def load_story():
    if not os.path.exists(JSON_PATH):
        raise FileNotFoundError(f"❌ Missing JSON: {JSON_PATH}")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support multiple structures
    if isinstance(data, list):
        return data
    if "pages" in data:
        return data["pages"]
    if "scenes" in data:
        return data["scenes"]

    raise ValueError("❌ Unsupported JSON structure")

def resolve_scene_paths(scene):
    """
    Supports multiple JSON key formats
    """

    bg = (
        scene.get("background")
        or scene.get("bg")
        or scene.get("background_image")
    )

    body = (
        scene.get("body")
        or scene.get("character")
        or scene.get("body_image")
    )

    return bg, body

# =========================
# ANGLE LOGIC
# =========================
def get_angle(desc):
    desc = (desc or "").lower()
    if "left" in desc:
        return "left"
    elif "right" in desc:
        return "right"
    return "front"

# =========================
# MAIN PIPELINE
# =========================
def render_story(user, story):
    print("🚀 Starting StoryMe pipeline...")

    face_assets = build_user_faces(user)
    scenes = load_story()

    out_dir = os.path.join(OUTPUT_DIR, user, story)
    ensure_dir(out_dir)

    for i, scene in enumerate(scenes):
        print(f"🎬 Scene {i+1}")

        bg_name, body_name = resolve_scene_paths(scene)

        if not bg_name or not body_name:
            raise KeyError(
                f"❌ Scene {i+1} missing background/body. Keys found: {list(scene.keys())}"
            )

        bg_path = os.path.join(TEMPLATES_DIR, bg_name)
        body_path = os.path.join(TEMPLATES_DIR, body_name)

        bg = safe_open_image(bg_path, "background")
        body = safe_open_image(body_path, "body")

        canvas = Image.alpha_composite(bg, body)

        if scene.get("character_present", True):
            angle = get_angle(scene.get("description"))

            face = Image.open(face_assets[angle]).convert("RGBA")
            face = resize_face(face)

            pos = tuple(scene.get("face_position", (300, 180)))

            canvas = alpha_blend(face, canvas, pos)

        out_path = os.path.join(out_dir, f"scene_{i+1}.png")
        canvas.save(out_path)

    print(f"✅ Generated {len(scenes)} scenes at: {out_dir}")

# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    render_story(args.user, args.story)