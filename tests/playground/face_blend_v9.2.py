"""
face_blend_v9_2.py

Deterministic face overlay (FULL CONTROL MODE)

Key Design:
- Uses ONLY JSON rotation (no detection noise)
- NO clipping (full range works)
- Pose affects POSITION strongly
- No warp (stable)
"""

import cv2
import numpy as np
import mediapipe as mp
import os
import argparse
import json
import re

BASE_DIR = "tests\\playground\\"

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

JSON_PATH = os.path.join(BASE_DIR, "forest_of_smiles_v8_final.json")

mp_face_mesh = mp.solutions.face_mesh


# =============================
# CONFIG
# =============================
def load_config():
    with open(JSON_PATH, "r") as f:
        return json.load(f)

config = load_config()


# =============================
# IO
# =============================
class ImageRepository:
    def load(self, path):
        return cv2.imread(path)

    def save(self, path, img):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, img)
        print("Saved:", path)

    def list_files(self, path):
        return sorted([f for f in os.listdir(path) if f.lower().endswith((".png", ".jpg"))])

    def list_dirs(self, path):
        return sorted([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])

repo = ImageRepository()


# =============================
# LANDMARKS
# =============================
def get_landmarks(image):
    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1) as mesh:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = mesh.process(rgb)

        if not result.multi_face_landmarks:
            return None

        h, w = image.shape[:2]
        return np.array([(int(l.x*w), int(l.y*h)) for l in result.multi_face_landmarks[0].landmark])


# =============================
# FACE EXTRACTION
# =============================
def extract_face(image, landmarks):
    hull = cv2.convexHull(landmarks)
    x, y, w, h = cv2.boundingRect(hull)
    return image[y:y+h, x:x+w], (x, y, w, h)


# =============================
# MASK
# =============================
def create_mask(w, h):
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, (w//2, h//2), (int(w*0.42), int(h*0.5)), 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (51,51), 25)


# =============================
# ANCHOR
# =============================
def get_anchor(template, page_number):
    h, w = template.shape[:2]

    page_cfg = next(
        (p for p in config["pages"] if p["page_number"] == page_number),
        {}
    )

    anchor = page_cfg.get("face_anchor", config["global"]["default_face_anchor"])

    cx = int(anchor["center"][0] * w)
    cy = int(anchor["center"][1] * h)

    fw = int(anchor["size_ratio"][0] * w)
    fh = int(anchor["size_ratio"][1] * h)

    return cx, cy, fw, fh, anchor


# =============================
# SAFE ROI
# =============================
def safe_roi(template, tx, ty, fw, fh):
    h, w = template.shape[:2]
    return max(0, min(tx, w-fw)), max(0, min(ty, h-fh))


# =============================
# CORE
# =============================
def process_scene(template_path, user_img, page_number):
    template = repo.load(template_path)

    landmarks = get_landmarks(user_img)
    if landmarks is None:
        print("❌ No face detected")
        return None

    face, bbox = extract_face(user_img, landmarks)

    cx, cy, fw, fh, anchor = get_anchor(template, page_number)

    # 🔥 FULL CONTROL: ONLY JSON VALUES
    json_yaw = anchor["rotation"]["yaw"]
    json_pitch = anchor["rotation"]["pitch"]
    json_roll = anchor["rotation"].get("roll", 0)

    yaw = json_yaw
    pitch = json_pitch
    roll = json_roll

    # 🔥 STRONG MOVEMENT (VISIBLE)
    pose_dx = int(yaw * 12)
    pose_dy = int(pitch * 10)

    # Apply directly to anchor
    cx = cx + pose_dx
    cy = cy + pose_dy

    face = cv2.resize(face, (fw, fh))

    # Roll rotation
    M = cv2.getRotationMatrix2D((fw//2, fh//2), roll, 1.0)
    face = cv2.warpAffine(face, M, (fw, fh))

    tx = cx - fw//2
    ty = cy - fh//2

    tx, ty = safe_roi(template, tx, ty, fw, fh)

    mask = create_mask(fw, fh)

    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

    canvas_face[ty:ty+fh, tx:tx+fw] = face
    canvas_mask[ty:ty+fh, tx:tx+fw] = mask

    print(f"[Page {page_number}] yaw={yaw}, pitch={pitch}, roll={roll}, dx={pose_dx}, dy={pose_dy}")

    return cv2.seamlessClone(canvas_face, template, canvas_mask, (cx, cy), cv2.NORMAL_CLONE)


# =============================
# USER
# =============================
def process_user(user, story="all"):
    user_path = os.path.join(USER_DIR, user)
    user_img = repo.load(os.path.join(user_path, repo.list_files(user_path)[0]))

    stories = repo.list_dirs(TEMPLATES_DIR) if story=="all" else [story]

    for s in stories:
        t_dir = os.path.join(TEMPLATES_DIR, s)
        templates = repo.list_files(t_dir)

        for t in templates:
            match = re.search(r'\d+', t)
            page_number = int(match.group()) if match else 1

            if page_number != 5:
                continue

            out = process_scene(os.path.join(t_dir, t), user_img, page_number)

            if out is not None:
                repo.save(os.path.join(OUTPUT_DIR, user, s, t), out)


# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", default="all")
    args = parser.parse_args()

    process_user(args.user, args.story)