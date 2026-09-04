from collections import deque
from typing import Iterable, Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:
    import cv2
except ImportError:  # Pillow fallback keeps the editor usable without OpenCV.
    cv2 = None

from .model import PHOTO_SIZES, ProcessingSettings
from .matting import model_available, portrait_alpha


MAX_WORK_EDGE = 1200


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError("背景色必须是 3 位或 6 位 HEX")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(1.0, MAX_WORK_EDGE / max(image.size))
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    return image


def _sample_edges(rgb: np.ndarray) -> np.ndarray:
    height, width = rgb.shape[:2]
    step = max(1, min(width, height) // 80)
    upper = max(1, round(height * 0.28))
    samples = np.concatenate((rgb[0, ::step], rgb[::step, 0][:upper // step + 1], rgb[::step, -1][:upper // step + 1]))
    return samples.astype(np.float32)


def _background_colors(rgb: np.ndarray) -> Iterable[np.ndarray]:
    samples = _sample_edges(rgb)
    height, width = rgb.shape[:2]
    patch = max(2, min(width, height) // 30)
    anchors = np.concatenate((
        rgb[:patch, :patch].reshape(-1, 3),
        rgb[:patch, -patch:].reshape(-1, 3),
    )).astype(np.float32)
    anchor = np.median(anchors, axis=0)
    near_anchor = np.linalg.norm(samples - anchor, axis=1) <= 80
    if near_anchor.any():
        samples = samples[near_anchor]
    # Quantization keeps this deterministic and avoids a heavy clustering dependency.
    quantized = np.round(samples / 16) * 16
    colors, counts = np.unique(quantized.astype(np.uint8), axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    selected = []
    for index in order:
        color = colors[index].astype(np.float32)
        if np.linalg.norm(color - anchor) > 80:
            continue
        if not any(np.linalg.norm(color - old) < 24 for old in selected):
            selected.append(color)
        if len(selected) == 4:
            break
    return selected or [samples.mean(axis=0)]


def _connected(candidate: np.ndarray) -> np.ndarray:
    height, width = candidate.shape
    visited = np.zeros_like(candidate, dtype=bool)
    queue = deque()
    for x in range(width):
        for y in (0, height - 1):
            if candidate[y, x] and not visited[y, x]:
                visited[y, x] = True
                queue.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if candidate[y, x] and not visited[y, x]:
                visited[y, x] = True
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and candidate[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((nx, ny))
    return visited


def _mask_from_edges(rgb: np.ndarray, tolerance: int) -> np.ndarray:
    tolerance = max(8, min(110, int(tolerance)))
    candidates = []
    for color in _background_colors(rgb):
        distance = np.linalg.norm(rgb.astype(np.float32) - color, axis=2)
        candidates.append(_connected(distance <= tolerance))
    background = np.logical_or.reduce(candidates)
    return ~background


def _grabcut_refine(rgb: np.ndarray, initial: np.ndarray) -> np.ndarray:
    """Refine a colour-derived seed with texture and contour information."""
    if cv2 is None or initial.mean() < 0.04 or initial.mean() > 0.96:
        return initial
    height, width = initial.shape
    image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)
    background = ~initial
    bg_radius = max(1, min(5, min(width, height) // 180))
    fg_radius = max(2, min(9, min(width, height) // 100))
    sure_background = cv2.erode(background.astype(np.uint8), np.ones((bg_radius * 2 + 1,) * 2, np.uint8)) > 0
    sure_foreground = cv2.erode(initial.astype(np.uint8), np.ones((fg_radius * 2 + 1,) * 2, np.uint8)) > 0
    mask[background] = cv2.GC_PR_BGD
    mask[initial] = cv2.GC_PR_FGD
    mask[sure_background] = cv2.GC_BGD
    mask[sure_foreground] = cv2.GC_FGD
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(image, mask, None, bg_model, fg_model, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return initial
    refined = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    # The edge seed is authoritative for a subject that touches the lower frame.
    refined |= initial & ~background
    return refined


def _morph(mask: np.ndarray, radius: int, dilate: bool) -> np.ndarray:
    if radius <= 0:
        return mask
    image = Image.fromarray((mask * 255).astype(np.uint8))
    size = radius * 2 + 1
    image = image.filter(ImageFilter.MaxFilter(size) if dilate else ImageFilter.MinFilter(size))
    return np.asarray(image) > 127


def _soft_alpha(foreground: np.ndarray, feather: float) -> np.ndarray:
    if feather <= 0:
        return foreground.astype(np.float32)
    radius = max(1, min(8, round(feather * 2)))
    image = Image.fromarray((foreground * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    soft = np.asarray(image, dtype=np.float32) / 255.0
    return np.where(foreground, np.maximum(soft, 0.55), soft * 0.35)


def _edge_alpha(rgb: np.ndarray, foreground: np.ndarray, feather: float) -> np.ndarray:
    """Create a narrow anti-aliased edge and suppress captured background pixels."""
    if cv2 is not None:
        sigma = max(0.35, min(2.4, 0.55 + float(feather) * 0.7))
        alpha = cv2.GaussianBlur(foreground.astype(np.float32), (0, 0), sigma)
    else:
        alpha = _soft_alpha(foreground, feather)
    alpha = np.clip(alpha, 0.0, 1.0)
    if not foreground.any():
        return alpha
    bg = np.median(np.concatenate((rgb[:12, :12].reshape(-1, 3), rgb[:12, -12:].reshape(-1, 3))), axis=0)
    distance = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
    # Pixels just outside the silhouette that still resemble the background are halo.
    confidence = np.clip((distance - 7.0) / max(18.0, float(30 + feather * 12)), 0.0, 1.0)
    boundary = (alpha > 0.01) & (alpha < 0.99)
    alpha[boundary] *= 0.35 + 0.65 * confidence[boundary]
    alpha[foreground & (alpha < 0.55)] = np.maximum(alpha[foreground & (alpha < 0.55)], 0.55)
    return alpha


def build_matte(image: Image.Image, settings: ProcessingSettings) -> Image.Image:
    work = prepare_image(image)
    rgb = np.asarray(work, dtype=np.uint8)
    cleanup = max(0, min(4, int(settings.edge_cleanup)))
    try:
        alpha = portrait_alpha(rgb) if model_available() else None
    except (OSError, RuntimeError, cv2.error if cv2 is not None else RuntimeError):
        alpha = None

    if alpha is not None:
        # A gentle level shift removes captured studio background without cutting
        # the continuous alpha values that preserve flyaway hair.
        threshold = cleanup * 0.018
        alpha = np.clip((alpha - threshold) / max(0.01, 1.0 - threshold), 0.0, 1.0)
        if settings.feather > 0 and cv2 is not None:
            sigma = min(1.2, float(settings.feather) * 0.28)
            if sigma > 0.05:
                alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
        alpha = (alpha * 255).clip(0, 255).astype(np.uint8)
    else:
        foreground = _mask_from_edges(rgb, settings.tolerance)
        foreground = _grabcut_refine(rgb, foreground)
        if cleanup:
            foreground = _morph(foreground, cleanup, False)
        alpha = (_edge_alpha(rgb, foreground, settings.feather) * 255).clip(0, 255).astype(np.uint8)
    rgba = np.dstack((rgb, alpha))
    return Image.fromarray(rgba, "RGBA")


def render_matte_preview(matte: Image.Image, target_size=None) -> Image.Image:
    """Render the transparent person over a neutral checkerboard for inspection."""
    image = matte.copy()
    if target_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    tile = 18
    board = Image.new("RGB", image.size, "#F4F5F7")
    pixels = board.load()
    for y in range(image.height):
        for x in range(image.width):
            if ((x // tile) + (y // tile)) % 2:
                pixels[x, y] = (224, 228, 233)
    board = board.convert("RGBA")
    board.alpha_composite(image)
    return board.convert("RGB")


def composition_crop_box(
    size: Tuple[int, int],
    target: Tuple[int, int],
    zoom: int,
    offset_x: int,
    offset_y: int,
):
    """Return the source-space box used by every composition workflow.

    Zoom values below 100 intentionally extend the canvas. The lower edge is
    anchored to the source so portraits that touch the bottom never acquire a
    visible horizontal cut inside the finished photo.
    """
    width, height = size
    target_w, target_h = target
    aspect = target_w / target_h
    zoom_ratio = max(0.6, min(1.8, float(zoom) / 100.0))

    if width / max(1, height) >= aspect:
        base_crop_h = float(height)
        base_crop_w = base_crop_h * aspect
    else:
        base_crop_w = float(width)
        base_crop_h = base_crop_w / aspect
    crop_w = max(1, int(round(base_crop_w / zoom_ratio)))
    crop_h = max(1, int(round(base_crop_h / zoom_ratio)))

    center_x = width / 2 + (offset_x / 100) * width
    left = int(round(center_x - crop_w / 2))
    if zoom_ratio < 1.0:
        # Keep the garment boundary on the final lower edge. Horizontal
        # movement remains available, while vertical movement can only crop
        # farther into the source and never expose empty space below it.
        top = int(round(height - crop_h + min(0, offset_y) / 100 * height))
    else:
        center_y = height / 2 + (offset_y / 100) * height
        top = int(round(center_y - crop_h / 2))
        left = max(0, min(width - crop_w, left))
        top = max(0, min(height - crop_h, top))
    return left, top, left + crop_w, top + crop_h


# Kept as an internal alias for callers from older project versions.
_crop_box = composition_crop_box


def _crop_with_fill(image: Image.Image, box, fill) -> Image.Image:
    left, top, right, bottom = box
    output = Image.new(image.mode, (right - left, bottom - top), fill)
    source_box = (
        max(0, left),
        max(0, top),
        min(image.width, right),
        min(image.height, bottom),
    )
    if source_box[2] > source_box[0] and source_box[3] > source_box[1]:
        output.paste(image.crop(source_box), (source_box[0] - left, source_box[1] - top))
    return output


def _crop_with_edge_extension(image: Image.Image, box) -> Image.Image:
    """Crop beyond the source by repeating its outermost pixels."""
    left, top, right, bottom = box
    pad_left = max(0, -left)
    pad_top = max(0, -top)
    pad_right = max(0, right - image.width)
    pad_bottom = max(0, bottom - image.height)
    pixels = np.asarray(image)
    extended = np.pad(
        pixels,
        ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
        mode="edge",
    )
    adjusted = (
        left + pad_left,
        top + pad_top,
        right + pad_left,
        bottom + pad_top,
    )
    return Image.fromarray(extended, image.mode).crop(adjusted)


def render_cutout(image: Image.Image, settings: ProcessingSettings, matte: Image.Image = None) -> Image.Image:
    source = prepare_image(image)
    working = matte or build_matte(source, settings)
    working_pixels = np.asarray(working, dtype=np.float32)
    working_alpha = working_pixels[:, :, 3] / 255.0
    transparent_source = working_alpha < 0.03
    if transparent_source.any():
        old_background = np.median(working_pixels[:, :, :3][transparent_source], axis=0)
    else:
        old_background = np.median(
            np.concatenate((
                working_pixels[:12, :12, :3].reshape(-1, 3),
                working_pixels[:12, -12:, :3].reshape(-1, 3),
            )),
            axis=0,
        )
    target = PHOTO_SIZES[settings.size_key]
    crop_box = _crop_box(working.size, (target.width, target.height), settings.zoom, settings.offset_x, settings.offset_y)
    cropped = _crop_with_fill(working, crop_box, (0, 0, 0, 0))
    output = cropped.resize((target.width, target.height), Image.Resampling.LANCZOS)
    pixels = np.asarray(output, dtype=np.float32).copy()
    alpha = pixels[:, :, 3:4] / 255.0
    transparent = alpha[:, :, 0] < 0.03
    if transparent.any():
        if cv2 is not None:
            solid = (alpha[:, :, 0] > 0.02).astype(np.uint8)
            inside_distance = cv2.distanceTransform(solid, cv2.DIST_L2, 3)
            color_distance = np.linalg.norm(pixels[:, :, :3] - old_background, axis=2)
            inner_edge = (inside_distance > 0) & (inside_distance <= 3.5)
            foreground_confidence = np.clip((color_distance - 8.0) / 72.0, 0.0, 1.0)
            alpha[:, :, 0][inner_edge] *= foreground_confidence[inner_edge]
        edge = (alpha[:, :, 0] > 0.02) & (alpha[:, :, 0] < 0.98)
        if edge.any():
            edge_alpha = np.maximum(alpha[edge], 0.15)
            recovered = (pixels[:, :, :3][edge] - old_background * (1.0 - edge_alpha)) / edge_alpha
            pixels[:, :, :3][edge] = np.clip(recovered, 0, 255)
            if cv2 is not None:
                opaque = alpha[:, :, 0] >= 0.98
                distance_input = (~opaque).astype(np.uint8)
                _, labels = cv2.distanceTransformWithLabels(
                    distance_input, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
                )
                palette = np.zeros((int(labels.max()) + 1, 3), dtype=np.float32)
                opaque_y, opaque_x = np.where(opaque)
                palette[labels[opaque_y, opaque_x]] = pixels[opaque_y, opaque_x, :3]
                nearest_foreground = palette[labels]
                edge_alpha_flat = alpha[:, :, 0][edge]
                color_distance = np.linalg.norm(pixels[:, :, :3][edge] - old_background, axis=1)
                color_confidence = np.clip((color_distance - 10.0) / 95.0, 0.0, 1.0)
                spill = np.clip((1.0 - edge_alpha_flat) * 0.7 + (1.0 - color_confidence) * 0.3, 0.0, 0.85)
                pixels[:, :, :3][edge] = (
                    pixels[:, :, :3][edge] * (1.0 - spill[:, None])
                    + nearest_foreground[edge] * spill[:, None]
                )
        pixels[:, :, 3:4] = alpha * 255.0
    if settings.brightness:
        foreground = alpha[:, :, 0] > 0.02
        pixels[:, :, :3][foreground] = np.clip(
            pixels[:, :, :3][foreground] + int(settings.brightness), 0, 255
        )
    result = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGBA")
    if abs(float(settings.rotation)) > 0.05:
        result = result.rotate(
            float(settings.rotation),
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0, 0),
        )
    return result


def render_photo(image: Image.Image, settings: ProcessingSettings, matte: Image.Image = None, original: bool = False) -> Image.Image:
    source = prepare_image(image)
    target = PHOTO_SIZES[settings.size_key]
    if original:
        crop_box = composition_crop_box(
            source.size,
            (target.width, target.height),
            settings.zoom,
            settings.offset_x,
            settings.offset_y,
        )
        cropped = _crop_with_edge_extension(source, crop_box)
        return cropped.resize((target.width, target.height), Image.Resampling.LANCZOS)
    cutout = render_cutout(source, settings, matte)
    background = Image.new("RGBA", cutout.size, hex_to_rgb(settings.background) + (255,))
    background.alpha_composite(cutout)
    return background.convert("RGB")
