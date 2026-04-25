import os
import argparse
import time
import replicate
import requests
import numpy as np
import cv2
from PIL import Image
from io import BytesIO

# =========================
# CLI
# =========================
parser = argparse.ArgumentParser()
parser.add_argument("--user", required=True)
parser.add_argument("--story", required=True)
parser.add_argument("--force", action="store_true")
args = parser.parse_args()

# =========================
# CONFIG
# =========================
BASE_DIR = "tests\\playground\\"
USER_DIR = os.path.join(BASE_DIR, "user_face")
CACHE_DIR = os.path.join(BASE_DIR, "generated_faces")

MODEL_VERSION = "zedge/instantid:ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"

# 🔥 MAIN SWITCH
USE_AI_FOR_POSE = True   # ← toggle here

BASE_PROMPT = "Pixar-style cartoon child, soft lighting, clean face, centered portrait"
NEGATIVE_PROMPT = "blurry, distorted, deformed, low quality"

# =========================
# STORAGE ABSTRACTION
# =========================
class Storage:
    def exists(self, path): raise NotImplementedError
    def save(self, img, path): raise NotImplementedError
    def load(self, path): raise NotImplementedError

class LocalStorage(Storage):
    def exists(self, path):
        return os.path.exists(path)

    def save(self, img, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)

    def load(self, path):
        return Image.open(path).convert("RGBA")

storage = LocalStorage()

# =========================
# UTILS
# =========================
def get_user_image(user):
    path = os.path.join(USER_DIR, user, f"{user}.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing user image: {path}")
    return path

def download_image(url):
    response = requests.get(url)
    return Image.open(BytesIO(response.content)).convert("RGBA")

# =========================
# RETRY ENGINE
# =========================
def safe_replicate_call(client, payload, retries=6):
    for attempt in range(retries):
        try:
            return client.run(MODEL_VERSION, input=payload)
        except Exception as e:
            if "429" in str(e):
                wait = min(2 ** attempt, 20)
                print(f"⏳ Rate limited. Retry in {wait}s...")
                time.sleep(wait)
            else:
                raise e
    raise Exception("❌ Max retries exceeded")

# =========================
# GENERIC AI GENERATOR
# =========================
def generate_ai_face(input_path, prompt_suffix):
    client = replicate.Client()

    payload = {
        "input_image": open(input_path, "rb"),
        "prompt": f"{BASE_PROMPT}, {prompt_suffix}",
        "negative_prompt": NEGATIVE_PROMPT,
        "num_outputs": 1,
        "num_inference_steps": 30,
        "guidance_scale": 7.5,
        "identitynet_strength_ratio": 0.85,
        "adapter_strength": 0.85
    }

    output = safe_replicate_call(client, payload)

    file_obj = output["output_paths"][0]
    return download_image(file_obj.url)

# =========================
# AI GENERATION
# =========================
def generate_front(user, force):
    path = os.path.join(CACHE_DIR, user, "front.png")

    if not force and storage.exists(path):
        print("✅ Cached front")
        return storage.load(path)

    print("🎨 AI FRONT")
    img = generate_ai_face(get_user_image(user), "front facing, looking straight")

    storage.save(img, path)
    return img

def generate_left_ai(user, force):
    path = os.path.join(CACHE_DIR, user, "left.png")

    if not force and storage.exists(path):
        print("✅ Cached left")
        return storage.load(path)

    print("🎨 AI LEFT")
    img = generate_ai_face(
        get_user_image(user),
        "head turned clearly to the left, 30 degree angle, face looking left, left ear visible"
    )

    storage.save(img, path)
    return img

def generate_right_ai(user, force):
    path = os.path.join(CACHE_DIR, user, "right.png")

    if not force and storage.exists(path):
        print("✅ Cached right")
        return storage.load(path)

    print("🎨 AI RIGHT")
    img = generate_ai_face(
        get_user_image(user),
        "head turned clearly to the right, 30 degree angle, face looking right, right ear visible"
    )

    storage.save(img, path)
    return img

# =========================
# SYNTHESIS (FALLBACK)
# =========================
def synthesize_left(img):
    print("🔄 Synth LEFT (warp)")
    img_np = np.array(img)
    h, w = img_np.shape[:2]

    shift = int(w * 0.18)

    src = np.float32([[0,0],[w,0],[0,h],[w,h]])
    dst = np.float32([[shift,0],[w,0],[shift,h],[w,h]])

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img_np, matrix, (w,h))

    return Image.fromarray(warped)

def synthesize_right(img):
    print("🔄 Synth RIGHT (warp)")
    img_np = np.array(img)
    h, w = img_np.shape[:2]

    shift = int(w * 0.18)

    src = np.float32([[0,0],[w,0],[0,h],[w,h]])
    dst = np.float32([[0,0],[w-shift,0],[0,h],[w-shift,h]])

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img_np, matrix, (w,h))

    return Image.fromarray(warped)

# =========================
# MAIN PIPELINE
# =========================
def generate_faces(user, force=False):
    print(f"\n🚀 Processing user: {user}")
    user_dir = os.path.join(CACHE_DIR, user)
    os.makedirs(user_dir, exist_ok=True)

    front = generate_front(user, force)

    if USE_AI_FOR_POSE:
        left = generate_left_ai(user, force)
        right = generate_right_ai(user, force)
    else:
        left_path = os.path.join(user_dir, "left.png")
        right_path = os.path.join(user_dir, "right.png")

        if force or not storage.exists(left_path):
            left = synthesize_left(front)
            storage.save(left, left_path)
        else:
            print("✅ Cached left")

        if force or not storage.exists(right_path):
            right = synthesize_right(front)
            storage.save(right, right_path)
        else:
            print("✅ Cached right")

    print("🎉 Done")

# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    generate_faces(args.user, args.force)