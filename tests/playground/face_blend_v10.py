"""
face_blend_v10_mesh.py

V10 – MediaPipe Mesh-Based Face Warping Engine

--------------------------------------------------
WHY THIS VERSION EXISTS
--------------------------------------------------
Previous versions (V7–V9) used rectangular face crops and global transforms.
Those approaches fail for yaw/pitch because a human face is NOT a flat plane.

This version upgrades the system to:

👉 Geometry-aware face transformation using MediaPipe Face Mesh

--------------------------------------------------
CORE APPROACH
--------------------------------------------------
1. Detect 468 facial landmarks using MediaPipe
2. Extract face region + landmarks
3. Triangulate landmarks (Delaunay triangulation)
4. Warp each triangle independently (piecewise affine)
5. Apply controlled yaw/pitch deformation to landmark positions
6. Blend into template using Poisson blending

--------------------------------------------------
WHY THIS WORKS
--------------------------------------------------
- Preserves facial proportions
- Allows directional deformation (yaw/pitch)
- Avoids distortion artifacts from global homography
- Still deterministic (no AI generation)

--------------------------------------------------
INPUT CONTROL (FROM YOUR JSON)
--------------------------------------------------
- center → placement
- size_ratio → scale
- rotation.roll → in-plane rotation
- rotation.yaw → horizontal mesh deformation
- rotation.pitch → vertical mesh deformation

--------------------------------------------------
LIMITATIONS
--------------------------------------------------
- Still not true 3D (no occlusion)
- Extreme angles (>30°) will still look unnatural
- Lighting is not physically modeled

--------------------------------------------------
DEPENDENCIES
--------------------------------------------------
opencv-python
mediapipe
numpy
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
# LOAD CONFIG
# =============================
def load_config():
    with open(JSON_PATH, "r") as f:
        return json.load(f)

config = load_config()


# =============================
# REPO
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
# TRIANGULATION
# =============================
def get_triangles(rect, points):
    subdiv = cv2.Subdiv2D(rect)
    for p in points:
        subdiv.insert((int(p[0]), int(p[1])))

    triangle_list = subdiv.getTriangleList()
    triangles = []

    for t in triangle_list:
        pts = [(t[0], t[1]), (t[2], t[3]), (t[4], t[5])]
        idx = []
        for pt in pts:
            for i, p in enumerate(points):
                if abs(pt[0]-p[0]) < 1 and abs(pt[1]-p[1]) < 1:
                    idx.append(i)
        if len(idx) == 3:
            triangles.append(idx)

    return triangles


# =============================
# APPLY YAW / PITCH TO LANDMARKS
# =============================
def deform_landmarks(landmarks, yaw, pitch):
    new_points = landmarks.copy().astype(np.float32)

    center_x = np.mean(landmarks[:, 0])
    center_y = np.mean(landmarks[:, 1])

    for i, (x, y) in enumerate(new_points):
        dx = x - center_x
        dy = y - center_y

        # Yaw: horizontal compression/expansion
        new_points[i][0] = x + dx * (yaw * 0.02)

        # Pitch: vertical compression
        new_points[i][1] = y + dy * (pitch * 0.015)

    return new_points


# =============================
# TRIANGLE WARP
# =============================
def warp_triangle(img, img_out, t1, t2):
    r1 = cv2.boundingRect(np.float32([t1]))
    r2 = cv2.boundingRect(np.float32([t2]))

    t1_rect = []
    t2_rect = []

    for i in range(3):
        t1_rect.append(((t1[i][0] - r1[0]), (t1[i][1] - r1[1])))
        t2_rect.append(((t2[i][0] - r2[0]), (t2[i][1] - r2[1])))

    mask = np.zeros((r2[3], r2[2], 3), dtype=np.float32)
    cv2.fillConvexPoly(mask, np.int32(t2_rect), (1.0, 1.0, 1.0))

    img1_rect = img[r1[1]:r1[1]+r1[3], r1[0]:r1[0]+r1[2]]

    size = (r2[2], r2[3])
    warp_mat = cv2.getAffineTransform(np.float32(t1_rect), np.float32(t2_rect))
    img2_rect = cv2.warpAffine(img1_rect, warp_mat, size, None,
                               flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REFLECT_101)

    img_out[r2[1]:r2[1]+r2[3], r2[0]:r2[0]+r2[2]] = \
        img_out[r2[1]:r2[1]+r2[3], r2[0]:r2[0]+r2[2]] * (1 - mask) + img2_rect * mask


# =============================
# ANCHOR
# =============================
def get_anchor(template, page_number):
    h, w = template.shape[:2]

    page_cfg = next((p for p in config["pages"] if p["page_number"] == page_number), {})

    anchor = page_cfg.get("face_anchor", config["global"]["default_face_anchor"])

    cx = int(anchor["center"][0] * w)
    cy = int(anchor["center"][1] * h)
    fw = int(anchor["size_ratio"][0] * w)
    fh = int(anchor["size_ratio"][1] * h)

    return cx, cy, fw, fh, anchor


# =============================
# CORE
# =============================
def process_scene(template_path, user_img, page_number):
    template = repo.load(template_path)

    landmarks = get_landmarks(user_img)
    if landmarks is None:
        return None

    cx, cy, fw, fh, anchor = get_anchor(template, page_number)

    yaw = anchor["rotation"]["yaw"]
    pitch = anchor["rotation"]["pitch"]
    roll = anchor["rotation"].get("roll", 0)

    # Resize user image
    face = cv2.resize(user_img, (fw, fh))

    landmarks = get_landmarks(face)
    if landmarks is None:
        return None

    # Apply deformation
    new_landmarks = deform_landmarks(landmarks, yaw, pitch)

    rect = (0, 0, fw, fh)
    triangles = get_triangles(rect, landmarks)

    warped_face = np.zeros_like(face, dtype=np.float32)

    for tri in triangles:
        t1 = [landmarks[i] for i in tri]
        t2 = [new_landmarks[i] for i in tri]
        warp_triangle(face, warped_face, t1, t2)

    warped_face = np.uint8(warped_face)

    # Roll
    M = cv2.getRotationMatrix2D((fw//2, fh//2), roll, 1.0)
    warped_face = cv2.warpAffine(warped_face, M, (fw, fh))

    tx = cx - fw//2
    ty = cy - fh//2

    mask = np.zeros(template.shape[:2], dtype=np.uint8)
    mask[ty:ty+fh, tx:tx+fw] = 255

    canvas = template.copy()
    canvas[ty:ty+fh, tx:tx+fw] = warped_face

    return cv2.seamlessClone(canvas, template, mask, (cx, cy), cv2.NORMAL_CLONE)


# =============================
# USER
# =============================
def process_user(user, story):
    user_path = os.path.join(USER_DIR, user)
    user_img = repo.load(os.path.join(user_path, repo.list_files(user_path)[0]))

    t_dir = os.path.join(TEMPLATES_DIR, story)
    templates = repo.list_files(t_dir)

    for t in templates:
        match = re.search(r'\d+', t)
        page_number = int(match.group()) if match else 1

        if page_number != 5:
            continue

        out = process_scene(os.path.join(t_dir, t), user_img, page_number)

        if out is not None:
            repo.save(os.path.join(OUTPUT_DIR, user, story, t), out)


# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", required=True)
    args = parser.parse_args()

    process_user(args.user, args.story)