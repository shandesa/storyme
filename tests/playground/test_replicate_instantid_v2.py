import os
import argparse
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
args = parser.parse_args()

# =========================
# PATHS
# =========================
BASE_DIR = "tests\\playground\\"
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_faces")

# =========================
# MODEL CONFIG
# =========================
MODEL_VERSION = "zedge/instantid:ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"

BASE_PROMPT = "Pixar-style cartoon child, soft lighting, friendly smile, clean face, centered portrait"
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
# CORE GENERATOR
# =========================
def generate_face(client, input_path, prompt_suffix, output_name):
    print(f"🎨 Generating {output_name}...")

    output = client.run(
        MODEL_VERSION,
        input={
            "input_image": open(input_path, "rb"),
            "prompt": f"{BASE_PROMPT}, {prompt_suffix}",
            "negative_prompt": NEGATIVE_PROMPT,

            # Stable params
            "num_outputs": 1,
            "num_inference_steps": 30,
            "guidance_scale": 7.5,

            # Identity preservation
            "identitynet_strength_ratio": 0.8,
            "adapter_strength": 0.8
        }
    )

    file_obj = output["output_paths"][0]
    img_url = file_obj.url

    img = download_image(img_url)

    return img


# =========================
# MAIN
# =========================
def generate_all_faces(user):
    print("🚀 Generating 3 identity-preserved faces...")

    input_path = get_user_image(user)

    user_output_dir = os.path.join(OUTPUT_DIR, user)
    ensure_dir(user_output_dir)

    client = replicate.Client()

    # -------------------------
    # FRONT
    # -------------------------
    front = generate_face(
        client,
        input_path,
        "front facing, looking straight, symmetrical face",
        "front"
    )
    front.save(os.path.join(user_output_dir, "front.png"))

    # -------------------------
    # LEFT
    # -------------------------
    left = generate_face(
        client,
        input_path,
        "looking slightly to the left, head turned 20 degrees left",
        "left"
    )
    left.save(os.path.join(user_output_dir, "left.png"))

    # -------------------------
    # RIGHT
    # -------------------------
    right = generate_face(
        client,
        input_path,
        "looking slightly to the right, head turned 20 degrees right",
        "right"
    )
    right.save(os.path.join(user_output_dir, "right.png"))

    print(f"✅ Saved all faces in: {user_output_dir}")


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    generate_all_faces(args.user)