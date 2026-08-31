from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw


def _jpeg_bytes(image: Image.Image, quality: int, dpi: int) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, subsampling=0, dpi=(dpi, dpi), optimize=True)
    return buffer.getvalue()


def encode_image(image: Image.Image, suffix: str = ".png", dpi: int = 300, max_bytes: int = 0) -> bytes:
    suffix = suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        if not max_bytes:
            return _jpeg_bytes(image, 95, dpi)
        for quality in range(95, 29, -5):
            data = _jpeg_bytes(image, quality, dpi)
            if len(data) <= max_bytes:
                return data
        return _jpeg_bytes(image, 25, dpi)
    buffer = BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi))
    return buffer.getvalue()


def save_image(image: Image.Image, path: Path, dpi: int = 300, max_bytes: int = 0) -> int:
    data = encode_image(image, path.suffix, dpi, max_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


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
