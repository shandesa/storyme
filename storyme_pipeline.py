#!/usr/bin/env python3
"""
StoryMe — Production Face Personalization Pipeline

A modern, modular pipeline for transforming a real child's face into a
stylized, storybook-friendly face and blending it naturally into an
illustrated template.

Modules:
    1. FaceDetector      — MediaPipe face detection + landmarks
    2. FaceParser        — BiSeNet face segmentation (skin/hair/bg mask)
    3. FaceProcessor     — Crop, normalize, resize
    4. FaceStyler        — AnimeGANv2 cartoon stylization
    5. FaceBlender       — OpenCV seamlessClone (Poisson blending)
    6. TemplateRenderer  — White-circle detection, name rendering

Requirements:
    pip install opencv-python pillow numpy mediapipe torch torchvision gdown

Usage (CLI):
    python storyme_pipeline.py template.png face.jpg "Shan"
    python storyme_pipeline.py template.png face.jpg "Shan" --output result.png

Usage (library):
    from storyme_pipeline import StoryMePipeline, PipelineConfig
    pipe = StoryMePipeline(PipelineConfig())
    pipe.run("template.png", "face.jpg", "Shan", "result.png")
"""

from __future__ import annotations

import sys
import os
import logging
import hashlib
import argparse
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision

import mediapipe as mp

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("storyme")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """All tuneable knobs in one place."""

    weights_dir: Path = field(
        default_factory=lambda: Path.home() / ".storyme" / "weights"
    )

    # Face detection
    detection_confidence: float = 0.5

    # Face crop padding (fraction of bbox size)
    face_pad_top: float = 0.25
    face_pad_bottom: float = 0.10
    face_pad_side: float = 0.15

    # BiSeNet
    bisenet_input_size: int = 512
    # Labels: 1=skin 2-3=brows 4-5=eyes 6=glasses 10=nose 11-13=mouth/lips
    face_labels: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 10, 11, 12, 13)

    # AnimeGANv2
    animegan_input_size: int = 512
    stylize_strength: float = 1.0
    stylize_saturation_boost: float = 1.10

    # Blending
    feather_radius: int = 12
    seamless_clone_flag: int = cv2.NORMAL_CLONE

    # Text rendering
    text_color: Tuple[int, int, int] = (80, 60, 30)

    # Template analysis
    white_threshold: int = 225


# =========================================================================
#  MODEL ARCHITECTURES
# =========================================================================

# -------------------------------------------------------------------------
#  BiSeNet  (face-parsing.PyTorch — zllrunning)
#  Pretrained weights: 79999_iter.pth  (~50 MB, 19-class face parsing)
# -------------------------------------------------------------------------

class _ConvBNReLU(nn.Module):
    def __init__(self, ic, oc, ks=3, s=1, p=1):
        super().__init__()
        self.conv = nn.Conv2d(ic, oc, ks, s, p, bias=False)
        self.bn = nn.BatchNorm2d(oc)

    def forward(self, x):
        return F.relu(self.bn(self.conv(x)), inplace=True)


class _BiSeNetOutput(nn.Module):
    def __init__(self, ic, mc, n_classes):
        super().__init__()
        self.conv = _ConvBNReLU(ic, mc)
        self.conv_out = nn.Conv2d(mc, n_classes, 1, bias=False)

    def forward(self, x):
        return self.conv_out(self.conv(x))


class _ARM(nn.Module):
    """Attention Refinement Module."""
    def __init__(self, ic, oc):
        super().__init__()
        self.conv = _ConvBNReLU(ic, oc)
        self.conv_atten = nn.Conv2d(oc, oc, 1, bias=False)
        self.bn_atten = nn.BatchNorm2d(oc)

    def forward(self, x):
        feat = self.conv(x)
        a = F.avg_pool2d(feat, feat.size()[2:])
        a = torch.sigmoid(self.bn_atten(self.conv_atten(a)))
        return feat * a


class _Resnet18Backbone(nn.Module):
    """Extract multi-scale features from torchvision ResNet-18."""
    def __init__(self):
        super().__init__()
        r = torchvision.models.resnet18(weights=None)
        self.conv1 = r.conv1
        self.bn1 = r.bn1
        self.relu = r.relu
        self.maxpool = r.maxpool
        self.layer1 = r.layer1   # 64ch  /4
        self.layer2 = r.layer2   # 128ch /8
        self.layer3 = r.layer3   # 256ch /16
        self.layer4 = r.layer4   # 512ch /32

    def forward(self, x):
        x = self.relu(self.bn1(self.conv1(x)))
        x = self.maxpool(x)
        x = self.layer1(x)
        f8 = self.layer2(x)
        f16 = self.layer3(f8)
        f32 = self.layer4(f16)
        return f8, f16, f32


class _ContextPath(nn.Module):
    def __init__(self):
        super().__init__()
        self.resnet = _Resnet18Backbone()
        self.arm16 = _ARM(256, 128)
        self.arm32 = _ARM(512, 128)
        self.conv_head32 = _ConvBNReLU(128, 128)
        self.conv_head16 = _ConvBNReLU(128, 128)
        self.conv_avg = _ConvBNReLU(512, 128, ks=1, s=1, p=0)

    def forward(self, x):
        f8, f16, f32 = self.resnet(x)
        sz8, sz16, sz32 = f8.shape[2:], f16.shape[2:], f32.shape[2:]

        avg = F.avg_pool2d(f32, sz32)
        avg = self.conv_avg(avg)
        avg_up = F.interpolate(avg, sz32, mode="nearest")

        f32a = self.arm32(f32) + avg_up
        f32u = self.conv_head32(F.interpolate(f32a, sz16, mode="nearest"))

        f16a = self.arm16(f16) + f32u
        f16u = self.conv_head16(F.interpolate(f16a, sz8, mode="nearest"))

        return f8, f16u, f32u


class _FFM(nn.Module):
    """Feature Fusion Module."""
    def __init__(self, ic, oc):
        super().__init__()
        self.convblk = _ConvBNReLU(ic, oc, ks=1, s=1, p=0)
        self.conv1 = nn.Conv2d(oc, oc // 4, 1, bias=False)
        self.conv2 = nn.Conv2d(oc // 4, oc, 1, bias=False)

    def forward(self, sp, cp):
        feat = self.convblk(torch.cat([sp, cp], dim=1))
        a = F.avg_pool2d(feat, feat.shape[2:])
        a = torch.sigmoid(self.conv2(F.relu(self.conv1(a), inplace=True)))
        return feat * a + feat


class BiSeNet(nn.Module):
    """19-class face segmentation network."""
    def __init__(self, n_classes: int = 19):
        super().__init__()
        self.cp = _ContextPath()
        self.ffm = _FFM(256, 256)
        self.conv_out = _BiSeNetOutput(256, 256, n_classes)
        self.conv_out16 = _BiSeNetOutput(128, 64, n_classes)
        self.conv_out32 = _BiSeNetOutput(128, 64, n_classes)

    def forward(self, x):
        H, W = x.shape[2:]
        f8, cp8, cp16 = self.cp(x)
        fuse = self.ffm(f8, cp8)
        out = F.interpolate(self.conv_out(fuse), (H, W), mode="bilinear", align_corners=True)
        out16 = F.interpolate(self.conv_out16(cp8), (H, W), mode="bilinear", align_corners=True)
        out32 = F.interpolate(self.conv_out32(cp16), (H, W), mode="bilinear", align_corners=True)
        return out, out16, out32


# -------------------------------------------------------------------------
#  AnimeGANv2 Generator  (bryandlee/animegan2-pytorch)
#  Pretrained weights: face_paint_512_v2.pt  (~8 MB)
# -------------------------------------------------------------------------

class _ConvNormLReLU(nn.Sequential):
    def __init__(self, ic, oc, ks=3, s=1, p=1, groups=1, bias=False):
        super().__init__(
            nn.ReflectionPad2d(p),
            nn.Conv2d(ic, oc, ks, s, 0, groups=groups, bias=bias),
            nn.GroupNorm(1, oc, affine=True),
            nn.LeakyReLU(0.2, inplace=True),
        )


class _InvResBlock(nn.Module):
    def __init__(self, ic, oc, expand=2):
        super().__init__()
        self.skip = ic == oc
        mid = int(round(ic * expand))
        layers = []
        if expand != 1:
            layers.append(_ConvNormLReLU(ic, mid, ks=1, p=0))
        layers.append(_ConvNormLReLU(mid, mid, groups=mid, bias=True))
        layers.append(nn.Conv2d(mid, oc, 1, bias=False))
        layers.append(nn.GroupNorm(1, oc, affine=True))
        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        out = self.layers(x)
        return x + out if self.skip else out


class AnimeGANv2(nn.Module):
    """Photo-to-anime generator."""
    def __init__(self):
        super().__init__()
        self.block_a = nn.Sequential(
            _ConvNormLReLU(3, 32, ks=7, p=3),
            _ConvNormLReLU(32, 64, s=2, p=(0, 1, 0, 1)),
            _ConvNormLReLU(64, 64),
        )
        self.block_b = nn.Sequential(
            _ConvNormLReLU(64, 128, s=2, p=(0, 1, 0, 1)),
            _ConvNormLReLU(128, 128),
        )
        self.block_c = nn.Sequential(
            _ConvNormLReLU(128, 128),
            _InvResBlock(128, 256, 2),
            _InvResBlock(256, 256, 2),
            _InvResBlock(256, 256, 2),
            _InvResBlock(256, 256, 2),
            _ConvNormLReLU(256, 128),
        )
        self.block_d = nn.Sequential(
            _ConvNormLReLU(128, 128),
            _ConvNormLReLU(128, 128),
        )
        self.block_e = nn.Sequential(
            _ConvNormLReLU(128, 64),
            _ConvNormLReLU(64, 64),
            _ConvNormLReLU(64, 32, ks=7, p=3),
        )
        self.out_layer = nn.Sequential(
            nn.Conv2d(32, 3, 1, bias=False),
            nn.Tanh(),
        )

    def forward(self, x):
        a = self.block_a(x)
        half = a.shape[2:]
        b = self.block_b(a)
        c = self.block_c(b)
        c = F.interpolate(c, half, mode="bilinear", align_corners=True)
        d = self.block_d(c)
        e = F.interpolate(d, (half[0] * 2, half[1] * 2), mode="bilinear", align_corners=False)
        e = self.block_e(e)
        return self.out_layer(e)


# =========================================================================
#  WEIGHT MANAGEMENT
# =========================================================================

BISENET_GDRIVE_ID = "154JgKpzCPW82qINcVieuPH3fZ2e0P812"
ANIMEGAN_URL = (
    "https://github.com/bryandlee/animegan2-pytorch/raw/main/"
    "weights/face_paint_512_v2.pt"
)


class WeightManager:
    """Download and cache pretrained model weights."""

    def __init__(self, weights_dir: Path):
        self.dir = weights_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- BiSeNet --

    @property
    def bisenet_path(self) -> Path:
        return self.dir / "bisenet_79999_iter.pth"

    def ensure_bisenet(self) -> Path:
        if self.bisenet_path.exists():
            return self.bisenet_path
        log.info("Downloading BiSeNet face-parsing weights (~50 MB) …")
        try:
            import gdown
            gdown.download(
                f"https://drive.google.com/uc?id={BISENET_GDRIVE_ID}",
                str(self.bisenet_path),
                quiet=False,
            )
        except Exception as e:
            log.warning(f"gdown failed ({e}). Trying torch.hub …")
            try:
                torch.hub.download_url_to_file(
                    f"https://drive.google.com/uc?export=download&id={BISENET_GDRIVE_ID}",
                    str(self.bisenet_path),
                )
            except Exception as e2:
                raise RuntimeError(
                    f"Cannot download BiSeNet weights.\n"
                    f"Please download manually:\n"
                    f"  pip install gdown && gdown {BISENET_GDRIVE_ID}\n"
                    f"Then place the file at: {self.bisenet_path}"
                ) from e2
        return self.bisenet_path

    # -- AnimeGANv2 --

    @property
    def animegan_path(self) -> Path:
        return self.dir / "face_paint_512_v2.pt"

    def ensure_animegan(self) -> Path:
        if self.animegan_path.exists():
            return self.animegan_path
        log.info("Downloading AnimeGANv2 weights (~8 MB) …")
        try:
            torch.hub.download_url_to_file(ANIMEGAN_URL, str(self.animegan_path))
        except Exception as e:
            raise RuntimeError(
                f"Cannot download AnimeGANv2 weights.\n"
                f"Please download manually from:\n"
                f"  {ANIMEGAN_URL}\n"
                f"Then place the file at: {self.animegan_path}"
            ) from e
        return self.animegan_path


# =========================================================================
#  FONT LOADING
# =========================================================================

_FONT_PATHS = [
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# =========================================================================
#  1. FACE DETECTOR  (MediaPipe)
# =========================================================================

class FaceDetector:
    """Detect faces using MediaPipe Face Detection.

    Returns bounding box + 6 key-points for the largest face.
    """

    def __init__(self, min_confidence: float = 0.5):
        self._mp_face = mp.solutions.face_detection
        self._det = self._mp_face.FaceDetection(
            model_selection=1,               # full-range model
            min_detection_confidence=min_confidence,
        )

    def detect(
        self, image: np.ndarray
    ) -> Optional[Dict[str, Any]]:
        """Detect the largest face in a BGR image.

        Returns dict with keys:
            bbox  — (x, y, w, h) in pixels
            landmarks — list of (x, y) for 6 key-points
            confidence — detection score
        Or None if no face found.
        """
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._det.process(rgb)

        if not results.detections:
            return None

        h_img, w_img = image.shape[:2]
        best = None
        best_area = 0

        for det in results.detections:
            bb = det.location_data.relative_bounding_box
            x = int(bb.xmin * w_img)
            y = int(bb.ymin * h_img)
            w = int(bb.width * w_img)
            h = int(bb.height * h_img)
            area = w * h
            if area > best_area:
                best_area = area
                kps = []
                for kp in det.location_data.relative_keypoints:
                    kps.append((int(kp.x * w_img), int(kp.y * h_img)))
                best = {
                    "bbox": (x, y, w, h),
                    "landmarks": kps,
                    "confidence": det.score[0],
                }

        return best

    def close(self):
        self._det.close()


# =========================================================================
#  2. FACE PARSER  (BiSeNet)
# =========================================================================

class FaceParser:
    """Generate a segmentation mask separating face, hair, background.

    Uses BiSeNet pretrained on CelebAMask-HQ (19 classes).
    Falls back to a convex-hull mask from MediaPipe landmarks when
    BiSeNet weights are unavailable.
    """

    IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, config: PipelineConfig, weights_mgr: WeightManager):
        self._cfg = config
        self._model: Optional[BiSeNet] = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._weights_mgr = weights_mgr

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            path = self._weights_mgr.ensure_bisenet()
            model = BiSeNet(n_classes=19)
            state = torch.load(str(path), map_location=self._device, weights_only=True)
            model.load_state_dict(state)
            model.to(self._device).eval()
            self._model = model
            log.info("BiSeNet face parser loaded")
        except Exception as e:
            log.warning(f"BiSeNet unavailable ({e}). Will use landmark-based mask.")

    def parse(
        self, face_bgr: np.ndarray, landmarks: Optional[List[Tuple[int, int]]] = None
    ) -> np.ndarray:
        """Return a float32 mask [0..1] same size as face_bgr (H, W)."""
        self._ensure_model()

        if self._model is not None:
            return self._parse_bisenet(face_bgr)
        elif landmarks:
            return self._parse_landmarks(face_bgr, landmarks)
        else:
            return self._parse_ellipse(face_bgr)

    def _parse_bisenet(self, face_bgr: np.ndarray) -> np.ndarray:
        h, w = face_bgr.shape[:2]
        sz = self._cfg.bisenet_input_size

        # Preprocess: resize → normalise (ImageNet) → CHW tensor
        rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (sz, sz), interpolation=cv2.INTER_LINEAR)
        inp = (resized.astype(np.float32) / 255.0 - self.IMAGENET_MEAN) / self.IMAGENET_STD
        tensor = torch.from_numpy(inp.transpose(2, 0, 1)).unsqueeze(0).to(self._device)

        with torch.no_grad():
            out = self._model(tensor)[0]  # main output
        seg = out.squeeze(0).argmax(0).cpu().numpy().astype(np.uint8)

        # Build binary mask from face labels
        mask = np.zeros_like(seg, dtype=np.float32)
        for lbl in self._cfg.face_labels:
            mask[seg == lbl] = 1.0

        # Resize back to original
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
        return mask

    @staticmethod
    def _parse_landmarks(
        face_bgr: np.ndarray, landmarks: List[Tuple[int, int]]
    ) -> np.ndarray:
        h, w = face_bgr.shape[:2]
        pts = np.array(landmarks, dtype=np.int32)
        hull = cv2.convexHull(pts)
        mask = np.zeros((h, w), dtype=np.float32)
        cv2.fillConvexPoly(mask, hull, 1.0)
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=8)
        return mask

    @staticmethod
    def _parse_ellipse(face_bgr: np.ndarray) -> np.ndarray:
        h, w = face_bgr.shape[:2]
        mask = np.zeros((h, w), dtype=np.float32)
        cx, cy = w // 2, h // 2
        axes = (int(w * 0.42), int(h * 0.46))
        cv2.ellipse(mask, (cx, cy), axes, 0, 0, 360, 1.0, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(6, w // 20))
        return mask


# =========================================================================
#  3. FACE PROCESSOR
# =========================================================================

class FaceProcessor:
    """Crop, normalise brightness/contrast, resize."""

    def __init__(self, config: PipelineConfig):
        self._cfg = config

    def crop_face(
        self, image: np.ndarray, bbox: Tuple[int, int, int, int]
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """Crop face with configurable padding. Returns (crop, adjusted_bbox)."""
        x, y, w, h = bbox
        ih, iw = image.shape[:2]

        pad_t = int(h * self._cfg.face_pad_top)
        pad_b = int(h * self._cfg.face_pad_bottom)
        pad_s = int(w * self._cfg.face_pad_side)

        x1 = max(0, x - pad_s)
        y1 = max(0, y - pad_t)
        x2 = min(iw, x + w + pad_s)
        y2 = min(ih, y + h + pad_b)

        return image[y1:y2, x1:x2].copy(), (x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def normalise(face: np.ndarray) -> np.ndarray:
        """CLAHE brightness normalisation."""
        lab = cv2.cvtColor(face, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        l_ch = clahe.apply(l_ch)
        return cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)

    @staticmethod
    def smooth(face: np.ndarray, d: int = 7, sc: int = 50, ss: int = 50) -> np.ndarray:
        """Light bilateral filter to reduce noise before stylisation."""
        return cv2.bilateralFilter(face, d, sc, ss)

    def preprocess(
        self, image: np.ndarray, bbox: Tuple[int, int, int, int]
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        crop, adj = self.crop_face(image, bbox)
        crop = self.normalise(crop)
        crop = self.smooth(crop)
        return crop, adj


# =========================================================================
#  4. FACE STYLER  (AnimeGANv2)
# =========================================================================

class FaceStyler:
    """Cartoon stylisation using AnimeGANv2.

    Falls back to a simple bilateral + edge-based cartoon effect when
    the pretrained weights are unavailable.
    """

    def __init__(self, config: PipelineConfig, weights_mgr: WeightManager):
        self._cfg = config
        self._model: Optional[AnimeGANv2] = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._weights_mgr = weights_mgr

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            path = self._weights_mgr.ensure_animegan()
            model = AnimeGANv2()
            state = torch.load(str(path), map_location=self._device, weights_only=True)
            model.load_state_dict(state)
            model.to(self._device).eval()
            self._model = model
            log.info("AnimeGANv2 styler loaded")
        except Exception as e:
            log.warning(f"AnimeGANv2 unavailable ({e}). Using fallback cartoon effect.")

    def stylize(self, face_bgr: np.ndarray) -> np.ndarray:
        """Return stylised face (same size as input)."""
        self._ensure_model()
        if self._model is not None:
            return self._stylize_animegan(face_bgr)
        return self._stylize_fallback(face_bgr)

    def _stylize_animegan(self, face_bgr: np.ndarray) -> np.ndarray:
        h, w = face_bgr.shape[:2]

        # Resize to multiple of 8
        sz = self._cfg.animegan_input_size
        nw = (sz // 8) * 8
        nh = (sz // 8) * 8
        inp = cv2.resize(face_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)

        # BGR→RGB, [0,255]→[-1,1], HWC→NCHW
        rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB).astype(np.float32)
        tensor = torch.from_numpy(rgb / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0)
        tensor = tensor.to(self._device)

        with torch.no_grad():
            out = self._model(tensor)

        # NCHW→HWC, [-1,1]→[0,255], RGB→BGR
        out_np = out.squeeze(0).permute(1, 2, 0).cpu().numpy()
        out_np = ((out_np + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
        result = cv2.cvtColor(out_np, cv2.COLOR_RGB2BGR)

        # Boost saturation slightly
        hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] *= self._cfg.stylize_saturation_boost
        hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
        result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        # Resize back
        return cv2.resize(result, (w, h), interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def _stylize_fallback(face_bgr: np.ndarray) -> np.ndarray:
        """Simple cartoon effect: bilateral smoothing + strong edges."""
        smooth = face_bgr.copy()
        for _ in range(4):
            smooth = cv2.bilateralFilter(smooth, 9, 75, 75)
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        edges = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 5
        )
        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        return cv2.bitwise_and(smooth, edges_bgr)


# =========================================================================
#  5. FACE BLENDER  (Poisson / seamlessClone)
# =========================================================================

class FaceBlender:
    """Blend a stylised face into a template using OpenCV seamlessClone."""

    def __init__(self, config: PipelineConfig):
        self._cfg = config

    def blend(
        self,
        template: np.ndarray,
        face: np.ndarray,
        mask: np.ndarray,
        center: Tuple[int, int],
    ) -> np.ndarray:
        """Poisson-blend face into template at given center.

        Args:
            template: BGR target image
            face: BGR stylised face (same size as mask)
            mask: float32 [0..1] segmentation mask
            center: (cx, cy) on the template where the face center should go
        """
        # Feather the mask edges
        fr = self._cfg.feather_radius
        mask_u8 = (mask * 255).clip(0, 255).astype(np.uint8)
        if fr > 0:
            mask_u8 = cv2.GaussianBlur(mask_u8, (0, 0), sigmaX=fr)

        # Ensure mask has content
        if mask_u8.max() < 10:
            log.warning("Mask is nearly empty — skipping blend")
            return template

        # seamlessClone needs the mask and source to be the same size
        cx, cy = center
        result = cv2.seamlessClone(
            face, template, mask_u8, (cx, cy), self._cfg.seamless_clone_flag
        )
        return result


# =========================================================================
#  6. TEMPLATE RENDERER
# =========================================================================

class TemplateRenderer:
    """Detect white placeholder circle, render name text."""

    def __init__(self, config: PipelineConfig):
        self._cfg = config

    def find_face_placeholder(
        self, template_bgr: np.ndarray
    ) -> Optional[Tuple[int, int, int]]:
        """Find the largest white circular region.
        Returns (center_x, center_y, radius) or None.
        """
        thr = self._cfg.white_threshold
        white = (
            (template_bgr[:, :, 0] > thr)
            & (template_bgr[:, :, 1] > thr)
            & (template_bgr[:, :, 2] > thr)
        ).astype(np.uint8) * 255

        contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best, best_area = None, 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 500:
                continue
            peri = cv2.arcLength(cnt, True)
            if peri == 0:
                continue
            circ = 4 * np.pi * area / (peri * peri)
            if circ > 0.55 and area > best_area:
                best, best_area = cnt, area

        if best is None:
            return None

        (cx, cy), r = cv2.minEnclosingCircle(best)
        return int(cx), int(cy), int(r)

    def inpaint_placeholder(
        self, template_bgr: np.ndarray, cx: int, cy: int, radius: int
    ) -> np.ndarray:
        """Fill the white circle with surrounding pixels via Telea inpainting."""
        h, w = template_bgr.shape[:2]
        thr = self._cfg.white_threshold

        ys = np.arange(max(0, cy - radius), min(h, cy + radius))
        xs = np.arange(max(0, cx - radius), min(w, cx + radius))
        yy, xx = np.meshgrid(ys, xs, indexing="ij")
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        region = template_bgr[ys[0] : ys[-1] + 1, xs[0] : xs[-1] + 1]
        inside = dist <= radius
        is_white = (region[:, :, 0] > thr) & (region[:, :, 1] > thr) & (region[:, :, 2] > thr)
        local_mask = (inside & is_white).astype(np.uint8) * 255

        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_mask[ys[0] : ys[-1] + 1, xs[0] : xs[-1] + 1] = local_mask

        if full_mask.sum() == 0:
            return template_bgr

        return cv2.inpaint(template_bgr, full_mask, 12, cv2.INPAINT_TELEA)

    @staticmethod
    def render_name(
        pil_img: Image.Image,
        name: str,
        position: Tuple[int, int],
        font_size: int = 36,
        color: Tuple[int, int, int] = (80, 60, 30),
    ) -> Image.Image:
        """Draw name centred at position with white outline for readability."""
        draw = ImageDraw.Draw(pil_img)
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), name, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = position[0] - tw // 2
        y = position[1] - th // 2
        # Outline
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    draw.text((x + dx, y + dy), name, font=font, fill=(255, 255, 255, 255))
        draw.text((x, y), name, font=font, fill=(*color, 255))
        return pil_img


# =========================================================================
#  MAIN PIPELINE
# =========================================================================

class StoryMePipeline:
    """Orchestrates the full face-personalisation pipeline.

    Designed for extensibility:
        • Swap FaceDetector for InsightFace by implementing the same interface
        • Swap FaceStyler for a Stable-Diffusion-based module
        • Load page coordinates from JSON for multi-page books
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config or PipelineConfig()
        self._wm = WeightManager(self.cfg.weights_dir)
        self.detector = FaceDetector(self.cfg.detection_confidence)
        self.parser = FaceParser(self.cfg, self._wm)
        self.processor = FaceProcessor(self.cfg)
        self.styler = FaceStyler(self.cfg, self._wm)
        self.blender = FaceBlender(self.cfg)
        self.renderer = TemplateRenderer(self.cfg)

    def run(
        self,
        template_path: str,
        face_path: str,
        child_name: str,
        output_path: str = "result.png",
        face_coords: Optional[Tuple[int, int, int, int]] = None,
        name_coords: Optional[Tuple[int, int]] = None,
        name_font_size: int = 36,
    ) -> str:
        """Execute the full pipeline.

        Args:
            template_path: Path to the illustrated template image
            face_path: Path to the user's photo
            child_name: Name to render on the template
            output_path: Where to save the result
            face_coords: Optional (cx, cy, radius, _) override for face circle
            name_coords: Optional (x, y) for name text position
            name_font_size: Font size for the name

        Returns:
            Path to the saved result image.
        """
        log.info("=" * 60)
        log.info("StoryMe Production Pipeline")
        log.info("=" * 60)

        # ---- Load images ----
        log.info("[1/7] Loading images …")
        template_bgr = cv2.imread(template_path)
        photo_bgr = cv2.imread(face_path)
        if template_bgr is None:
            raise FileNotFoundError(f"Cannot read template: {template_path}")
        if photo_bgr is None:
            raise FileNotFoundError(f"Cannot read photo: {face_path}")
        log.info(
            f"  Template {template_bgr.shape[1]}×{template_bgr.shape[0]}, "
            f"Photo {photo_bgr.shape[1]}×{photo_bgr.shape[0]}"
        )

        # ---- Detect face (MediaPipe) ----
        log.info("[2/7] Detecting face (MediaPipe) …")
        detection = self.detector.detect(photo_bgr)
        if detection is None:
            log.warning("  No face detected — using centre crop as fallback")
            ih, iw = photo_bgr.shape[:2]
            d = min(iw, ih)
            cx, cy = iw // 2, ih // 2
            r = d // 2
            detection = {
                "bbox": (cx - r, cy - r, 2 * r, 2 * r),
                "landmarks": [],
                "confidence": 0.0,
            }
        else:
            bx, by, bw, bh = detection["bbox"]
            log.info(
                f"  Face found at ({bx},{by} {bw}×{bh}), "
                f"confidence={detection['confidence']:.2f}"
            )

        # ---- Crop & preprocess ----
        log.info("[3/7] Cropping & preprocessing face …")
        face_crop, adj_bbox = self.processor.preprocess(photo_bgr, detection["bbox"])
        log.info(f"  Cropped to {face_crop.shape[1]}×{face_crop.shape[0]}")

        # ---- Parse face (BiSeNet segmentation) ----
        log.info("[4/7] Parsing face segmentation …")
        # Adjust landmarks to crop coordinate system
        ax, ay = adj_bbox[0], adj_bbox[1]
        local_lm = [(lx - ax, ly - ay) for lx, ly in detection.get("landmarks", [])]
        mask = self.parser.parse(face_crop, local_lm if local_lm else None)
        mask_pct = mask.mean() * 100
        log.info(f"  Mask coverage: {mask_pct:.1f}% of crop area")

        # ---- Stylize (AnimeGANv2) ----
        log.info("[5/7] Stylizing face (AnimeGANv2) …")
        stylized = self.styler.stylize(face_crop)
        log.info(f"  Stylized: {stylized.shape[1]}×{stylized.shape[0]}")

        # ---- Find template placeholder & blend ----
        log.info("[6/7] Blending into template (seamlessClone) …")

        if face_coords:
            tcx, tcy, tr = face_coords[0], face_coords[1], face_coords[2]
        else:
            placeholder = self.renderer.find_face_placeholder(template_bgr)
            if placeholder:
                tcx, tcy, tr = placeholder
                log.info(f"  Placeholder circle: center=({tcx},{tcy}), r={tr}")
            else:
                log.warning("  No placeholder found — placing at image centre")
                th, tw = template_bgr.shape[:2]
                tcx, tcy = tw // 2, th // 2
                tr = min(tw, th) // 6

        # Inpaint the white circle first
        template_bgr = self.renderer.inpaint_placeholder(template_bgr, tcx, tcy, tr)

        # Resize stylized face + mask to fit the circle
        face_diam = int(tr * 2 * 0.92)
        face_for_blend = cv2.resize(stylized, (face_diam, face_diam))
        mask_for_blend = cv2.resize(mask, (face_diam, face_diam))

        # Blend using seamlessClone
        result_bgr = self.blender.blend(
            template_bgr, face_for_blend, mask_for_blend, (tcx, tcy)
        )

        # ---- Render name ----
        log.info("[7/7] Rendering name …")
        result_pil = Image.fromarray(cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB))

        if name_coords is None:
            # Default: below the face circle
            name_coords = (tcx, tcy + tr + 20)

        result_pil = self.renderer.render_name(
            result_pil, child_name, name_coords, name_font_size, self.cfg.text_color
        )

        # ---- Save ----
        result_pil.save(output_path, quality=95)
        size_kb = os.path.getsize(output_path) / 1024
        log.info(f"  Saved: {output_path} ({size_kb:.0f} KB)")
        log.info("=" * 60)
        log.info("Done!")
        log.info("=" * 60)
        return output_path

    def close(self):
        self.detector.close()


# =========================================================================
#  CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="StoryMe — Production Face Personalization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python storyme_pipeline.py template.png face.jpg "Shan"
  python storyme_pipeline.py template.png face.jpg "Shan" -o page1_result.png
  python storyme_pipeline.py template.png face.jpg "Shan" --name-xy 400 900

Library usage:
  from storyme_pipeline import StoryMePipeline, PipelineConfig
  pipe = StoryMePipeline(PipelineConfig())
  pipe.run("template.png", "face.jpg", "Shan", "result.png",
           name_coords=(400, 900), name_font_size=48)
""",
    )
    parser.add_argument("template", help="Path to the template image")
    parser.add_argument("face", help="Path to the user's photo")
    parser.add_argument("name", help="Child's name")
    parser.add_argument("-o", "--output", default="result.png", help="Output path")
    parser.add_argument(
        "--name-xy", nargs=2, type=int, default=None,
        metavar=("X", "Y"), help="Name text position (x y)"
    )
    parser.add_argument("--name-size", type=int, default=36, help="Name font size")
    parser.add_argument(
        "--weights-dir", type=str, default=None,
        help="Directory for model weights (default: ~/.storyme/weights)"
    )
    args = parser.parse_args()

    cfg = PipelineConfig()
    if args.weights_dir:
        cfg.weights_dir = Path(args.weights_dir)

    pipeline = StoryMePipeline(cfg)
    try:
        pipeline.run(
            args.template,
            args.face,
            args.name,
            args.output,
            name_coords=tuple(args.name_xy) if args.name_xy else None,
            name_font_size=args.name_size,
        )
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
