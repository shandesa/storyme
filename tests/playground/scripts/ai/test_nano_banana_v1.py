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

# Current file:
# storyme/tests/playground/scripts/ai/test_nano_banana_v1.py
#
# parents[0] = ai
# parents[1] = scripts
# parents[2] = playground
#
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

    # File handler
    fh = logging.FileHandler(
        log_file,
        encoding="utf-8"
    )

    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # Console handler
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
# BASE PROMPT
# ============================================================

BASE_PROMPT = """
REFERENCE IMAGE PRIORITY: VERY HIGH

Use the uploaded image as the exact identity reference for the child.

The generated character MUST preserve:

* same face shape
* same eyes
* same smile
* same cheeks
* same hairstyle
* same hairline
* same ears
* same skin tone
* same child identity

The child must remain instantly recognizable as the person in the uploaded image.

Do NOT redesign the face.
Do NOT generate a different child.
Do NOT stylize the facial proportions too aggressively.

STYLE:

Warm cinematic lighting.
Soft pastel colors.
Magical jungle atmosphere.

SCENE:
A magical jungle entrance with tall trees, soft mist, golden morning sunlight filtering through leaves.

CHARACTER:

* age 4–6
* light yellow t-shirt
* beige shorts
* brown explorer hat with black lace band

COMPOSITION:

* horizontal 5:4 aspect ratio
* medium shot
* eye-level camera
* child positioned on left side
* right side softly blurred and empty for story text

LIGHTING:

* soft warm light from top-left
* evenly lit face
* no harsh shadows

IMPORTANT:
The face identity from the uploaded image is to be used as it is in the scene.

The result should look like:
“the same real child converted into a Pixar movie scene with no Pixar character stylization.”
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
                    f"\n\nADDITIONAL PAGE SCENE:\n"
                    f"{page_prompt}"
                )

            logger.info("Prompt Prepared")

            logger.info("===================================================")
            logger.info(f"FINAL PROMPT FOR PAGE {idx}")
            logger.info("===================================================")

            logger.info(final_prompt)

            logger.info("===================================================")
            logger.info(f"REFERENCE IMAGE PATH: {reference_image}")
            logger.info("===================================================")

            start_time = time.time()

            with open(reference_image, "rb") as img_file:

                output = replicate.run(
                    MODEL_NAME,
                    input={
                        "prompt": final_prompt,
                        "image_input": [img_file],
                        "aspect_ratio": "5:4",
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

        logger.info("===================================================")
        logger.info("ALL PAGES GENERATED SUCCESSFULLY")
        logger.info("===================================================")

    except Exception as e:

        logger.exception("Generation Failed")

        raise e


if __name__ == "__main__":
    main()