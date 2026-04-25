"""
face_blend_v7.py

Reference-Free Face Overlay Engine (V7)

- Removes dependency on reference images
- Uses MediaPipe for face detection
- Uses V6 JSON for position, size, rotation
- Fully deterministic placement
"""

import cv2
import numpy as np
import mediapipe as mp
import os
import argparse
import json

# =============================
# CONFIG
# =============================
BASE_DIR = "tests\\playground\\"

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

V6_JSON_PATH = os.path.join(BASE_DIR, "forest_of_smiles_v7_final.json")

mp_face_mesh = mp.solutions.face_mesh

# =============================
# LOAD JSON
# =============================
def load_config():
    with open(V6_JSON_PATH, "r") as f:
        return json.load(f)

config = load_config()

# =============================
# IMAGE REPO
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
# FACE NORMALIZATION
# =============================
def extract_face(image, landmarks):
    hull = cv2.convexHull(landmarks)
    x, y, w, h = cv2.boundingRect(hull)

    face = image[y:y+h, x:x+w]
    return face

# =============================
# ROTATION
# =============================
def apply_rotation(face, yaw, pitch):
    h, w = face.shape[:2]
    center = (w // 2, h // 2)

    # yaw → rotation
    M = cv2.getRotationMatrix2D(center, yaw, 1.0)
    face = cv2.warpAffine(face, M, (w, h))

    # pitch → vertical scale
    scale_y = 1 + (pitch / 100.0)
    face = cv2.resize(face, (w, int(h * scale_y)))

    return face

# =============================
# COLOR + LIGHT
# =============================
def match_color(src, dst):
    src_lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst_lab = cv2.cvtColor(dst, cv2.COLOR_BGR2LAB).astype(np.float32)

    for i in range(3):
        s_mean, s_std = src_lab[:,:,i].mean(), src_lab[:,:,i].std()
        d_mean, d_std = dst_lab[:,:,i].mean(), dst_lab[:,:,i].std()

        src_lab[:,:,i] = ((src_lab[:,:,i]-s_mean)/(s_std+1e-6))*d_std + d_mean

    return cv2.cvtColor(np.clip(src_lab,0,255).astype(np.uint8), cv2.COLOR_LAB2BGR)

def match_light(face, roi):
    face = face.astype(np.float32)
    roi = roi.astype(np.float32)

    ratio = roi.mean() / (face.mean() + 1e-6)
    face *= ratio

    return np.clip(face,0,255).astype(np.uint8)

# =============================
# MASK
# =============================
def create_mask(w, h):
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, (w//2, h//2), (int(w*0.42), int(h*0.5)), 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (51,51), 25)

# =============================
# FACE ANCHOR
# =============================
def get_anchor(template):
    h, w = template.shape[:2]

    anchor = config["global"]["face_anchor"]

    cx = int(anchor["center"][0] * w)
    cy = int(anchor["center"][1] * h)

    fw = int(anchor["size_ratio"][0] * w)
    fh = int(anchor["size_ratio"][1] * h)

    yaw = anchor["rotation"]["yaw"]
    pitch = anchor["rotation"]["pitch"]

    return cx, cy, fw, fh, yaw, pitch

# =============================
# CORE
# =============================
def process_scene(template_path, user_img):
    template = repo.load(template_path)

    landmarks = get_landmarks(user_img)
    if landmarks is None:
        print("❌ No face detected")
        return None

    face = extract_face(user_img, landmarks)

    cx, cy, fw, fh, yaw, pitch = get_anchor(template)

    face = cv2.resize(face, (fw, fh))
    face = apply_rotation(face, yaw, pitch)

    # 🔥 CRITICAL FIX: force size back
    face = cv2.resize(face, (fw, fh))
    
    tx = cx - fw // 2
    ty = cy - fh // 2

    roi = template[ty:ty+fh, tx:tx+fw]

    face = match_color(face, roi)
    face = match_light(face, roi)

    mask = create_mask(fw, fh)

    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

    canvas_face[ty:ty+fh, tx:tx+fw] = face
    canvas_mask[ty:ty+fh, tx:tx+fw] = mask

    center = (cx, cy)

    return cv2.seamlessClone(canvas_face, template, canvas_mask, center, cv2.NORMAL_CLONE)

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
            out = process_scene(os.path.join(t_dir, t), user_img)
            if out is not None:
                out_path = os.path.join(OUTPUT_DIR, user, s, t)
                repo.save(out_path, out)

# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", default="all")
    args = parser.parse_args()

    process_user(args.user, args.story)