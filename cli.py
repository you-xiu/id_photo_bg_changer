import argparse
from pathlib import Path

from PIL import Image

from pictone.engine import build_matte, render_photo
from pictone.model import PHOTO_SIZES, ProcessingSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="证件照换底色命令行工具")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--color", default="#438EDB")
    parser.add_argument("--size", choices=PHOTO_SIZES, default="one")
    parser.add_argument("--tolerance", type=int, default=48)
    parser.add_argument("--feather", type=float, default=0.6)
    args = parser.parse_args()

    settings = ProcessingSettings(
        background=args.color,
        size_key=args.size,
        tolerance=args.tolerance,
        feather=args.feather,
    )
    with Image.open(args.input) as source:
        source = source.convert("RGB")
        matte = build_matte(source, settings)
        render_photo(source, settings, matte=matte).save(args.output)


if __name__ == "__main__":
    main()
