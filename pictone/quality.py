from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter, ImageStat

try:
    import cv2
except ImportError:
    cv2 = None

from .face import detect_faces


@dataclass(frozen=True)
class QualityItem:
    name: str
    value: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class QualityReport:
    items: tuple
    score: int

    @property
    def passed(self):
        return all(item.passed for item in self.items)

    def summary(self) -> str:
        failed = [item.name for item in self.items if not item.passed]
        return "检查通过" if not failed else "需注意：" + "、".join(failed)


def _blur_score(image: Image.Image) -> float:
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    if cv2 is not None:
        return float(cv2.Laplacian(gray, cv2.CV_32F).var())
    return float(ImageStat.Stat(image.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0])


def inspect_photo(source: Image.Image, matte: Image.Image = None, target_size=None) -> QualityReport:
    image = source.convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    try:
        faces = detect_faces(rgb)
    except Exception:
        faces = []
    items = []
    items.append(QualityItem("人脸数量", str(len(faces)), len(faces) == 1, "建议使用单人正面照片"))
    if faces:
        face = faces[0]
        x, y, face_width, face_height = face.box
        ratio = face_width / width
        centered = abs(face.center[0] - width / 2) / width < 0.12
        size_ok = 0.26 <= ratio <= 0.42
        tilt_ok = abs(face.eye_tilt) <= 5
        items.append(QualityItem("人脸位置", "居中" if centered else "偏移", centered, "可用水平位置微调"))
        items.append(QualityItem("人脸比例", f"{ratio:.0%}", size_ok, "建议人脸宽度约占成片 26% 至 42%"))
        items.append(QualityItem("眼线水平", f"{face.eye_tilt:+.1f}°", tilt_ok, "可使用自动构图或旋转修正"))
        headroom = y / height
        items.append(QualityItem("头顶留白", f"{headroom:.0%}", headroom >= 0.03, "头顶不宜贴近上边缘"))
    blur_score = _blur_score(image)
    items.append(QualityItem("清晰度", f"{blur_score:.0f}", blur_score >= 30, "原图过度模糊会影响抠图和打印"))
    brightness = float(rgb.mean())
    items.append(QualityItem("曝光", f"{brightness:.0f}/255", 35 <= brightness <= 225, "避免整体过暗或过曝"))
    if matte is not None:
        alpha = np.asarray(matte.getchannel("A"), dtype=np.uint8)
        edge_ratio = float(((alpha > 0) & (alpha < 255)).mean())
        items.append(QualityItem("抠图边缘", f"过渡区域 {edge_ratio:.1%}", edge_ratio < 0.75, "透明预览中检查发丝、耳廓和肩线"))
    if target_size:
        items.append(QualityItem("输出尺寸", f"{target_size[0]} x {target_size[1]}", True, ""))
    score = round(100 * sum(item.passed for item in items) / max(1, len(items)))
    return QualityReport(tuple(items), score)
