import os
import cv2
import numpy as np
import mediapipe as mp

# =========================
# CONFIGURATION
# =========================
USER = "nikshay"
STORY_ID = "forrest_of_smiles"
BASE_DIR = "tests/playground"

USER_FACE_PATH = os.path.join(BASE_DIR, "user_face", USER, f"{USER}.png")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates", STORY_ID)
OUTPUT_DIR = os.path.join(BASE_DIR, "output", USER, STORY_ID)

# CALIBRATED CONFIG
FACE_CONFIG = {
    "scene_10.png": {"x": 383, "y": 325, "w": 273, "h": 228, "yaw": 35, "pitch": 0},
}

# Initialize MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True)

# =========================
# CORE ENGINE
# =========================

def get_final_3d_face(img, yaw, pitch):
    h, w = img.shape[:2]
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb_img)
    
    if not results.multi_face_landmarks:
        print("❌ CRITICAL: MediaPipe could not find a face in the input image!")
        return None

    # 1. Get Landmarks
    landmarks = results.multi_face_landmarks[0].landmark
    points = np.array([(int(l.x * w), int(l.y * h)) for l in landmarks])
    
    # Use nose bridge as pivot
    center_x = int(points[1, 0]) 
    center_y = int(points[1, 1])

    # 2. Create TIGHT isolation mask (No sunset background)
    mask = np.zeros((h, w), dtype=np.uint8)
    hull = cv2.convexHull(points)
    cv2.fillConvexPoly(mask, hull, 255)

    # 3. 3D Pivot Rotation
    focal_length = w * 1.5 
    K = np.array([[focal_length, 0, center_x], [0, focal_length, center_y], [0, 0, 1]], dtype=np.float32)
    R = cv2.Rodrigues(np.array([np.deg2rad(pitch), np.deg2rad(yaw), 0], dtype=np.float32))[0]
    
    map1, map2 = cv2.initUndistortRectifyMap(K, np.zeros(4), R, K, (w, h), cv2.CV_32FC1)
    
    # Warping face and mask
    warped_img = cv2.remap(img, map1, map2, cv2.INTER_LANCZOS4)
    warped_mask = cv2.remap(mask, map1, map2, cv2.INTER_NEAREST)

    # 4. LIGHT feathering (Reduced from 25 to 5 to keep features sharp)
    warped_mask = cv2.GaussianBlur(warped_mask, (11, 11), 5)
    
    res = cv2.cvtColor(warped_img, cv2.COLOR_BGR2BGRA)
    res[:, :, 3] = warped_mask
    return res

def main():
    print(f"🚀 Processing {USER}...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    raw_img = cv2.imread(USER_FACE_PATH)

    for scene, cfg in FACE_CONFIG.items():
        scene_path = os.path.join(TEMPLATE_DIR, scene)
        if not os.path.exists(scene_path): continue

        bg = cv2.imread(scene_path)
        face_3d = get_final_3d_face(raw_img, cfg['yaw'], cfg['pitch'])
        
        if face_3d is None: continue

        # Resize
        face_final = cv2.resize(face_3d, (cfg['w'], cfg['h']), interpolation=cv2.INTER_LANCZOS4)

        # Composite
        x, y, w, h = cfg['x'], cfg['y'], cfg['w'], cfg['h']
        center = (x + w // 2, y + h // 2)
        
        rgb_face = face_final[:, :, :3]
        mask = face_final[:, :, 3]

        # Use NORMAL_CLONE instead of MIXED if features are disappearing
        final_img = cv2.seamlessClone(rgb_face, bg, mask, center, cv2.NORMAL_CLONE)

        cv2.imwrite(os.path.join(OUTPUT_DIR, f"ULTIMATE_{scene}"), final_img)
        print(f"✅ Created ULTIMATE_{scene}")

if __name__ == "__main__":
    main()