from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PhotoSize:
    key: str
    label: str
    width: int
    height: int


PHOTO_SIZES = {
    "one": PhotoSize("one", "一寸  295 x 413", 295, 413),
    "two": PhotoSize("two", "二寸  413 x 579", 413, 579),
    "small_one": PhotoSize("small_one", "小一寸  260 x 378", 260, 378),
    "small_two": PhotoSize("small_two", "小二寸  390 x 567", 390, 567),
}


@dataclass
class ProcessingSettings:
    background: str = "#438EDB"
    size_key: str = "one"
    tolerance: int = 48
    edge_cleanup: int = 1
    feather: float = 0.6
    brightness: int = 0
    zoom: int = 100
    offset_x: int = 0
    offset_y: int = 0
    rotation: float = 0.0
    dpi: int = 300
    max_bytes: int = 0


@dataclass
class DocumentState:
    source: Optional[object] = None
    matte: Optional[object] = None
    result: Optional[object] = None
    path: Optional[Path] = None
    dirty: bool = False
    processing: bool = False
    revision: int = 0
    matte_history: list = field(default_factory=list)
    matte_future: list = field(default_factory=list)
    face_report: Optional[object] = None

    def clear(self) -> None:
        self.source = None
        self.matte = None
        self.result = None
        self.path = None
        self.dirty = False
        self.processing = False
        self.revision += 1
        self.matte_history.clear()
        self.matte_future.clear()
        self.face_report = None
