import cv2
import numpy as np
import mediapipe as mp
import os
import argparse
import traceback
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
        "x": 486,
        "y": 128,
        "w": 116,
        "h": 122
    },
    "scene_02.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_03.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_04.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_05.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_06.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_07.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_08.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_09.png": {
        "x": 586,
        "y": 148,
        "w": 116,
        "h": 122
    },
    "scene_10.png": {
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
        print(f"[shantanu][ImageRepository.load_image] Attempting to load: {path}")
        img = cv2.imread(path)
        if img is None:
            print(f"[shantanu][ImageRepository.load_image] ❌ FAILED to load: {path}")
        return img

    def save_image(self, path: str, image):
        print(f"[shantanu][ImageRepository.save_image] Attempting to save to: {path}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        success = cv2.imwrite(path, image)
        if success:
            print(f"[shantanu][ImageRepository.save_image] ✅ Successfully saved: {path}")
        else:
            print(f"[shantanu][ImageRepository.save_image] ❌ FAILED to save: {path}")

    def list_dirs(self, path: str) -> List[str]:
        print(f"[shantanu][ImageRepository.list_dirs] Scanning directories in: {path}")
        if not os.path.exists(path):
            print(f"[shantanu][ImageRepository.list_dirs] ❌ Path does not exist: {path}")
            return []
        dirs = sorted([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])
        print(f"[shantanu][ImageRepository.list_dirs] Found {len(dirs)} directories.")
        return dirs

    def list_files(self, path: str) -> List[str]:
        print(f"[shantanu][ImageRepository.list_files] Scanning files in: {path}")
        if not os.path.exists(path):
            print(f"[shantanu][ImageRepository.list_files] ❌ Path does not exist: {path}")
            return []
        files = sorted([f for f in os.listdir(path) if f.lower().endswith((".png", ".jpg", ".jpeg"))])
        print(f"[shantanu][ImageRepository.list_files] Found {len(files)} image files.")
        return files

repo = ImageRepository()

# =============================
# FACE UTILS
# =============================
def get_landmarks(image):
    print(f"[shantanu][get_landmarks] Initializing MediaPipe FaceMesh...")
    try:
        with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as mesh:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = mesh.process(rgb)

            if not result.multi_face_landmarks:
                print("[shantanu][get_landmarks] ❌ No face detected in the image.")
                return None

            h, w = image.shape[:2]
            pts = np.array([(int(l.x * w), int(l.y * h)) for l in result.multi_face_landmarks[0].landmark])
            print(f"[shantanu][get_landmarks] ✅ Successfully extracted {len(pts)} landmarks.")
            return pts
    except Exception as e:
        print(f"[shantanu][get_landmarks] ❌ CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        return None

def align_face(img, pts):
    print("[shantanu][align_face] Calculating rotation matrix for alignment...")
    left_eye, right_eye = pts[33], pts[263]
    dx = float(right_eye[0] - left_eye[0])
    dy = float(right_eye[1] - left_eye[1])
    angle = np.degrees(np.arctan2(dy, dx))
    center = ((left_eye[0] + right_eye[0]) / 2, (left_eye[1] + right_eye[1]) / 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    print(f"[shantanu][align_face] Rotating image by {angle:.2f} degrees.")
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))

def extract_face_crop(image, pts):
    print("[shantanu][extract_face_crop] Generating convex hull and bounding box...")
    hull = cv2.convexHull(pts)
    x, y, w, h = cv2.boundingRect(hull)
    pad = int(0.15 * h)
    y_pad = max(0, y - pad)
    h_pad = min(image.shape[0] - y_pad, h + pad)
    print(f"[shantanu][extract_face_crop] Final crop box: x={x}, y={y_pad}, w={w}, h={h_pad}")
    return image[y_pad:y_pad+h_pad, x:x+w]

# =============================
# CORE
# =============================
def process_scene(template_path, user_img):
    filename = os.path.basename(template_path)
    print(f"\n[shantanu][process_scene] >>> STARTING SCENE: {filename}")

    template = repo.load_image(template_path)
    if template is None: return None

    if filename not in face_config:
        print(f"[shantanu][process_scene] ❌ Missing config for {filename} in face_config dictionary!")
        return None

    box = face_config[filename]
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    print(f"[shantanu][process_scene] Target Template Box: x={x}, y={y}, w={w}, h={h}")

    # Step 1: Detect & Align
    user_pts = get_landmarks(user_img)
    if user_pts is None: return None

    aligned = align_face(user_img, user_pts)
    user_pts = get_landmarks(aligned) # Re-detect on aligned for precision
    if user_pts is None: return None

    face_crop = extract_face_crop(aligned, user_pts)

    # Step 2: Resize
    scale = 0.93
    target_w, target_h = int(w * scale), int(h * scale)
    print(f"[shantanu][process_scene] Resizing face crop to {target_w}x{target_h}")
    face_resized = cv2.resize(face_crop, (target_w, target_h))

    # Step 3: Masking
    print("[shantanu][process_scene] Creating soft elliptical mask...")
    mask = np.zeros((target_h, target_w), dtype=np.uint8)
    cv2.ellipse(mask, (target_w//2, target_h//2), (target_w//2, target_h//2), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (31, 31), 15)

    # Step 4: Canvas Placement
    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)
    x_offset = x + (w - target_w) // 2
    y_offset = y + (h - target_h) // 2
    
    print(f"[shantanu][process_scene] Offsetting face onto canvas at x={x_offset}, y={y_offset}")
    canvas_face[y_offset:y_offset+target_h, x_offset:x_offset+target_w] = face_resized
    canvas_mask[y_offset:y_offset+target_h, x_offset:x_offset+target_w] = mask

    # Step 5: Seamless Clone
    print("[shantanu][process_scene] Executing cv2.seamlessClone (this may take a second)...")
    try:
        center = (x + w // 2, y + h // 2)
        output = cv2.seamlessClone(canvas_face, template, canvas_mask, center, cv2.NORMAL_CLONE)
        print(f"[shantanu][process_scene] ✅ COMPLETED SCENE: {filename}")
        return output
    except Exception as e:
        print(f"[shantanu][process_scene] ❌ SEAMLESS CLONE ERROR: {str(e)}")
        return None

# =============================
# USER PROCESSING
# =============================
def process_user(user_name: str, story_name: str = "all"):
    print(f"[shantanu][process_user] STARTING SESSION for user: {user_name}")
    user_path = os.path.join(USER_DIR, user_name)
    user_images = repo.list_files(user_path)

    if not user_images:
        print(f"[shantanu][process_user] ❌ ERROR: No images found in {user_path}")
        return

    user_img = repo.load_image(os.path.join(user_path, user_images[0]))
    stories = repo.list_dirs(TEMPLATES_DIR) if story_name == "all" else [story_name]

    for story in stories:
        print(f"\n[shantanu][process_user] Processing Story Folder: {story}")
        t_path = os.path.join(TEMPLATES_DIR, story)
        templates = repo.list_files(t_path)

        for t in templates:
            result = process_scene(os.path.join(t_path, t), user_img)
            if result is not None:
                out_path = os.path.join(OUTPUT_DIR, user_name, story, t)
                repo.save_image(out_path, result)
            else:
                print(f"[shantanu][process_user] ⚠️ Skipping {t} due to processing failure.")

# =============================
# ENTRY
# =============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--story", default="all")
    args = parser.parse_args()

    print("[shantanu][main] Script initialized. Parsing arguments...")
    process_user(args.user, args.story)
    print("\n[shantanu][main] SCRIPT FINISHED.")