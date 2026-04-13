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
REFERENCES_DIR = os.path.join(BASE_DIR, "references")
USER_DIR = os.path.join(BASE_DIR, "user_face")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated")

mp_face_mesh = mp.solutions.face_mesh

# =============================
# 🔥 FACE PLACEMENT CONFIG
# =============================
face_config = {
    "scene_01.png": {"x": 297, "y": 608, "w": 192, "h": 180},
    "scene_02.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_03.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_04.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_05.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_06.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_07.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_08.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_09.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_10.png": {"x": 586, "y": 148, "w": 116, "h": 122},
}

# =============================
# DATA LAYER
# =============================
class ImageRepository:
    def load_image(self, path: str):
        print(f"📥 Loading: {path}")
        return cv2.imread(path)

    def save_image(self, path: str, image):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, image)
        print(f"💾 Saved: {path}")

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
# FACE UTILITIES
# =============================
def get_landmarks(image):
    with mp_face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    ) as mesh:

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = mesh.process(rgb)

        if not result.multi_face_landmarks:
            print("❌ No face detected")
            return None

        h, w = image.shape[:2]
        pts = np.array([
            (int(l.x * w), int(l.y * h))
            for l in result.multi_face_landmarks[0].landmark
        ])

        return pts


def align_face(img, pts):
    left_eye = pts[33]
    right_eye = pts[263]

    dx = float(right_eye[0] - left_eye[0])
    dy = float(right_eye[1] - left_eye[1])

    angle = np.degrees(np.arctan2(dy, dx))

    center = (
        float((left_eye[0] + right_eye[0]) / 2),
        float((left_eye[1] + right_eye[1]) / 2)
    )

    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))


KEY_POINTS = [33, 263, 1, 61, 291, 199]

def extract_keypoints(pts):
    return np.array([pts[i] for i in KEY_POINTS], dtype=np.float32)


def match_color(src, dst):
    src = src.astype(np.float32)
    dst = dst.astype(np.float32)

    for i in range(3):
        src_mean, src_std = src[:, :, i].mean(), src[:, :, i].std()
        dst_mean, dst_std = dst[:, :, i].mean(), dst[:, :, i].std()

        src[:, :, i] = ((src[:, :, i] - src_mean) / (src_std + 1e-6)) * dst_std + dst_mean

    return np.clip(src, 0, 255).astype(np.uint8)


# =============================
# CORE PROCESSING
# =============================
def process_scene(template_path, reference_path, user_img):
    filename = os.path.basename(template_path)

    print(f"\n🎬 Processing: {filename}")

    template = repo.load_image(template_path)
    reference = repo.load_image(reference_path)

    if template is None or reference is None:
        return None

    if filename not in face_config:
        print("❌ No config found")
        return None

    # STEP 1: Landmarks
    ref_pts = get_landmarks(reference)
    user_pts = get_landmarks(user_img)

    if ref_pts is None or user_pts is None:
        return None

    # STEP 2: Align user face
    user_aligned = align_face(user_img, user_pts)
    user_pts = get_landmarks(user_aligned)

    if user_pts is None:
        return None

    # STEP 3: Warp (preserve expression)
    ref_kp = extract_keypoints(ref_pts)
    user_kp = extract_keypoints(user_pts)

    M, _ = cv2.estimateAffinePartial2D(user_kp, ref_kp)

    if M is None:
        print("❌ Warp failed")
        return None

    warped = cv2.warpAffine(
        user_aligned,
        M,
        (reference.shape[1], reference.shape[0])
    )

    # STEP 4: Extract ONLY face region
    x, y, w, h = cv2.boundingRect(cv2.convexHull(ref_pts))
    face_region = warped[y:y+h, x:x+w]

    # STEP 5: Resize using YOUR CONFIG (🔥 CONTROL HERE)
    box = face_config[filename]
    tx, ty, tw, th = box["x"], box["y"], box["w"], box["h"]

    face_resized = cv2.resize(face_region, (tw, th))

    # STEP 6: Color match
    template_roi = template[ty:ty+th, tx:tx+tw]
    face_colored = match_color(face_resized, template_roi)

    # STEP 7: Create soft mask
    mask = np.zeros((th, tw), dtype=np.uint8)
    cv2.ellipse(mask, (tw//2, th//2), (tw//2, th//2), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (21, 21), 11)

    # STEP 8: Prepare canvas
    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

    canvas_face[ty:ty+th, tx:tx+tw] = face_colored
    canvas_mask[ty:ty+th, tx:tx+tw] = mask

    center = (tx + tw // 2, ty + th // 2)

    # STEP 9: Blend
    output = cv2.seamlessClone(
        canvas_face,
        template,
        canvas_mask,
        center,
        cv2.NORMAL_CLONE
    )

    return output


# =============================
# USER PROCESSING
# =============================
def process_user(user_name: str, story_name: str = "all"):
    print(f"\n👤 Processing user: {user_name}")

    user_path = os.path.join(USER_DIR, user_name)

    if not os.path.exists(user_path):
        print("❌ User folder missing")
        return

    user_files = repo.list_files(user_path)

    if not user_files:
        print("❌ No user image found")
        return

    user_img = repo.load_image(os.path.join(user_path, user_files[0]))

    if story_name == "all":
        stories = repo.list_dirs(TEMPLATES_DIR)
    else:
        stories = [story_name]

    for story in stories:
        print(f"\n📖 Story: {story}")

        t_dir = os.path.join(TEMPLATES_DIR, story)
        r_dir = os.path.join(REFERENCES_DIR, story)

        templates = repo.list_files(t_dir)
        references = repo.list_files(r_dir)

        for t, r in zip(templates, references):
            result = process_scene(
                os.path.join(t_dir, t),
                os.path.join(r_dir, r),
                user_img
            )

            if result is None:
                continue

            out_path = os.path.join(OUTPUT_DIR, user_name, story, t)
            repo.save_image(out_path, result)

    print("\n🎉 Done!")


# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", default="all")
    args = parser.parse_args()

    process_user(args.user, args.story)