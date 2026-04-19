#!/usr/bin/env python3
"""Convert PNG/JPEG images to flash format for LED display.

Supports multiple images: reads a list file (image.txt) or single image.

Flash format (one or more images concatenated):
    Per image:
        [MAGIC:8]      'I' (0x49)
        [LENGTH:24]    Image data size in bytes (big-endian)
        [WIDTH:16]     Image width in pixels (big-endian)
        [HEIGHT:16]    Image height in pixels (big-endian)
        [FRAMEDIV:16]  Frames between position updates (big-endian)
        [DATA...]      RGB pixel data: width x height x 3 bytes

    The image module scans for 'I' at the start of each image.
    After the last image, the next byte won't be 'I', so it wraps to start.

List file format (image.txt):
    # comments and blank lines are ignored
    path/to/image1.png
    path/to/image2.jpg,32
    path/to/image3.png

    Optional comma-separated frame_divider per image (default from CLI arg).
"""

import sys
import os

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow library required")
    print("Install with: pip install Pillow")
    sys.exit(1)


def convert_one_image(input_file, frame_divider=16):
    """Convert a single image file to flash binary data.

    Returns:
        bytearray of header + pixel data, or None on error.
    """
    try:
        img = Image.open(input_file).convert('RGB')
        width, height = img.size

        if width < 8 or height < 16:
            print(f"  Error: Image must be at least 8x16 pixels (got {width}x{height})")
            return None

        data_length = width * height * 3
        if data_length > 0xffffff:
            print(f"  Error: Image too large ({data_length} bytes, max 16,777,215)")
            return None

        header = bytearray([
            0x49,  # 'I'
            (data_length >> 16) & 0xff,
            (data_length >> 8) & 0xff,
            data_length & 0xff,
            (width >> 8) & 0xff,
            width & 0xff,
            (height >> 8) & 0xff,
            height & 0xff,
            (frame_divider >> 8) & 0xff,
            frame_divider & 0xff,
        ])

        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                r, g, b = img.getpixel((x, y))
                pixels.extend([r, g, b])

        total = len(header) + len(pixels)
        print(f"  {input_file}: {width}x{height}, {total:,} bytes, framediv={frame_divider}")
        return header + pixels

    except FileNotFoundError:
        print(f"  Error: File not found: {input_file}")
        return None
    except Exception as e:
        print(f"  Error processing {input_file}: {e}")
        return None


def convert_from_list(list_file, output_file, default_frame_divider=16):
    """Read image list file and concatenate all images into one binary."""
    base_dir = os.path.dirname(os.path.abspath(list_file))

    entries = []
    with open(list_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            path = parts[0].strip()
            fdiv = int(parts[1].strip()) if len(parts) > 1 else default_frame_divider
            # Resolve relative paths from list file directory
            if not os.path.isabs(path):
                path = os.path.join(base_dir, path)
            entries.append((path, fdiv))

    if not entries:
        print(f"Error: No images found in {list_file}")
        return False

    print(f"Converting {len(entries)} images from {list_file}:")

    output = bytearray()
    count = 0
    for path, fdiv in entries:
        data = convert_one_image(path, fdiv)
        if data is not None:
            output.extend(data)
            count += 1

    if count == 0:
        print("Error: No images converted successfully")
        return False

    with open(output_file, 'wb') as f:
        f.write(output)

    print(f"\nWrote {len(output):,} bytes to {output_file} ({count} images)")
    return True


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python3 host/image_convert.py <input> <output.bin> [frame_divider]")
        print()
        print("  input          Image file (PNG/JPEG) or list file (.txt)")
        print("  output.bin     Output binary file for flash")
        print("  frame_divider  Default frames between moves (default: 16)")
        print()
        print("List file format (image.txt):")
        print("  # comment")
        print("  path/to/image1.png")
        print("  path/to/image2.jpg,32    # optional per-image frame_divider")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_divider = int(sys.argv[3]) if len(sys.argv) > 3 else 16

    if frame_divider < 1 or frame_divider > 65535:
        print(f"Error: frame_divider must be 1-65535 (got {frame_divider})")
        sys.exit(1)

    # If input is a .txt file, treat as list; otherwise single image
    if input_file.endswith('.txt'):
        success = convert_from_list(input_file, output_file, frame_divider)
    else:
        data = convert_one_image(input_file, frame_divider)
        if data:
            with open(output_file, 'wb') as f:
                f.write(data)
            success = True
        else:
            success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
