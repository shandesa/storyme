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
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_test")

# =========================
# 🔥 FULL VERSION HASH (CORRECT)
# =========================
MODEL_VERSION = "zedge/instantid:ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"

PROMPT = "Pixar-style cartoon child, soft lighting, friendly face"
NEGATIVE_PROMPT = "blurry, distorted, deformed, low quality"

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
# MAIN TEST
# =========================
def test_model(user):
    print("🚀 Running InstantID (correct config)...")

    ensure_dir(OUTPUT_DIR)
    input_path = get_user_image(user)

    client = replicate.Client()

    try:
        output = client.run(
            MODEL_VERSION,
            input={
                "input_image": open(input_path, "rb"),
                "prompt": PROMPT,
                "negative_prompt": NEGATIVE_PROMPT,

                # 🔥 ADD THESE (IMPORTANT)
                "num_outputs": 1,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,

                # Optional but stabilizes
                "identitynet_strength_ratio": 0.8,
                "adapter_strength": 0.8
            }
        )

        print("✅ Raw output:", output)

        try:
            # Extract FileOutput object
            file_obj = output["output_paths"][0]

            # Get actual URL
            img_url = file_obj.url

            print("🌐 URL:", img_url)

            img = download_image(img_url)

            out_path = os.path.join(OUTPUT_DIR, f"{user}_instantid.png")
            img.save(out_path)

            print("💾 Saved:", out_path)

        except Exception as e:
            print("❌ Failed to parse output:", str(e))

    except Exception as e:
        print("❌ ERROR:", str(e))


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    test_model(args.user)