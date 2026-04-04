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

    center_x = float((left_eye[0] + right_eye[0]) / 2.0)
    center_y = float((left_eye[1] + right_eye[1]) / 2.0)
    center = (center_x, center_y)

    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))


KEY_POINTS = [33, 263, 1, 61, 291, 199]


def extract_keypoints(pts):
    return np.array([pts[i] for i in KEY_POINTS], dtype=np.float32)


def warp_face(src_img, src_pts, dst_pts, size):
    M, _ = cv2.estimateAffinePartial2D(src_pts, dst_pts)
    if M is None:
        return None
    return cv2.warpAffine(src_img, M, size)


# =============================
# FULL FACE MASK
# =============================
def create_mask(shape, pts):
    mask = np.zeros(shape[:2], dtype=np.uint8)

    hull = cv2.convexHull(pts)
    cv2.fillConvexPoly(mask, hull, 255)

    mask = cv2.GaussianBlur(mask, (31, 31), 15)
    return mask


# =============================
# FACE CENTER
# =============================
def get_face_center(pts):
    x, y, w, h = cv2.boundingRect(pts)
    return (int(x + w / 2), int(y + h / 2))


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
    template = repo.load_image(template_path)
    reference = repo.load_image(reference_path)

    if template is None or reference is None:
        return None

    ref_pts = get_landmarks(reference)
    user_pts = get_landmarks(user_img)

    if ref_pts is None or user_pts is None:
        return None

    user_aligned = align_face(user_img, user_pts)
    user_pts_aligned = get_landmarks(user_aligned)

    if user_pts_aligned is None:
        return None

    ref_kp = extract_keypoints(ref_pts)
    user_kp = extract_keypoints(user_pts_aligned)

    warped = warp_face(
        user_aligned,
        user_kp,
        ref_kp,
        (reference.shape[1], reference.shape[0])
    )

    if warped is None:
        return None

    mask = create_mask(reference.shape, ref_pts)
    warped = match_color(warped, reference)

    # =============================
    # 🔥 FINAL FIX: SCALE CENTER
    # =============================
    ref_h, ref_w = reference.shape[:2]
    tmp_h, tmp_w = template.shape[:2]

    x, y, w, h = cv2.boundingRect(ref_pts)

    center_x = int((x + w / 2) * (tmp_w / ref_w))
    center_y = int((y + h / 2) * (tmp_h / ref_h))

    center = (center_x, center_y)

    blended = cv2.seamlessClone(
        warped,
        template,
        mask,
        center,
        cv2.NORMAL_CLONE
    )

    return blended


# =============================
# USER PROCESSING
# =============================
def process_user(user_name: str, story_name: str = "all"):
    print(f"\n👤 Processing user: {user_name}")

    user_path = os.path.join(USER_DIR, user_name)
    print(f"🔍 Looking for user images in: {user_path}")

    if not os.path.exists(user_path):
        print(f"❌ User folder not found: {user_name}")
        return

    user_images = repo.list_files(user_path)

    if not user_images:
        print("❌ No user image found")
        return

    user_img_path = os.path.join(user_path, user_images[0])
    user_img = repo.load_image(user_img_path)

    print(f"📸 Using user image: {user_images[0]}")

    if story_name == "all":
        stories = repo.list_dirs(TEMPLATES_DIR)
    else:
        stories = [story_name]

    for story in stories:
        print(f"\n📖 Story: {story}")

        template_story_path = os.path.join(TEMPLATES_DIR, story)
        reference_story_path = os.path.join(REFERENCES_DIR, story)

        if not os.path.exists(template_story_path) or not os.path.exists(reference_story_path):
            print(f"❌ Story '{story}' not found")
            continue

        template_files = repo.list_files(template_story_path)
        reference_files = repo.list_files(reference_story_path)

        if len(template_files) != len(reference_files):
            print(f"⚠️ Mismatch in {story}")
            continue

        for t, r in zip(template_files, reference_files):
            scene_name = os.path.splitext(t)[0]

            print(f"   ▶ Processing scene: {scene_name}")

            result = process_scene(
                os.path.join(template_story_path, t),
                os.path.join(reference_story_path, r),
                user_img
            )

            if result is None:
                print(f"   ❌ Failed: {scene_name}")
                continue

            output_path = os.path.join(
                OUTPUT_DIR,
                user_name,
                story,
                f"{scene_name}.png"
            )

            repo.save_image(output_path, result)

            print(f"   ✅ Saved: {output_path}")

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