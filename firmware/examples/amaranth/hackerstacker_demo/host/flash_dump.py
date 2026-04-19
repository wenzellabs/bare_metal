#!/usr/bin/env python3
"""Dump flash regions via the bare_metal USB-SPI bridge (while in bootloader mode)."""

import sys, struct, serial, serial.tools.list_ports

def find_port():
    for p in serial.tools.list_ports.comports():
        if "1d50:6130" in (f"{p.vid:04x}:{p.pid:04x}" if p.vid else ""):
            return p.device
        if "1209:2100" in (f"{p.vid:04x}:{p.pid:04x}" if p.vid else ""):
            return p.device
    return None

def spi_cmd(ser, opcode, addr=None, write_bytes=b'', read_len=0):
    """Send a raw SPI command through the USB-SPI bridge."""
    w = bytearray([opcode])
    if addr is not None:
        w += struct.pack('>I', addr)[1:]  # 24-bit big-endian address
    w += write_bytes
    frame = b'\x01' + struct.pack('<HH', len(w), read_len) + w
    ser.write(frame)
    ser.flush()
    return ser.read(read_len) if read_len else b''

def fast_read(ser, addr, length):
    """Fast Read (0x0B) with dummy byte — read up to 'length' bytes."""
    # 0x0B + 3-byte addr + 1 dummy byte, then read 'length' bytes
    w = bytearray([0x0B])
    w += struct.pack('>I', addr)[1:]
    w += b'\x00'  # dummy byte
    frame = b'\x01' + struct.pack('<HH', len(w), length) + w
    ser.write(frame)
    ser.flush()
    return ser.read(length)

def hexdump(data, base_addr=0, width=16):
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {base_addr+i:06x}: {hex_part:<{width*3}}  {ascii_part}")

def main():
    port = find_port()
    if not port:
        print("No bootloader found. Press reset to enter bootloader mode.")
        sys.exit(1)

    print(f"Using {port}")
    ser = serial.Serial(port, timeout=2)

    # Wake flash
    spi_cmd(ser, 0xAB)
    # Read ID
    fid = spi_cmd(ser, 0x9F, read_len=3)
    print(f"Flash ID: {fid.hex()}")

    # Regions to check (from the flash map)
    regions = [
        ("Bootmeta (0x01F000)",   0x01F000, 256),
        ("Slot 1 header (0x020000)", 0x020000, 64),
        ("Font data (0x080000)",  0x080000, 64),
        ("Game data (0x090000)",  0x090000, 64),
        ("Nick data (0x0A0000)",  0x0A0000, 64),
        ("Image data (0x0B0000)", 0x0B0000, 64),
    ]

    # Also check the OLD addresses (lp8k layout)
    old_regions = [
        ("OLD font (0x050000)",   0x050000, 64),
        ("OLD image (0x060000)",  0x060000, 64),
        ("OLD nick (0x0FEC00)",   0x0FEC00, 64),
    ]

    for name, addr, length in regions + old_regions:
        data = fast_read(ser, addr, length)
        is_empty = all(b == 0xFF for b in data)
        is_zero  = all(b == 0x00 for b in data)
        tag = " [EMPTY/0xFF]" if is_empty else (" [ALL ZEROS]" if is_zero else "")
        print(f"\n{name}{tag}:")
        hexdump(data, addr)

    ser.close()

if __name__ == "__main__":
    main()
