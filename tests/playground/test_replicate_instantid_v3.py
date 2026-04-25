import os
import argparse
import time
import replicate
import requests
from PIL import Image
from io import BytesIO

# =========================
# CLI
# =========================
parser = argparse.ArgumentParser()
parser.add_argument("--user", required=True)
parser.add_argument("--story", required=True)
parser.add_argument("--force", action="store_true", help="Force regenerate images")
args = parser.parse_args()

# =========================
# PATHS
# =========================
BASE_DIR = "tests\\playground\\"
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_faces")

MODEL_VERSION = "zedge/instantid:ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"

BASE_PROMPT = "Pixar-style cartoon child, soft lighting, clean face, detailed eyes, high quality"
NEGATIVE_PROMPT = "blurry, distorted, deformed, extra eyes, low quality"

# =========================
# UTILS
# =========================
def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def get_user_image(user):
    path = os.path.join(USER_DIR, user, f"{user}.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ User image not found: {path}")
    return path

def download_image(url):
    response = requests.get(url)
    return Image.open(BytesIO(response.content))

# =========================
# RATE LIMIT SAFE CALL
# =========================
def safe_replicate_call(client, input_payload, retries=5):
    for attempt in range(retries):
        try:
            return client.run(MODEL_VERSION, input=input_payload)
        except Exception as e:
            if "429" in str(e):
                wait = 2 + attempt * 2
                print(f"⏳ Rate limited. Sleeping {wait}s...")
                time.sleep(wait)
            else:
                raise e
    raise Exception("❌ Max retries exceeded")

# =========================
# GENERATOR
# =========================
def generate_face(client, input_path, prompt_suffix, save_path):
    print(f"🎨 Generating {os.path.basename(save_path)}...")

    output = safe_replicate_call(
        client,
        {
            "input_image": open(input_path, "rb"),
            "prompt": f"{BASE_PROMPT}, {prompt_suffix}",
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
    img.save(save_path)

    print(f"💾 Saved: {save_path}")

# =========================
# MAIN
# =========================
def generate_all_faces(user, force=False):
    print("🚀 Generating identity-preserved faces...")

    input_path = get_user_image(user)

    user_output_dir = os.path.join(OUTPUT_DIR, user)
    ensure_dir(user_output_dir)

    client = replicate.Client()

    paths = {
        "front": os.path.join(user_output_dir, "front.png"),
        "left": os.path.join(user_output_dir, "left.png"),
        "right": os.path.join(user_output_dir, "right.png"),
    }

    # -------------------------
    # FRONT
    # -------------------------
    if force or not os.path.exists(paths["front"]):
        generate_face(
            client,
            input_path,
            "front facing, looking straight, symmetrical face",
            paths["front"]
        )
        time.sleep(2)
    else:
        print("✅ Skipping front (already exists)")

    # -------------------------
    # LEFT (stronger pose)
    # -------------------------
    if force or not os.path.exists(paths["left"]):
        generate_face(
            client,
            input_path,
            "head turned clearly to the left, 30 degree angle, eyes looking left",
            paths["left"]
        )
        time.sleep(2)
    else:
        print("✅ Skipping left (already exists)")

    # -------------------------
    # RIGHT (stronger pose)
    # -------------------------
    if force or not os.path.exists(paths["right"]):
        generate_face(
            client,
            input_path,
            "head turned clearly to the right, 30 degree angle, eyes looking right",
            paths["right"]
        )
        time.sleep(2)
    else:
        print("✅ Skipping right (already exists)")

    print(f"🎉 Done for user: {user}")

# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    generate_all_faces(args.user, args.force)