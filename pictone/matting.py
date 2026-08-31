import sys
import threading
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


MODEL_NAME = "modnet_photographic.onnx"
MODEL_SHA256 = "5069a5e306b9f5e9f4f2b0360264c9f8ea13b257c7c39943c7cf6a2ec3a102ae"
_network = None
_network_lock = threading.Lock()


def _model_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return root / "pictone" / "models" / MODEL_NAME
    return Path(__file__).resolve().parent / "models" / MODEL_NAME


def model_available() -> bool:
    return cv2 is not None and _model_path().is_file()


def _load_network():
    global _network
    if _network is None:
        if not model_available():
            raise FileNotFoundError("MODNet portrait matting model is unavailable")
        _network = cv2.dnn.readNetFromONNX(str(_model_path()))
        _network.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        _network.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return _network


def portrait_alpha(rgb: np.ndarray, input_size: int = 512) -> np.ndarray:
    """Return a continuous MODNet portrait alpha matte in the source resolution."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for AI portrait matting")

    height, width = rgb.shape[:2]
    if max(height, width) < input_size or min(height, width) > input_size:
        if width >= height:
            resized_height = input_size
            resized_width = round(width / height * input_size)
        else:
            resized_width = input_size
            resized_height = round(height / width * input_size)
    else:
        resized_width, resized_height = width, height

    resized_width = max(32, resized_width - resized_width % 32)
    resized_height = max(32, resized_height - resized_height % 32)
    resized = cv2.resize(rgb, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    tensor = resized.astype(np.float32) / 127.5 - 1.0
    tensor = np.transpose(tensor, (2, 0, 1))[None]

    with _network_lock:
        network = _load_network()
        network.setInput(tensor)
        matte = network.forward()[0, 0]

    matte = cv2.resize(matte, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.clip(matte, 0.0, 1.0).astype(np.float32)
