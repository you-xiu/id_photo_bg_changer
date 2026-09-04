import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


MODEL_NAME = "face_detection_yunet_2023mar.onnx"
_detector = None
_detector_lock = threading.Lock()


@dataclass(frozen=True)
class FaceDetection:
    box: tuple
    landmarks: tuple
    score: float

    @property
    def center(self):
        x, y, width, height = self.box
        return x + width / 2, y + height / 2

    @property
    def eye_tilt(self) -> float:
        left = self.landmarks[0]
        right = self.landmarks[1]
        return float(np.degrees(np.arctan2(right[1] - left[1], right[0] - left[0])))


def _model_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return root / "pictone" / "models" / MODEL_NAME
    return Path(__file__).resolve().parent / "models" / MODEL_NAME


def model_available() -> bool:
    return cv2 is not None and _model_path().is_file() and hasattr(cv2, "FaceDetectorYN_create")


def _load_detector(width: int, height: int):
    global _detector
    if not model_available():
        raise FileNotFoundError("YuNet face detector is unavailable")
    with _detector_lock:
        if _detector is None:
            _detector = cv2.FaceDetectorYN.create(str(_model_path()), "", (width, height), 0.65, 0.3, 5000)
        else:
            _detector.setInputSize((width, height))
        return _detector


def detect_faces(rgb: np.ndarray) -> list[FaceDetection]:
    if not model_available():
        return []
    height, width = rgb.shape[:2]
    try:
        detector = _load_detector(width, height)
    except (OSError, RuntimeError):
        return []
    _, faces = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if faces is None:
        return []
    found = []
    for row in faces:
        values = row.astype(float).tolist()
        box = tuple(values[:4])
        landmarks = tuple((values[index], values[index + 1]) for index in range(4, 14, 2))
        found.append(FaceDetection(box, landmarks, values[14]))
    return sorted(found, key=lambda item: item.score, reverse=True)


def suggest_layout(rgb: np.ndarray, target_aspect: float, matte=None) -> Optional[dict]:
    faces = detect_faces(rgb)
    if not faces:
        return None
    face = faces[0]
    height, width = rgb.shape[:2]
    x, y, face_width, face_height = face.box
    face_center_x, face_center_y = face.center

    # Compute against the actual aspect-ratio crop, not the full source width.
    # The previous full-width calculation enlarged already well-framed portraits
    # and cut away the lower shoulders.
    if width / max(1, height) >= target_aspect:
        base_crop_height = float(height)
        base_crop_width = base_crop_height * target_aspect
    else:
        base_crop_width = float(width)
        base_crop_height = base_crop_width / target_aspect

    # A 35% face width keeps the portrait readable while retaining both
    # shoulders on typical phone photos. Allow a modest canvas extension when
    # the source is already framed too tightly.
    desired_face_ratio = 0.35
    zoom = int(round(desired_face_ratio * base_crop_width / max(1.0, face_width) * 100.0))
    zoom = int(np.clip(zoom, 90, 145))
    zoom_ratio = zoom / 100.0
    crop_width = base_crop_width / zoom_ratio
    crop_height = base_crop_height / zoom_ratio

    desired_left = face_center_x - crop_width / 2
    if zoom < 100:
        left = desired_left
    else:
        left = float(np.clip(desired_left, 0, max(0.0, width - crop_width)))

    # YuNet's face box starts below the hairline. Prefer the segmentation mask
    # for the real crown position, falling back to a conservative face estimate.
    estimated_crown_y = max(0.0, y - face_height * 0.28)
    if matte is not None:
        try:
            alpha = np.asarray(matte.getchannel("A"), dtype=np.uint8)
            foreground = alpha > 96
            rows = np.flatnonzero(foreground.any(axis=1))
            if rows.size:
                mask_crown_y = float(rows[0])
                plausible_limit = y + face_height * 0.12
                if mask_crown_y <= plausible_limit:
                    estimated_crown_y = mask_crown_y
        except (AttributeError, TypeError, ValueError):
            pass
    desired_top = estimated_crown_y - crop_height * 0.08
    if zoom < 100:
        # Expanded portraits are bottom-anchored by the renderer to prevent an
        # internal garment cutoff. The added area naturally becomes headroom.
        top = float(height - crop_height)
    else:
        top = float(np.clip(desired_top, 0, max(0.0, height - crop_height)))

    crop_center_x = left + crop_width / 2
    crop_center_y = top + crop_height / 2
    offset_x = int(round(np.clip((crop_center_x - width / 2) / max(1, width) * 100, -20, 20)))
    offset_y = 0 if zoom < 100 else int(round(np.clip((crop_center_y - height / 2) / max(1, height) * 100, -20, 20)))
    rotation = 0.0 if abs(face.eye_tilt) < 3.0 else float(np.clip(face.eye_tilt * 1.4, -5, 5))
    return {
        "faces": faces,
        "zoom": zoom,
        "offset_x": offset_x,
        "offset_y": offset_y,
        # PIL rotates counter-clockwise in image coordinates; using the detected
        # signed tilt levels the eye line. Negating it made the tilt worse.
        "rotation": rotation,
        "face_ratio": face_width / max(1.0, crop_width),
        "headroom": (estimated_crown_y - top) / max(1.0, crop_height),
    }
