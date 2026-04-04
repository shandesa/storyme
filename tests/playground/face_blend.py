import cv2
import numpy as np
import mediapipe as mp
import os
import argparse
from typing import List

# =============================
# CONFIG
# =============================
BASE_DIR = "tests\\playground\\"

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

mp_face_mesh = mp.solutions.face_mesh

# =============================
# 🔥 FACE TEMPLATE CONFIG
# =============================
face_config = {
    "scene_01.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    }
}

# =============================
# DATA LAYER
# =============================
class ImageRepository:
    def load_image(self, path: str):
        return cv2.imread(path)

    def save_image(self, path: str, image):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, image)

    def list_dirs(self, path: str) -> List[str]:
        return sorted([
            d for d in os.listdir(path)
            if os.path.isdir(os.path.join(path, d))
        ])

    def list_files(self, path: str) -> List[str]:
        return sorted([
            f for f in os.listdir(path)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ])

repo = ImageRepository()

# =============================
# FACE UTILS
# =============================
def get_landmarks(image):
    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as mesh:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = mesh.process(rgb)

        if not result.multi_face_landmarks:
            print("❌ No face detected")
            return None

        h, w = image.shape[:2]
        pts = np.array([(int(l.x * w), int(l.y * h)) for l in result.multi_face_landmarks[0].landmark])
        return pts


def align_face(img, pts):
    left_eye, right_eye = pts[33], pts[263]

    dx = float(right_eye[0] - left_eye[0])
    dy = float(right_eye[1] - left_eye[1])

    angle = np.degrees(np.arctan2(dy, dx))
    center = ((left_eye[0] + right_eye[0]) / 2, (left_eye[1] + right_eye[1]) / 2)

    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))


def extract_face_crop(image, pts):
    hull = cv2.convexHull(pts)

    x, y, w, h = cv2.boundingRect(hull)

    # Add padding
    pad = int(0.15 * h)
    y = max(0, y - pad)
    h = min(image.shape[0] - y, h + pad)

    face = image[y:y+h, x:x+w]
    return face


# =============================
# CORE
# =============================
def process_scene(template_path, user_img):

    template = repo.load_image(template_path)
    filename = os.path.basename(template_path)

    print(f"📥 Processing: {filename}")

    if filename not in face_config:
        print("❌ No face config found")
        return None

    box = face_config[filename]
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]

    # =============================
    # 🔥 FACE DETECT + ALIGN
    # =============================
    user_pts = get_landmarks(user_img)
    if user_pts is None:
        return None

    aligned = align_face(user_img, user_pts)
    user_pts = get_landmarks(aligned)

    if user_pts is None:
        return None

    face_crop = extract_face_crop(aligned, user_pts)

    # =============================
    # 🔥 RESIZE TO TEMPLATE BOX
    # =============================
    scale = 0.93  # slight shrink for better blending
    target_w = int(w * scale)
    target_h = int(h * scale)

    face_resized = cv2.resize(face_crop, (target_w, target_h))

    # =============================
    # 🔥 CREATE SOFT MASK
    # =============================
    mask = np.zeros((target_h, target_w), dtype=np.uint8)
    cv2.ellipse(mask, (target_w//2, target_h//2),
                (target_w//2, target_h//2),
                0, 0, 360, 255, -1)

    mask = cv2.GaussianBlur(mask, (31, 31), 15)

    # =============================
    # 🔥 PLACE ON CANVAS
    # =============================
    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

    x_offset = x + (w - target_w) // 2
    y_offset = y + (h - target_h) // 2

    canvas_face[y_offset:y_offset+target_h, x_offset:x_offset+target_w] = face_resized
    canvas_mask[y_offset:y_offset+target_h, x_offset:x_offset+target_w] = mask

    # =============================
    # 🔥 BLEND
    # =============================
    center = (x + w // 2, y + h // 2)

    output = cv2.seamlessClone(
        canvas_face,
        template,
        canvas_mask,
        center,
        cv2.NORMAL_CLONE
    )

    print("✅ Done")

    return output


# =============================
# USER PROCESSING
# =============================
def process_user(user_name: str, story_name: str = "all"):

    user_path = os.path.join(USER_DIR, user_name)
    user_images = repo.list_files(user_path)

    if not user_images:
        print("❌ No user image found")
        return

    user_img = repo.load_image(os.path.join(user_path, user_images[0]))

    if story_name == "all":
        stories = repo.list_dirs(TEMPLATES_DIR)
    else:
        stories = [story_name]

    for story in stories:

        t_path = os.path.join(TEMPLATES_DIR, story)
        templates = repo.list_files(t_path)

        for t in templates:

            result = process_scene(
                os.path.join(t_path, t),
                user_img
            )

            if result is None:
                continue

            out_path = os.path.join(OUTPUT_DIR, user_name, story, t)
            repo.save_image(out_path, result)

            print(f"✅ Saved: {out_path}")


# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--user", required=True)
    parser.add_argument("--story", default="all")

    args = parser.parse_args()

    process_user(args.user, args.story)