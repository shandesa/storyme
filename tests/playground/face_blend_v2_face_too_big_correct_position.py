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
            print("❌ No face detected")
            return None

        h, w = image.shape[:2]
        pts = np.array([
            (int(l.x * w), int(l.y * h))
            for l in result.multi_face_landmarks[0].landmark
        ])

        print("✅ Landmarks detected:", len(pts))
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

    print(f"🔄 Aligning face | angle: {angle:.2f}")

    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))


KEY_POINTS = [33, 263, 1, 61, 291, 199]


def extract_keypoints(pts):
    return np.array([pts[i] for i in KEY_POINTS], dtype=np.float32)


def warp_face(src_img, src_pts, dst_pts, size):
    M, _ = cv2.estimateAffinePartial2D(src_pts, dst_pts)
    if M is None:
        print("❌ Warp matrix failed")
        return None
    return cv2.warpAffine(src_img, M, size)


# =============================
# MASK
# =============================
def create_mask(shape, pts):
    mask = np.zeros(shape[:2], dtype=np.uint8)

    hull = cv2.convexHull(pts)
    cv2.fillConvexPoly(mask, hull, 255)

    mask = cv2.GaussianBlur(mask, (31, 31), 15)
    return mask


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

    print("📥 Loaded template & reference")

    ref_pts = get_landmarks(reference)
    user_pts = get_landmarks(user_img)

    if ref_pts is None or user_pts is None:
        print("❌ Landmark detection failed")
        return None

    user_aligned = align_face(user_img, user_pts)
    user_pts = get_landmarks(user_aligned)

    if user_pts is None:
        print("❌ Failed after alignment")
        return None

    ref_kp = extract_keypoints(ref_pts)
    user_kp = extract_keypoints(user_pts)

    warped = warp_face(
        user_aligned,
        user_kp,
        ref_kp,
        (reference.shape[1], reference.shape[0])
    )

    if warped is None:
        return None

    print("🎨 Affine warp complete")

    warped = match_color(warped, reference)

    mask = create_mask(reference.shape, ref_pts)

    # =============================
    # 🔥 FINAL CENTER FIX (UPWARD SHIFT)
    # =============================
    ys, xs = np.where(mask > 0)

    center_x = int(xs.mean())
    center_y = int(ys.mean())

    # 🔥 shift upward (critical fix)
    shift = int((max(ys) - min(ys)) * 0.18)
    center_y = center_y - shift

    center = (center_x, center_y)

    print(f"📍 Adjusted center: {center}")

    output = cv2.seamlessClone(
        warped,
        template,
        mask,
        center,
        cv2.NORMAL_CLONE
    )

    print("✅ Blending complete")

    return output


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

        t_path = os.path.join(TEMPLATES_DIR, story)
        r_path = os.path.join(REFERENCES_DIR, story)

        templates = repo.list_files(t_path)
        references = repo.list_files(r_path)

        for t, r in zip(templates, references):
            print(f"   ▶ Processing scene: {t}")

            result = process_scene(
                os.path.join(t_path, t),
                os.path.join(r_path, r),
                user_img
            )

            if result is None:
                print(f"   ❌ Failed: {t}")
                continue

            out_path = os.path.join(OUTPUT_DIR, user_name, story, t)
            repo.save_image(out_path, result)

            print(f"   ✅ Saved: {out_path}")

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