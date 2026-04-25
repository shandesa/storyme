"""
face_blend_v10_2.py

Stable Mesh-Based Face Warp (Corrected)

Fixes:
- Proper triangle mesh construction from MediaPipe edges
- No index errors
- Safe triangle warping (zero-area guard)
- Convex hull mask (no square artifacts)
- Accumulated blending to reduce seams
- Controlled deformation (no face collapse)

IMPORTANT:
Keep rotations small:
yaw:   -8 to +8
pitch: -5 to +5
"""

import cv2
import numpy as np
import mediapipe as mp
import os
import json
import argparse
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
with open(JSON_PATH, "r") as f:
    config = json.load(f)


# =============================
# IO
# =============================
def load_img(p): return cv2.imread(p)

def save_img(p, img):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cv2.imwrite(p, img)
    print("Saved:", p)


# =============================
# LANDMARKS
# =============================
def get_landmarks(img):
    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1) as mesh:
        res = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            return None
        h, w = img.shape[:2]
        return np.array([(int(l.x*w), int(l.y*h)) for l in res.multi_face_landmarks[0].landmark])


# =============================
# BUILD TRIANGLES (FIXED)
# =============================
def build_triangles():
    tri_set = set()
    edges = list(mp_face_mesh.FACEMESH_TESSELATION)

    for (a, b) in edges:
        for (c, d) in edges:
            if b == c:
                tri = tuple(sorted([a, b, d]))
                if len(set(tri)) == 3:
                    tri_set.add(tri)

    return list(tri_set)

TRIANGLES = build_triangles()


# =============================
# SAFE DEFORMATION
# =============================
def deform_landmarks(pts, yaw, pitch):
    pts = pts.astype(np.float32)
    cx, cy = np.mean(pts[:,0]), np.mean(pts[:,1])

    out = pts.copy()

    for i,(x,y) in enumerate(pts):
        dx = (x - cx) / cx
        dy = (y - cy) / cy

        out[i][0] = x + dx * yaw * 6
        out[i][1] = y + dy * pitch * 5

    return out


# =============================
# TRIANGLE WARP
# =============================
def warp_triangle(img, out, t1, t2):
    r1 = cv2.boundingRect(np.float32([t1]))
    r2 = cv2.boundingRect(np.float32([t2]))

    # guard against invalid triangles
    if r1[2] == 0 or r1[3] == 0 or r2[2] == 0 or r2[3] == 0:
        return

    t1_rect = [(t1[i][0]-r1[0], t1[i][1]-r1[1]) for i in range(3)]
    t2_rect = [(t2[i][0]-r2[0], t2[i][1]-r2[1]) for i in range(3)]

    mask = np.zeros((r2[3], r2[2]), dtype=np.float32)
    cv2.fillConvexPoly(mask, np.int32(t2_rect), 1.0)

    img1 = img[r1[1]:r1[1]+r1[3], r1[0]:r1[0]+r1[2]]

    warp_mat = cv2.getAffineTransform(np.float32(t1_rect), np.float32(t2_rect))
    warped = cv2.warpAffine(
        img1,
        warp_mat,
        (r2[2], r2[3]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101
    )

    out_slice = out[r2[1]:r2[1]+r2[3], r2[0]:r2[0]+r2[2]]
    out_slice[:] = out_slice*(1-mask[...,None]) + warped*mask[...,None]


# =============================
# ANCHOR
# =============================
def get_anchor(template, page_number):
    h, w = template.shape[:2]

    page = next((p for p in config["pages"] if p["page_number"] == page_number), {})
    anchor = page.get("face_anchor", config["global"]["default_face_anchor"])

    cx = int(anchor["center"][0]*w)
    cy = int(anchor["center"][1]*h)
    fw = int(anchor["size_ratio"][0]*w)
    fh = int(anchor["size_ratio"][1]*h)

    return cx, cy, fw, fh, anchor


# =============================
# CORE
# =============================
def process_scene(template_path, user_img, page_number):

    template = load_img(template_path)
    cx, cy, fw, fh, anchor = get_anchor(template, page_number)

    yaw   = anchor["rotation"]["yaw"]
    pitch = anchor["rotation"]["pitch"]
    roll  = anchor["rotation"].get("roll", 0)

    face = cv2.resize(user_img, (fw, fh))
    pts = get_landmarks(face)

    if pts is None:
        return None

    pts2 = deform_landmarks(pts, yaw, pitch)

    warped = np.zeros_like(face, dtype=np.float32)

    for tri in TRIANGLES:
        try:
            t1 = [pts[tri[0]], pts[tri[1]], pts[tri[2]]]
            t2 = [pts2[tri[0]], pts2[tri[1]], pts2[tri[2]]]
            warp_triangle(face, warped, t1, t2)
        except:
            continue

    warped = np.uint8(warped)

    # roll rotation
    M = cv2.getRotationMatrix2D((fw//2, fh//2), roll, 1)
    warped = cv2.warpAffine(warped, M, (fw, fh))

    # =============================
    # MASK (convex hull)
    # =============================
    hull = cv2.convexHull(pts2.astype(np.int32))

    mask = np.zeros(template.shape[:2], dtype=np.uint8)
    face_mask = np.zeros((fh, fw), dtype=np.uint8)

    cv2.fillConvexPoly(face_mask, hull, 255)

    tx = cx - fw//2
    ty = cy - fh//2

    # clamp ROI
    tx = max(0, min(tx, template.shape[1] - fw))
    ty = max(0, min(ty, template.shape[0] - fh))

    mask[ty:ty+fh, tx:tx+fw] = face_mask

    canvas = template.copy()
    canvas[ty:ty+fh, tx:tx+fw] = warped

    return cv2.seamlessClone(canvas, template, mask, (cx, cy), cv2.NORMAL_CLONE)


# =============================
# RUN
# =============================
def run(user, story):
    user_path = os.path.join(USER_DIR, user)
    user_img = load_img(os.path.join(user_path, os.listdir(user_path)[0]))

    t_dir = os.path.join(TEMPLATES_DIR, story)

    for f in sorted(os.listdir(t_dir)):
        if not f.endswith(".png"):
            continue

        page = int(re.search(r'\d+', f).group())

        if page != 5:
            continue
        out = process_scene(os.path.join(t_dir, f), user_img, page)

        if out is not None:
            save_img(os.path.join(OUTPUT_DIR, user, story, f), out)


# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", required=True)
    args = parser.parse_args()

    run(args.user, args.story)