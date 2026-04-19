#!/usr/bin/env python3
"""Convert PNG/JPEG image to flash format for LED display.

This tool converts images to the flash format used by the image display module.
The output binary can be flashed to address 0x040000 on the tinyFPGA BX.

Flash format:
    [MAGIC:8]      'I' (0x49)
    [LENGTH:24]    Image data size in bytes (big-endian)
    [WIDTH:16]     Image width in pixels (big-endian)
    [HEIGHT:16]    Image height in pixels (big-endian)
    [FRAMEDIV:16]  Frames between position updates (big-endian)
    [DATA...]      RGB pixel data: width x height x 3 bytes
"""

import sys
import os

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow library required")
    print("Install with: pip install Pillow")
    sys.exit(1)


def create_flash_image(input_file, output_file, frame_divider=16):
    """Convert image file to flash format.
    
    Args:
        input_file: Path to input image (PNG, JPEG, etc.)
        output_file: Path to output binary file
        frame_divider: Frames between position updates (default 16)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load and convert image to RGB
        img = Image.open(input_file).convert('RGB')
        width, height = img.size
        
        # Validate dimensions
        if width < 8 or height < 16:
            print(f"Error: Image must be at least 8x16 pixels (got {width}x{height})")
            return False
        
        # Calculate data size
        data_length = width * height * 3
        
        # Check if fits in 24-bit length field
        if data_length > 0xffffff:
            print(f"Error: Image too large ({data_length} bytes, max 16,777,215)")
            return False
        
        # Create header
        magic = 0x49  # 'I'
        
        header = bytearray([
            magic,
            (data_length >> 16) & 0xff,  # Length MSB
            (data_length >> 8) & 0xff,   # Length mid
            data_length & 0xff,          # Length LSB
            (width >> 8) & 0xff,         # Width MSB
            width & 0xff,                # Width LSB
            (height >> 8) & 0xff,        # Height MSB
            height & 0xff,               # Height LSB
            (frame_divider >> 8) & 0xff, # Frame divider MSB
            frame_divider & 0xff,        # Frame divider LSB
        ])
        
        # Extract pixel data (row by row, left to right)
        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                r, g, b = img.getpixel((x, y))
                pixels.extend([r, g, b])
        
        # Write output
        with open(output_file, 'wb') as f:
            f.write(header)
            f.write(pixels)
        
        total_size = len(header) + len(pixels)
        print(f"  Created {output_file}")
        print(f"  Image: {width}x{height} pixels")
        print(f"  Size: {total_size:,} bytes ({total_size/1024:.1f} KB)")
        print(f"  Frame divider: {frame_divider} (updates every {frame_divider/238:.3f}s @ 238fps)")
        
        # Calculate skating area
        skate_width = width - 8
        skate_height = height - 16
        if skate_width > 0 and skate_height > 0:
            print(f"  Skating area: {skate_width}x{skate_height} pixels")
        else:
            print(f"  Warning: Image is same size as display (no skating motion)")
        
        return True
        
    except FileNotFoundError:
        print(f"Error: File not found: {input_file}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python3 host/image_convert.py input.png output.bin [frame_divider]")
        print()
        print("Arguments:")
        print("  input.png        Input image file (PNG, JPEG, etc.)")
        print("  output.bin       Output binary file for flash")
        print("  frame_divider    Frames between moves (default: 16)")
        print()
        print("Examples:")
        print("  python3 host/image_convert.py image.png image.bin")
        print("  python3 host/image_convert.py photo.jpg image.bin 30")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    frame_divider = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    
    if frame_divider < 1 or frame_divider > 65535:
        print(f"Error: frame_divider must be 1-65535 (got {frame_divider})")
        sys.exit(1)
    
    success = create_flash_image(input_file, output_file, frame_divider)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
