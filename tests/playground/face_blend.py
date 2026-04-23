import cv2
import numpy as np
import mediapipe as mp
import os
import argparse

# =============================
# CONFIG
# =============================
BASE_DIR = "tests\\playground\\"

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
REFERENCES_DIR = os.path.join(BASE_DIR, "references")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

mp_face_mesh = mp.solutions.face_mesh

# =============================
# FACE CONFIG
# =============================
face_config = {
    "scene_01.png": {"x": 297, "y": 608, "w": 192, "h": 180},
    "scene_02.png": {"x": 280, "y": 848, "w": 220, "h": 185},
    "scene_03.png": {"x": 365, "y": 764, "w": 200, "h": 175},
    "scene_04.png": {"x": 290, "y": 478, "w": 193, "h": 178},
    "scene_05.png": {"x": 180, "y": 524, "w": 193, "h": 158},
    "scene_06.png": {"x": 570, "y": 304, "w": 238, "h": 218},  # Need little face rotation to the left so that left cheek is little behind and right cheek is little forward. Otherwise, face looks too big in the scene.
    "scene_07.png": {"x": 220, "y": 238, "w": 255, "h": 228},
    "scene_08.png": {"x": 286, "y": 288, "w": 280, "h": 233},  # Need little face rotation to the right so that right cheek is little behind and left cheek is little forward. Otherwise, face looks too big in the scene.
    "scene_09.png": {"x": 293, "y": 240, "w": 295, "h": 248},
    "scene_10.png": {"x": 383, "y": 303, "w": 273, "h": 228},  # Need little face rotation to the right so that right cheek is little behind and left cheek is little forward. Otherwise, face looks too big in the scene.
}

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
# ALIGNMENT (STABLE)
# =============================
def align_face(user_img, user_pts, ref_pts, ref_shape):
    idx = [33, 263, 1, 61, 291, 199, 152]

    user_kp = np.array([user_pts[i] for i in idx], dtype=np.float32)
    ref_kp  = np.array([ref_pts[i] for i in idx], dtype=np.float32)

    M, _ = cv2.estimateAffinePartial2D(user_kp, ref_kp, method=cv2.LMEDS)

    if M is None:
        print("⚠️ Alignment failed")
        return user_img

    # prevent flip
    if np.linalg.det(M[:2, :2]) < 0:
        print("⚠️ Flip detected, skipping alignment")
        return user_img

    return cv2.warpAffine(
        user_img,
        M,
        (ref_shape[1], ref_shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101
    )

# =============================
# COLOR MATCH
# =============================
def match_color(src, dst):
    src_lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst_lab = cv2.cvtColor(dst, cv2.COLOR_BGR2LAB).astype(np.float32)

    for i in range(3):
        s_mean, s_std = src_lab[:,:,i].mean(), src_lab[:,:,i].std()
        d_mean, d_std = dst_lab[:,:,i].mean(), dst_lab[:,:,i].std()

        src_lab[:,:,i] = ((src_lab[:,:,i]-s_mean)/(s_std+1e-6))*d_std + d_mean

    return cv2.cvtColor(np.clip(src_lab,0,255).astype(np.uint8), cv2.COLOR_LAB2BGR)

# =============================
# LIGHT MATCH
# =============================
def match_light(face, roi):
    face = face.astype(np.float32)
    roi = roi.astype(np.float32)

    ratio = roi.mean() / (face.mean() + 1e-6)
    face *= ratio

    if roi[:,:,2].mean() > roi[:,:,0].mean():
        face[:,:,2] *= 1.05
        face[:,:,1] *= 1.02

    return np.clip(face,0,255).astype(np.uint8)

# =============================
# MASK
# =============================
def create_mask(w, h):
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, (w//2, h//2), (int(w*0.42), int(h*0.5)), 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (51,51), 25)

# =============================
# CORE
# =============================
def process_scene(template_path, reference_path, user_img):
    template = repo.load(template_path)
    reference = repo.load(reference_path)

    if template is None or reference is None:
        return None

    filename = os.path.basename(template_path)

    ref_pts = get_landmarks(reference)
    user_pts = get_landmarks(user_img)

    if ref_pts is None or user_pts is None:
        return None

    # ✅ SINGLE ALIGNMENT ONLY
    user_aligned = align_face(user_img, user_pts, ref_pts, reference.shape)

    warped = user_aligned.copy()

    # =============================
    # SAFE FACE EXTRACTION (FIXED)
    # =============================
    x, y, w, h = cv2.boundingRect(cv2.convexHull(ref_pts))

    H, W = warped.shape[:2]

    # clamp
    x = max(0, x)
    y = max(0, y)
    w = min(w, W - x)
    h = min(h, H - y)

    if w <= 0 or h <= 0:
        print("❌ Invalid bbox")
        return None

    face = warped[y:y+h, x:x+w]

    if face is None or face.size == 0:
        print("❌ Empty face crop")
        return None

    # =============================
    # SIZE + POSITION
    # =============================
    tx, ty = x, y
    tw, th = int(w * 1.1), int(h * 1.1)

    if filename in face_config:
        cfg = face_config[filename]
        tx, ty, tw, th = cfg["x"], cfg["y"], cfg["w"], cfg["h"]

    if tw <= 0 or th <= 0:
        print("❌ Invalid resize size")
        return None

    face = cv2.resize(face, (tw, th))

    # =============================
    # COLOR + LIGHT
    # =============================
    roi = template[ty:ty+th, tx:tx+tw]
    face = match_color(face, roi)
    face = match_light(face, roi)

    # =============================
    # MASK + BLEND
    # =============================
    mask = create_mask(tw, th)

    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

    canvas_face[ty:ty+th, tx:tx+tw] = face
    canvas_mask[ty:ty+th, tx:tx+tw] = mask

    center = (tx + tw//2, ty + th//2)

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
        r_dir = os.path.join(REFERENCES_DIR, s)

        templates = repo.list_files(t_dir)
        refs = repo.list_files(r_dir)

        for t, r in zip(templates, refs):
            out = process_scene(os.path.join(t_dir, t), os.path.join(r_dir, r), user_img)
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