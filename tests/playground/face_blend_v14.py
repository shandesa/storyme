# tests/playground/face_blend_v13.py

import argparse
import os
import json
import time
import replicate
from PIL import Image, ImageDraw
from datetime import datetime


# -------------------------------
# Logger Utility
# -------------------------------
class Logger:
    @staticmethod
    def log(level, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {message}")

    @staticmethod
    def info(msg): Logger.log("INFO", msg)
    @staticmethod
    def debug(msg): Logger.log("DEBUG", msg)
    @staticmethod
    def warn(msg): Logger.log("WARN", msg)
    @staticmethod
    def error(msg): Logger.log("ERROR", msg)


# -------------------------------
# Config
# -------------------------------
class Config:
    BASE_PATH = "tests/playground"
    MAX_RETRIES = 3
    IMG_STRENGTH = 0.3


# -------------------------------
# Identity
# -------------------------------
class FaceIdentity:
    def __init__(self, user_dir):
        Logger.info(f"[FaceIdentity.__init__] user_dir={user_dir}")

        self.paths = {
            "front": os.path.join(user_dir, "front.jpg"),
            "left": os.path.join(user_dir, "left.jpg"),
            "right": os.path.join(user_dir, "right.jpg")
        }

    def validate(self):
        Logger.info("[FaceIdentity.validate] Validating face images")

        for k, v in self.paths.items():
            Logger.debug(f"Checking {k} -> {v}")
            if not os.path.exists(v):
                raise Exception(f"Missing {k} image: {v}")

        Logger.info("[FaceIdentity.validate] All face images valid")


def select_face(yaw, paths):
    Logger.info(f"[select_face] yaw={yaw}")

    if yaw < -3:
        Logger.info("Selecting LEFT face")
        return paths["left"]
    elif yaw > 3:
        Logger.info("Selecting RIGHT face")
        return paths["right"]

    Logger.info("Selecting FRONT face")
    return paths["front"]


# -------------------------------
# Pose Generator
# -------------------------------
class PoseGenerator:
    def generate(self, output_path):
        Logger.info(f"[PoseGenerator.generate] output_path={output_path}")

        img = Image.new("RGB", (512, 512), "black")
        draw = ImageDraw.Draw(img)

        draw.line((256, 100, 256, 300), fill="white", width=6)
        draw.line((256, 150, 200, 220), fill="white", width=6)
        draw.line((256, 150, 312, 220), fill="white", width=6)
        draw.line((256, 300, 200, 400), fill="white", width=6)
        draw.line((256, 300, 312, 400), fill="white", width=6)

        img.save(output_path)

        Logger.info(f"[PoseGenerator.generate] Pose saved")
        return output_path


# -------------------------------
# Prompt Builder
# -------------------------------
class PromptBuilder:
    def build(self, page):
        Logger.info("[PromptBuilder.build] Building prompt")

        emotion = page["character"]["emotion"]["type"]
        intensity = page["character"]["emotion"]["intensity"]
        scene = page["narrative"]["scene"]

        prompt = f"""
Preserve original background exactly.
Do not change environment or lighting.

Pixar-style 3D cartoon child added into the scene.

Scene: {scene}
Emotion: {emotion} ({intensity})

Soft lighting, cinematic, expressive face, consistent identity.
"""

        Logger.debug(f"[PromptBuilder.build] Prompt:\n{prompt}")
        return prompt


# -------------------------------
# Renderer
# -------------------------------
class Renderer:
    def __init__(self):
        Logger.info("[Renderer.__init__] Initializing Replicate client")
        self.client = replicate.Client()

    def generate(self, base_image, face_image, pose_image, prompt):
        Logger.info("[Renderer.generate] Starting generation")

        Logger.debug(f"base_image={base_image}")
        Logger.debug(f"face_image={face_image}")
        Logger.debug(f"pose_image={pose_image}")
        Logger.debug(f"prompt_length={len(prompt)}")

        try:
            output = self.client.run(
                "stability-ai/sdxl",
                input={
                    "prompt": prompt,
                    "image": open(base_image, "rb"),
                    "num_inference_steps": 30,
                    "guidance_scale": 5,
                    "strength": Config.IMG_STRENGTH
                }
            )

            Logger.info("[Renderer.generate] Generation successful")
            return output

        except Exception as e:
            Logger.error(f"[Renderer.generate] Error: {str(e)}")
            raise


# -------------------------------
# Quality Checker
# -------------------------------
class QualityChecker:
    def is_valid(self, path):
        Logger.info(f"[QualityChecker.is_valid] Checking {path}")

        if not os.path.exists(path):
            Logger.warn("File does not exist")
            return False

        size = os.path.getsize(path)
        Logger.debug(f"File size = {size}")

        if size < 1000:
            Logger.warn("File too small → invalid")
            return False

        Logger.info("File valid")
        return True


# -------------------------------
# Pipeline
# -------------------------------
class Pipeline:
    def __init__(self, user, story):
        Logger.info(f"[Pipeline.__init__] user={user}, story={story}")

        self.user = user
        self.story = story

        self.base = Config.BASE_PATH
        self.user_dir = os.path.join(self.base, "user_face", user)
        self.story_path = os.path.join(self.base, "stories", f"{story}.json")
        self.output_dir = os.path.join(self.base, "output", user, story)

        Logger.debug(f"user_dir={self.user_dir}")
        Logger.debug(f"story_path={self.story_path}")
        Logger.debug(f"output_dir={self.output_dir}")

        os.makedirs(self.output_dir, exist_ok=True)

        self.renderer = Renderer()
        self.pose_gen = PoseGenerator()
        self.quality = QualityChecker()

    def run(self):
        Logger.info("[Pipeline.run] Starting pipeline")

        identity = FaceIdentity(self.user_dir)
        identity.validate()

        Logger.info(f"Loading story JSON from {self.story_path}")

        with open(self.story_path) as f:
            story = json.load(f)

        prev_scene = None

        for page in story["pages"]:
            page_num = page["page_number"]
            Logger.info(f"\n========== PAGE {page_num} ==========")

            output_file = os.path.join(self.output_dir, f"page_{page_num}.png")
            Logger.debug(f"output_file={output_file}")

            # EVEN PAGE
            if not page["character"]["present"]:
                prev_scene = os.path.join(
                    self.base, "pre_generated", f"page_{page_num}.png"
                )

                Logger.info(f"[EVEN] Using pre-generated scene: {prev_scene}")

                if not os.path.exists(prev_scene):
                    raise Exception(f"Missing pre-generated page {page_num}")

                continue

            # ODD PAGE
            if not prev_scene:
                raise Exception(f"No base scene for page {page_num}")

            Logger.info(f"[ODD] Using base scene: {prev_scene}")

            yaw = page["character"]["head_pose"]["yaw"]
            face_img = select_face(yaw, identity.paths)

            prompt = PromptBuilder().build(page)

            pose_path = os.path.join(self.output_dir, f"pose_{page_num}.png")
            self.pose_gen.generate(pose_path)

            success = False

            for attempt in range(Config.MAX_RETRIES):
                Logger.info(f"[RETRY] Page {page_num} Attempt {attempt+1}")

                try:
                    result = self.renderer.generate(
                        prev_scene, face_img, pose_path, prompt
                    )

                    with open(output_file, "wb") as f:
                        f.write(result.read())

                    if self.quality.is_valid(output_file):
                        success = True
                        Logger.info(f"[SUCCESS] Page {page_num} generated")
                        break

                except Exception as e:
                    Logger.error(f"[RETRY ERROR] {str(e)}")

                Logger.warn("Retrying...")
                time.sleep(1)

            if not success:
                Logger.error(f"[FAILED] Page {page_num}")

            prev_scene = output_file

        Logger.info("[Pipeline.run] Completed")


# -------------------------------
# CLI
# -------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", required=True)

    args = parser.parse_args()

    Logger.info("[MAIN] Starting execution")

    Pipeline(args.user, args.story).run()

    Logger.info("[MAIN] Finished execution")