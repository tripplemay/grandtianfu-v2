"""Generate a synthetic axis-aligned line drawing, not a measured building plan."""

from pathlib import Path

from PIL import Image, ImageDraw


def main():
    image = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(image).rectangle((40, 30, 360, 270), outline="black", width=5)
    image.save(Path(__file__).with_name("synthetic-room.png"), format="PNG")


if __name__ == "__main__":
    main()
