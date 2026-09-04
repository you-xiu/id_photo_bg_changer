from io import BytesIO
from dataclasses import dataclass
import csv
import os
from pathlib import Path
from typing import Iterable
import uuid

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class ExportValidation:
    path: Path
    size: tuple[int, int]
    dpi: tuple[int, int]
    mode: str
    file_bytes: int
    valid: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class BatchExportRecord:
    source: str
    output: str
    status: str
    quality_score: int | None = None
    detail: str = ""


def _jpeg_bytes(image: Image.Image, quality: int, dpi: int) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, subsampling=0, dpi=(dpi, dpi), optimize=True)
    return buffer.getvalue()


def encode_image(image: Image.Image, suffix: str = ".png", dpi: int = 300, max_bytes: int = 0) -> bytes:
    suffix = suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        if not max_bytes:
            return _jpeg_bytes(image, 95, dpi)
        for quality in range(95, 19, -3):
            data = _jpeg_bytes(image, quality, dpi)
            if len(data) <= max_bytes:
                return data
        data = _jpeg_bytes(image, 18, dpi)
        if len(data) <= max_bytes:
            return data
        raise ValueError(f"当前尺寸无法压缩到 {max_bytes // 1024} KB，请提高体积上限或改用 PNG")
    buffer = BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi))
    return buffer.getvalue()


def save_image(image: Image.Image, path: Path, dpi: int = 300, max_bytes: int = 0) -> int:
    path = Path(path)
    data = encode_image(image, path.suffix, dpi, max_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(data)


def collision_safe_path(path: Path) -> Path:
    """Return an unused sibling path without changing an existing export."""
    path = Path(path)
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为 {path.name} 生成可用文件名")


def validate_export(
    path: Path,
    expected_size: tuple[int, int] | None = None,
    expected_dpi: int | None = None,
    max_bytes: int = 0,
    require_alpha: bool = False,
) -> ExportValidation:
    path = Path(path)
    issues = []
    try:
        file_bytes = path.stat().st_size
        with Image.open(path) as image:
            image.load()
            size = image.size
            mode = image.mode
            raw_dpi = image.info.get("dpi", (0, 0))
            if isinstance(raw_dpi, (int, float)):
                raw_dpi = (raw_dpi, raw_dpi)
            dpi = tuple(round(float(value)) for value in raw_dpi[:2]) if raw_dpi else (0, 0)
    except Exception as exc:
        return ExportValidation(path, (0, 0), (0, 0), "", 0, False, (f"文件无法重新读取：{exc}",))

    if expected_size and size != tuple(expected_size):
        issues.append(f"尺寸应为 {expected_size[0]} x {expected_size[1]}，实际为 {size[0]} x {size[1]}")
    if expected_dpi and (not dpi[0] or abs(dpi[0] - expected_dpi) > 2):
        issues.append(f"DPI 应为 {expected_dpi}，实际为 {dpi[0] or '未写入'}")
    if max_bytes and file_bytes > max_bytes:
        issues.append(f"文件体积 {file_bytes // 1024} KB 超过限制 {max_bytes // 1024} KB")
    if require_alpha and "A" not in mode:
        issues.append("透明人物文件缺少 Alpha 通道")
    return ExportValidation(path, size, dpi, mode, file_bytes, not issues, tuple(issues))


def write_batch_report(records: Iterable[BatchExportRecord], path: Path) -> Path:
    path = collision_safe_path(Path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("源文件", "输出文件", "处理状态", "质量评分", "说明"))
            for record in records:
                writer.writerow((record.source, record.output, record.status, record.quality_score or "", record.detail))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def make_print_sheet(images: Iterable[Image.Image], paper: str = "6x4", dpi: int = 300, columns: int = 5) -> Image.Image:
    """Create a 6x4 inch print sheet with 25x35 mm one-inch photo slots."""
    paper_sizes = {"6x4": (6, 4), "A4": (8.27, 11.69)}
    paper_width, paper_height = paper_sizes.get(paper, paper_sizes["6x4"])
    canvas_size = (round(paper_width * dpi), round(paper_height * dpi))
    sheet = Image.new("RGB", canvas_size, "white")
    source = next(iter(images), None)
    if source is None:
        return sheet
    photo = source.convert("RGB")
    slot_w, slot_h = photo.size
    margin = max(12, round(dpi * 0.12))
    gap = max(8, round(dpi * 0.04))
    columns = max(1, min(columns, (canvas_size[0] - margin * 2 + gap) // (slot_w + gap)))
    rows = max(1, (canvas_size[1] - margin * 2 + gap) // (slot_h + gap))
    count = columns * rows
    total_w = columns * slot_w + (columns - 1) * gap
    total_h = rows * slot_h + (rows - 1) * gap
    start_x = max(margin, (canvas_size[0] - total_w) // 2)
    start_y = max(margin, (canvas_size[1] - total_h) // 2)
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate([photo] * count):
        row, column = divmod(index, columns)
        x = start_x + column * (slot_w + gap)
        y = start_y + row * (slot_h + gap)
        sheet.paste(item, (x, y))
        draw.rectangle((x, y, x + slot_w - 1, y + slot_h - 1), outline="#D0D0D0", width=1)
    sheet.info["dpi"] = (dpi, dpi)
    return sheet
