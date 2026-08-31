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


def suggest_layout(rgb: np.ndarray, target_aspect: float) -> Optional[dict]:
    faces = detect_faces(rgb)
    if not faces:
        return None
    face = faces[0]
    height, width = rgb.shape[:2]
    x, y, face_width, face_height = face.box
    face_center_x, face_center_y = face.center
    desired_face_width = width * 0.39
    zoom = int(np.clip(desired_face_width / max(1.0, face_width) * 100.0, 80, 160))
    crop_height = min(height, round(height / (zoom / 100.0)))
    crop_width = min(width, round(crop_height * target_aspect))
    if crop_width > width:
        crop_width = width
        crop_height = min(height, round(crop_width / target_aspect))
    desired_center_x = width / 2
    desired_center_y = y + face_height * 0.47 + crop_height * 0.18
    offset_x = int(np.clip((face_center_x - desired_center_x) / max(1, width) * 100, -20, 20))
    offset_y = int(np.clip((face_center_y - desired_center_y) / max(1, height) * 100, -20, 20))
    return {
        "faces": faces,
        "zoom": zoom,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "rotation": float(np.clip(-face.eye_tilt, -12, 12)),
    }
