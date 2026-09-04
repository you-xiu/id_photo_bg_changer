import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
import tempfile

from .model import PHOTO_SIZES


APP_DIR_NAME = "PicTone"
MAX_RECENT_FILES = 6


@dataclass
class AppPreferences:
    background: str = "#438EDB"
    size_key: str = "one"
    dpi: int = 300
    max_bytes_kb: int = 0
    last_export_dir: str = ""
    recent_files: list[str] = field(default_factory=list)


def preferences_path(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "settings.json"
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir()
    return Path(root) / APP_DIR_NAME / "settings.json"


def _valid_color(value) -> bool:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def sanitize_preferences(data: dict) -> AppPreferences:
    defaults = AppPreferences()
    background = data.get("background", defaults.background)
    if not _valid_color(background):
        background = defaults.background
    size_key = data.get("size_key", defaults.size_key)
    if size_key not in PHOTO_SIZES:
        size_key = defaults.size_key
    try:
        dpi = max(72, min(600, int(data.get("dpi", defaults.dpi))))
    except (TypeError, ValueError):
        dpi = defaults.dpi
    try:
        max_bytes_kb = max(0, min(10240, int(data.get("max_bytes_kb", defaults.max_bytes_kb))))
    except (TypeError, ValueError):
        max_bytes_kb = defaults.max_bytes_kb
    export_dir = data.get("last_export_dir", "")
    if not isinstance(export_dir, str):
        export_dir = ""
    recent = data.get("recent_files", [])
    if not isinstance(recent, list):
        recent = []
    recent = [item for item in recent if isinstance(item, str)][:MAX_RECENT_FILES]
    return AppPreferences(background.upper(), size_key, dpi, max_bytes_kb, export_dir, recent)


def load_preferences(path: Path | None = None) -> AppPreferences:
    target = path or preferences_path()
    try:
        data = json.loads(Path(target).read_text(encoding="utf-8"))
        return sanitize_preferences(data if isinstance(data, dict) else {})
    except (OSError, ValueError, TypeError):
        return AppPreferences()


def save_preferences(preferences: AppPreferences, path: Path | None = None) -> None:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(asdict(preferences), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def add_recent_file(preferences: AppPreferences, path: Path) -> None:
    normalized = str(Path(path).resolve())
    preferences.recent_files = [
        normalized,
        *(item for item in preferences.recent_files if item.lower() != normalized.lower()),
    ][:MAX_RECENT_FILES]
