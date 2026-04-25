"""
face_blend_v9.py

V9 Face Overlay Engine

- Real head pose estimation (solvePnP)
- Perspective warp for yaw/pitch
- Roll rotation
- Per-page anchors (V8 JSON)
- Auto-anchor correction (V8.1)
- Safe ROI handling
"""

import cv2
import numpy as np
import mediapipe as mp
import os
import argparse
import json

BASE_DIR = "tests\\playground\\"

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

JSON_PATH = os.path.join(BASE_DIR, "forest_of_smiles_v8_final.json")

mp_face_mesh = mp.solutions.face_mesh


# =============================
# LOAD CONFIG
# =============================
def load_config():
    with open(JSON_PATH, "r") as f:
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
# FACE EXTRACTION
# =============================
def extract_face(image, landmarks):
    hull = cv2.convexHull(landmarks)
    x, y, w, h = cv2.boundingRect(hull)
    return image[y:y+h, x:x+w], (x, y, w, h)


# =============================
# FACE CENTER (AUTO ANCHOR)
# =============================
def compute_face_center(landmarks):
    left_eye = landmarks[33]
    right_eye = landmarks[263]
    nose = landmarks[1]

    cx = int((left_eye[0] + right_eye[0] + nose[0]) / 3)
    cy = int((left_eye[1] + right_eye[1] + nose[1]) / 3)

    return cx, cy


def normalize_face_center(landmarks, bbox):
    x, y, w, h = bbox
    cx, cy = compute_face_center(landmarks)

    nx = (cx - x) / w
    ny = (cy - y) / h

    return nx, ny


# =============================
# HEAD POSE (REAL)
# =============================
def estimate_head_pose(landmarks, image_shape):
    h, w = image_shape[:2]

    image_points = np.array([
        landmarks[1],    # nose
        landmarks[152],  # chin
        landmarks[33],   # left eye
        landmarks[263],  # right eye
        landmarks[61],   # left mouth
        landmarks[291]   # right mouth
    ], dtype="double")

    model_points = np.array([
        (0.0, 0.0, 0.0),
        (0.0, -63.6, -12.5),
        (-43.3, 32.7, -26.0),
        (43.3, 32.7, -26.0),
        (-28.9, -28.9, -24.1),
        (28.9, -28.9, -24.1)
    ])

    focal_length = w
    center = (w/2, h/2)

    camera_matrix = np.array([
        [focal_length, 0, center[0]],
        [0, focal_length, center[1]],
        [0, 0, 1]
    ])

    dist_coeffs = np.zeros((4,1))

    success, rotation_vec, _ = cv2.solvePnP(
        model_points,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE
    )

    return rotation_vec


def rotation_to_euler(rotation_vec):
    rmat, _ = cv2.Rodrigues(rotation_vec)

    sy = np.sqrt(rmat[0,0]**2 + rmat[1,0]**2)

    pitch = np.arctan2(-rmat[2,0], sy)
    yaw   = np.arctan2(rmat[1,0], rmat[0,0])
    roll  = np.arctan2(rmat[2,1], rmat[2,2])

    return np.degrees(yaw), np.degrees(pitch), np.degrees(roll)


# =============================
# PERSPECTIVE WARP
# =============================
def warp_face(face, yaw, pitch):
    h, w = face.shape[:2]

    dx = int(yaw * 0.6)
    dy = int(pitch * 0.6)

    src = np.float32([
        [0,0], [w,0], [0,h], [w,h]
    ])

    dst = np.float32([
        [0+dx, 0+dy],
        [w-dx, 0+dy],
        [0+dx, h-dy],
        [w-dx, h-dy]
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(face, M, (w, h))


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
    ratio = roi.mean() / (face.mean() + 1e-6)
    return np.clip(face * ratio, 0, 255).astype(np.uint8)


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
def get_anchor(template, page_index):
    h, w = template.shape[:2]

    page_cfg = next(
        (p for p in config["pages"] if p["page_number"] == page_index + 1),
        {}
    )

    anchor = page_cfg.get("face_anchor", config["global"]["default_face_anchor"])

    cx = int(anchor["center"][0] * w)
    cy = int(anchor["center"][1] * h)

    fw = int(anchor["size_ratio"][0] * w)
    fh = int(anchor["size_ratio"][1] * h)

    return cx, cy, fw, fh


# =============================
# SAFE ROI
# =============================
def safe_roi(template, tx, ty, fw, fh):
    h, w = template.shape[:2]

    tx = max(0, min(tx, w - fw))
    ty = max(0, min(ty, h - fh))

    return tx, ty


# =============================
# CORE
# =============================
def process_scene(template_path, user_img, page_index):
    template = repo.load(template_path)

    landmarks = get_landmarks(user_img)
    if landmarks is None:
        print("❌ No face detected")
        return None

    face, bbox = extract_face(user_img, landmarks)
    nx, ny = normalize_face_center(landmarks, bbox)

    # REAL POSE
    rotation_vec = estimate_head_pose(landmarks, user_img.shape)
    yaw, pitch, roll = rotation_to_euler(rotation_vec)

    cx, cy, fw, fh = get_anchor(template, page_index)

    face = cv2.resize(face, (fw, fh))

    # perspective warp
    face = warp_face(face, yaw, pitch)

    # roll
    M = cv2.getRotationMatrix2D((fw//2, fh//2), roll, 1.0)
    face = cv2.warpAffine(face, M, (fw, fh))

    # auto anchor correction
    ideal_x = 0.5
    ideal_y = 0.45

    dx = int((ideal_x - nx) * fw)
    dy = int((ideal_y - ny) * fh)

    tx = cx - fw // 2 + dx
    ty = cy - fh // 2 + dy

    tx, ty = safe_roi(template, tx, ty, fw, fh)

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

        for idx, t in enumerate(templates):
            if idx != 5:
                continue
            
            out = process_scene(os.path.join(t_dir, t), user_img, idx)

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