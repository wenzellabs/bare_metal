#!/usr/bin/env python3
"""Convert nickname text file to flash binary format.

Input format (nick.txt):
    Each line: NICKNAME,RED,GREEN,BLUE
    Example:
        Alice,255,0,0
        Bob,0,255,0
        Charlie,0,0,255

Output binary format:
    [MAGIC:8]         'N' (0x4E)
    [LENGTH:24]       Total data size in bytes (big-endian)
    [COUNT:16]        Number of nicknames (big-endian)
    [DATA...]         For each nickname:
                        [NAME_LEN:8]  Length of name (1-32)
                        [NAME:...]    ASCII characters
                        [COLOR_R:8]   Red (0-255)
                        [COLOR_G:8]   Green (0-255)
                        [COLOR_B:8]   Blue (0-255)
"""

import sys
import struct


def convert_nicknames(input_file, output_file):
    """Convert nickname text file to binary format."""
    
    # Read and parse input file
    nicknames = []
    with open(input_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split(',')
            if len(parts) != 4:
                print(f"Warning: Line {line_num} invalid format (expected NAME,R,G,B): {line}")
                continue
            
            name = parts[0].strip()
            try:
                r = int(parts[1].strip())
                g = int(parts[2].strip())
                b = int(parts[3].strip())
            except ValueError:
                print(f"Warning: Line {line_num} invalid color values: {line}")
                continue
            
            # Validate
            if not name:
                print(f"Warning: Line {line_num} empty name")
                continue
            if len(name) > 32:
                print(f"Warning: Line {line_num} name too long (max 32), truncating: {name}")
                name = name[:32]
            if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
                print(f"Warning: Line {line_num} color out of range (0-255): {line}")
                continue
            
            nicknames.append((name, r, g, b))
    
    if not nicknames:
        print("Error: No valid nicknames found in input file")
        return False
    
    print(f"Found {len(nicknames)} nicknames:")
    for name, r, g, b in nicknames:
        print(f"  {name:20s} RGB({r:3d},{g:3d},{b:3d})")
    
    # Build binary output
    data = bytearray()
    
    # Magic byte
    data.append(ord('N'))
    
    # Calculate total data size (after count field)
    data_size = 0
    for name, r, g, b in nicknames:
        data_size += 1 + len(name) + 3  # len + name + RGB
    
    # Length (24-bit big-endian)
    data.extend(struct.pack('>I', data_size)[1:])  # Skip first byte to get 24-bit
    
    # Count (16-bit big-endian)
    data.extend(struct.pack('>H', len(nicknames)))
    
    # Nickname data
    for name, r, g, b in nicknames:
        # Reverse name: LED chain runs right-to-left, so store
        # characters in reverse order for left-to-right display
        reversed_name = name[::-1]
        
        # Length of name
        data.append(len(reversed_name))
        
        # Name bytes (ASCII, reversed)
        data.extend(reversed_name.encode('ascii'))
        
        # Color (RGB)
        data.append(r)
        data.append(g)
        data.append(b)
    
    # Write output file
    with open(output_file, 'wb') as f:
        f.write(data)
    
    print(f"\nWrote {len(data)} bytes to {output_file}")
    print(f"Header: magic={chr(data[0])}, length={data_size}, count={len(nicknames)}")
    return True


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 nick_convert.py input.txt output.bin")
        print()
        print("Input format (one per line):")
        print("  NAME,RED,GREEN,BLUE")
        print("  Alice,255,0,0")
        print("  Bob,0,255,0")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    if convert_nicknames(input_file, output_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
