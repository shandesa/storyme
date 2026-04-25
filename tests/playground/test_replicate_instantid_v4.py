import os
import argparse
import time
import math
import replicate
import requests
import numpy as np
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

PROMPT = "Pixar-style cartoon child, soft lighting, clean face, centered portrait"
NEGATIVE_PROMPT = "blurry, distorted, deformed, low quality"

# =========================
# CACHE ABSTRACTION
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

# Future: AzureStorage(Storage)

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
# EXPONENTIAL RETRY
# =========================
def safe_replicate_call(client, payload, retries=5):
    for attempt in range(retries):
        try:
            return client.run(MODEL_VERSION, input=payload)
        except Exception as e:
            if "429" in str(e):
                wait = 2 ** attempt
                print(f"⏳ Rate limited. Retry in {wait}s...")
                time.sleep(wait)
            else:
                raise e
    raise Exception("❌ Max retries exceeded")

# =========================
# AI GENERATION (FRONT ONLY)
# =========================
def generate_front_face(user, force=False):
    front_path = os.path.join(CACHE_DIR, user, "front.png")

    if not force and storage.exists(front_path):
        print("✅ Using cached front face")
        return storage.load(front_path)

    print("🎨 Generating front face via AI...")

    input_path = get_user_image(user)
    client = replicate.Client()

    output = safe_replicate_call(
        client,
        {
            "input_image": open(input_path, "rb"),
            "prompt": PROMPT,
            "negative_prompt": NEGATIVE_PROMPT,
            "num_outputs": 1,
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
            "identitynet_strength_ratio": 0.85,
            "adapter_strength": 0.85
        }
    )

    file_obj = output["output_paths"][0]
    img_url = file_obj.url

    img = download_image(img_url)

    storage.save(img, front_path)

    return img

# =========================
# TRANSFORM ENGINE
# =========================
import cv2
import numpy as np
from PIL import Image

def synthesize_left(img):
    print("🔄 Synthesizing LEFT (perspective)")

    img_np = np.array(img)
    h, w = img_np.shape[:2]

    # source points
    src = np.float32([
        [0, 0],
        [w, 0],
        [0, h],
        [w, h]
    ])

    # destination points (simulate left turn)
    shift = int(w * 0.15)

    dst = np.float32([
        [shift, 0],      # top-left pushed right
        [w, 0],
        [shift, h],
        [w, h]
    ])

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img_np, matrix, (w, h))

    return Image.fromarray(warped)

def synthesize_right(img):
    print("🔄 Synthesizing RIGHT (perspective)")

    img_np = np.array(img)
    h, w = img_np.shape[:2]

    src = np.float32([
        [0, 0],
        [w, 0],
        [0, h],
        [w, h]
    ])

    shift = int(w * 0.15)

    dst = np.float32([
        [0, 0],
        [w - shift, 0],  # top-right pulled left
        [0, h],
        [w - shift, h]
    ])

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img_np, matrix, (w, h))

    return Image.fromarray(warped)

# =========================
# MAIN
# =========================
def generate_faces(user, force=False):
    user_dir = os.path.join(CACHE_DIR, user)
    os.makedirs(user_dir, exist_ok=True)

    front_path = os.path.join(user_dir, "front.png")
    left_path = os.path.join(user_dir, "left.png")
    right_path = os.path.join(user_dir, "right.png")

    # FRONT
    front = generate_front_face(user, force)

    # LEFT
    if force or not storage.exists(left_path):
        left = synthesize_left(front)
        storage.save(left, left_path)
    else:
        print("✅ Using cached left")

    # RIGHT
    if force or not storage.exists(right_path):
        right = synthesize_right(front)
        storage.save(right, right_path)
    else:
        print("✅ Using cached right")

    print("🎉 All faces ready")

# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    generate_faces(args.user, args.force)