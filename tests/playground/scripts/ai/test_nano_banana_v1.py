# File: storyme/tests/playground/scripts/ai/test_nano_banana_v1.py

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import replicate


# ============================================================
# CONFIG
# ============================================================

MODEL_NAME = "google/nano-banana"

PLAYGROUND_DIR = Path(__file__).resolve().parents[2]

INPUT_DIR = PLAYGROUND_DIR / "input"
OUTPUT_DIR = PLAYGROUND_DIR / "output" / "nano_banana"
LOG_DIR = PLAYGROUND_DIR / "output" / "logs" / "nano_banana"

ENV_FILE = PLAYGROUND_DIR / "env"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# ENV LOADER
# ============================================================

def load_env_file(logger):

    logger.info(f"Loading env file: {ENV_FILE}")

    if not ENV_FILE.exists():
        raise FileNotFoundError(f"env file not found: {ENV_FILE}")

    with open(ENV_FILE, "r", encoding="utf-8") as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip()

            os.environ[key] = value

    replicate_key = os.environ.get("REPLICATE_KEY")

    if not replicate_key:
        raise Exception("REPLICATE_KEY not found in env file")

    os.environ["REPLICATE_API_TOKEN"] = replicate_key

    logger.info("REPLICATE_API_TOKEN loaded successfully")


# ============================================================
# LOGGING
# ============================================================

def setup_logger(name: str):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_file = LOG_DIR / f"{name}_{timestamp}.log"

    logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    fh = logging.FileHandler(
        log_file,
        encoding="utf-8"
    )

    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    ch = logging.StreamHandler(sys.stdout)

    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("===================================================")
    logger.info("Nano Banana Test Started")
    logger.info("===================================================")
    logger.info(f"Log File: {log_file}")

    return logger


# ============================================================
# PROMPT
# ============================================================

BASE_PROMPT = """
Use the uploaded reference image as the exact identity reference for the child.

The generated child must remain the SAME child from the uploaded image.

Preserve:
- same face
- same eyes
- same smile
- same hairstyle
- same skin tone
- same facial identity

The child should remain instantly recognizable across all story pages.

Soft cinematic animated storybook style.

Warm lighting.
Cute realistic child appearance.
Natural facial proportions.

CHARACTER:
- age 4-6
- light yellow t-shirt
- beige shorts
- brown explorer hat

SCENE:
Magical jungle forest with soft morning sunlight.

COMPOSITION:
- horizontal 5:4
- medium shot
- eye-level camera
- child on left side
- empty space on right side for story text

IMPORTANT:
Identity consistency is more important than artistic stylization.

The result should look like:
the same real child placed into an animated movie scene.
"""


# ============================================================
# INPUT LOADER
# ============================================================

def load_story_input(name: str):

    person_dir = INPUT_DIR / name

    story_json_path = person_dir / "story.json"

    if not story_json_path.exists():

        raise FileNotFoundError(
            f"story.json not found: {story_json_path}"
        )

    with open(story_json_path, "r", encoding="utf-8") as f:

        story_data = json.load(f)

    image_dir = person_dir / "images"

    if not image_dir.exists():

        raise FileNotFoundError(
            f"images folder missing: {image_dir}"
        )

    supported = [".jpg", ".jpeg", ".png", ".webp"]

    image_files = [

        p for p in image_dir.iterdir()

        if p.suffix.lower() in supported
    ]

    if not image_files:

        raise Exception(
            f"No reference image found in {image_dir}"
        )

    reference_image = image_files[0]

    return story_data, reference_image


# ============================================================
# SAVE OUTPUT
# ============================================================

def save_output_image(output, output_file, logger):

    logger.info("Saving output image...")

    logger.info(
        f"Output object type: {type(output)}"
    )

    if isinstance(output, list):
        output = output[0]

    if hasattr(output, "read"):

        data = output.read()

        with open(output_file, "wb") as f:
            f.write(data)

        return

    if isinstance(output, str):

        import requests

        response = requests.get(output)

        with open(output_file, "wb") as f:
            f.write(response.content)

        return

    raise Exception(
        f"Unsupported output type: {type(output)}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--name",
        required=True,
        help="Input folder name"
    )

    args = parser.parse_args()

    logger = setup_logger(args.name)

    try:

        # ----------------------------------------------------
        # LOAD ENV
        # ----------------------------------------------------

        load_env_file(logger)

        # ----------------------------------------------------
        # LOAD INPUT
        # ----------------------------------------------------

        logger.info(f"Loading input for: {args.name}")

        story_data, reference_image = load_story_input(
            args.name
        )

        logger.info(f"Reference Image: {reference_image}")

        pages = story_data.get("pages", [])

        if not pages:
            raise Exception("No pages found in story.json")

        logger.info(f"Total Pages: {len(pages)}")

        # ----------------------------------------------------
        # GENERATE PAGES
        # ----------------------------------------------------

        for idx, page in enumerate(pages, start=1):

            logger.info("---------------------------------------------------")
            logger.info(f"Generating Page {idx}")
            logger.info("---------------------------------------------------")

            page_prompt = page.get(
                "prompt",
                ""
            ).strip()

            final_prompt = BASE_PROMPT

            if page_prompt:

                final_prompt += (
                    f"\n\nPAGE SCENE:\n"
                    f"{page_prompt}"
                )

            logger.info("===================================================")
            logger.info(f"FINAL PROMPT FOR PAGE {idx}")
            logger.info("===================================================")

            logger.info(final_prompt)

            logger.info("===================================================")
            logger.info(f"REFERENCE IMAGE PATH: {reference_image}")
            logger.info("===================================================")

            start_time = time.time()

            reference_images = []

            # ------------------------------------------------
            # ORIGINAL IMAGE
            # ------------------------------------------------

            original_file = open(reference_image, "rb")

            reference_images.append(original_file)

            logger.info(
                f"Added original reference image: "
                f"{reference_image}"
            )

            # ------------------------------------------------
            # PREVIOUS PAGE FOR CONTINUITY
            # ------------------------------------------------

            previous_page_path = (
                OUTPUT_DIR /
                f"{args.name}_page_{idx-1}.png"
            )

            previous_page_file = None

            if idx > 1 and previous_page_path.exists():

                logger.info(
                    f"Using previous page reference: "
                    f"{previous_page_path}"
                )

                previous_page_file = open(
                    previous_page_path,
                    "rb"
                )

                reference_images.append(
                    previous_page_file
                )

            logger.info(
                f"Total reference images: "
                f"{len(reference_images)}"
            )

            # ------------------------------------------------
            # GENERATE
            # ------------------------------------------------

            output = replicate.run(
                MODEL_NAME,
                input={
                    "prompt": final_prompt,
                    "image_input": reference_images,
                    "aspect_ratio": "5:4",
                    "seed": 12345
                }
            )

            elapsed = round(
                time.time() - start_time,
                2
            )

            logger.info(
                f"Generation completed in "
                f"{elapsed} sec"
            )

            logger.info(
                f"Raw Replicate Output Type: "
                f"{type(output)}"
            )

            logger.info(
                f"Raw Replicate Output: "
                f"{output}"
            )

            output_file = (
                OUTPUT_DIR /
                f"{args.name}_page_{idx}.png"
            )

            save_output_image(
                output,
                output_file,
                logger
            )

            logger.info(f"Saved: {output_file}")

            # ------------------------------------------------
            # CLOSE FILES
            # ------------------------------------------------

            original_file.close()

            if previous_page_file:
                previous_page_file.close()

        logger.info("===================================================")
        logger.info("ALL PAGES GENERATED SUCCESSFULLY")
        logger.info("===================================================")

    except Exception as e:

        logger.exception("Generation Failed")

        raise e


if __name__ == "__main__":
    main()