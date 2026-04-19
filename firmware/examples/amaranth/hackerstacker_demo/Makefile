# Minimal Makefile for Amaranth -> Yosys -> nextpnr-ice40 -> icepack f# Synthesis: produce JSON for nextpnr
$(JSON): $(VGEN_BLINK) $(VGEN_SK9822) $(VGEN_RAINBOW) $(VGEN_CLOCK) $(VGEN_BUTTON) $(VGEN_MAINMENU) $(VGEN_FLASH) $(VGEN_IMAGE) $(WRAP) $(PCF)
	$(YOSYS) -q -p "synth_ice40 -top top -json $(JSON)" $(VGEN_BLINK) $(VGEN_SK9822) $(VGEN_RAINBOW) $(VGEN_CLOCK) $(VGEN_BUTTON) $(VGEN_MAINMENU) $(VGEN_FLASH) $(VGEN_IMAGE) $(WRAP)
# Target: iCE40UP5k-SG48 (bare_metal)

# toolchain
PY ?= python3
YOSYS ?= yosys
NEXTPNR ?= nextpnr-ice40
ICEPACK ?= icepack
TINYPROG ?= tinyprog
SEED ?= 1

# FPGA settings
DEVICE   = up5k
PKG      = sg48

# flash memory map

# 0x000_0000 - 0x000_009f =160b, multiboot header, slot table
# 0x000_00a0 - 0x001_efff ~124kB, slot 0, bare_metal_bootloader
# 0x001_f000 - 0x001_ffff =4kB, bootmetadata
# 0x002_0000 - 0x003_ffff =128kB, slot 1, user bitstream, hackerstacker_demo by default
# 0x004_0000 - 0x005_ffff =128kB, slot 2, transputers anyone?
# 0x006_0000 - 0x007_ffff ~128kB, slot 3, hooray for transputers
# 0x008_0000 - 0x100_0000 user data, images, fonts, text, sounds, etc

# here, in hackerstacker_demo, we reserve the first 512 KB for bootloader and bitstreams,
# and use the rest for user data:
# 0x008_0000 - 0x008_ffff = 64 kB, font data
# 0x009_0000 - 0x009_ffff = 64 kB, game data
# 0x00a_0000 - 0x00a_ffff = 64 kB, nick names
# 0x00b_0000 - 0x0ff_ffff = ~15.3MB images, video


# Image conversion settings
IMAGE_FRAME_DIVIDER ?= 32
IMAGE_CONVERTER = host/image_convert.py

# Font conversion settings
FONT_CONVERTER = host/font_convert.py

TOP = top
SK9822 = sk9822_controller
RAINBOW = rainbow_module
PATTERN = pattern_module
BUTTON = button_handler
MAINMENU = mainmenu
FLASH = flash_controller
IMAGE = image_module
NICK = nick_module
STACKER = stacker_module
FONT_RENDER = font_render
BUILD = build
VGEN_SK9822 = $(BUILD)/$(SK9822).v
VGEN_RAINBOW = $(BUILD)/$(RAINBOW).v
VGEN_PATTERN = $(BUILD)/$(PATTERN).v
VGEN_BUTTON = $(BUILD)/$(BUTTON).v
VGEN_MAINMENU = $(BUILD)/$(MAINMENU).v
VGEN_FLASH = $(BUILD)/$(FLASH).v
VGEN_IMAGE = $(BUILD)/$(IMAGE).v
VGEN_NICK = $(BUILD)/$(NICK).v
VGEN_STACKER = $(BUILD)/$(STACKER).v
VGEN_FONT_RENDER = $(BUILD)/$(FONT_RENDER).v
WRAP = vsrc/board_top.v
JSON = $(BUILD)/$(TOP).json
ASC = $(BUILD)/$(TOP).asc
BIN = $(BUILD)/$(TOP).bin
IMAGE_BIN = $(BUILD)/image.bin
FONT_BIN = $(BUILD)/font.bin
COMBINED_BIN = $(BUILD)/combined.bin
PCF = constraints/top.pcf

# Detect which image source exists (for dependency tracking)
# Prefer image.txt (multi-image list), fallback to single image file
IMAGE_SOURCE = $(firstword $(wildcard image.txt image.png image.jpg image.jpeg))

.PHONY: all clean flash prog boot run report timing stats
all: $(BIN)

$(BUILD):
	mkdir -p $(BUILD)

# Generate Verilog from the Amaranth Python scripts
$(VGEN_SK9822): src/sk9822.py | $(BUILD)
	$(PY) $< $(VGEN_SK9822)

$(VGEN_RAINBOW): src/rainbow.py | $(BUILD)
	$(PY) $< $(VGEN_RAINBOW)

$(VGEN_PATTERN): src/pattern.py | $(BUILD)
	$(PY) $< $(VGEN_PATTERN)

$(VGEN_BUTTON): src/button.py | $(BUILD)
	$(PY) $< $(VGEN_BUTTON)

$(VGEN_MAINMENU): src/mainmenu.py | $(BUILD)
	$(PY) $< $(VGEN_MAINMENU)

$(VGEN_FLASH): src/flash_controller.py | $(BUILD)
	$(PY) $< $(VGEN_FLASH)

$(VGEN_IMAGE): src/image.py | $(BUILD)
	$(PY) $< $(VGEN_IMAGE)

$(VGEN_NICK): src/nick.py | $(BUILD)
	$(PY) $< $(VGEN_NICK)

$(VGEN_STACKER): src/stacker.py | $(BUILD)
	$(PY) $< $(VGEN_STACKER)

$(VGEN_FONT_RENDER): src/font_render.py | $(BUILD)
	$(PY) $< $(VGEN_FONT_RENDER)

# Synthesis: produce JSON for nextpnr
$(JSON): $(VGEN_SK9822) $(VGEN_RAINBOW) $(VGEN_PATTERN) $(VGEN_BUTTON) $(VGEN_MAINMENU) $(VGEN_FLASH) $(VGEN_IMAGE) $(VGEN_NICK) $(VGEN_STACKER) $(VGEN_FONT_RENDER) $(WRAP) $(PCF)
	$(YOSYS) -q -p "synth_ice40 -top $(TOP) -json $(JSON)" $(VGEN_SK9822) $(VGEN_RAINBOW) $(VGEN_PATTERN) $(VGEN_BUTTON) $(VGEN_MAINMENU) $(VGEN_FLASH) $(VGEN_IMAGE) $(VGEN_NICK) $(VGEN_STACKER) $(VGEN_FONT_RENDER) $(WRAP)

# Place & Route
$(ASC): $(JSON)
	$(NEXTPNR) --$(DEVICE) --package $(PKG) --freq 16 --seed $(SEED) --json $(JSON) --pcf $(PCF) --asc $(ASC) 2>&1 | tee $(BUILD)/nextpnr.log

# Pack binary for the bare_metal_bootloader
$(BIN): $(ASC)
	$(ICEPACK) $(ASC) $(BIN)

# Convert image(s) to flash format
# Prefers image.txt (list of images), falls back to single image file
$(IMAGE_BIN): $(IMAGE_CONVERTER) $(IMAGE_SOURCE) | $(BUILD)
	@if [ -f image.txt ]; then \
		echo "Converting images from image.txt to $(IMAGE_BIN)..."; \
		$(PY) $(IMAGE_CONVERTER) image.txt $(IMAGE_BIN) $(IMAGE_FRAME_DIVIDER); \
	elif [ -f image.png ] || [ -f image.jpg ] || [ -f image.jpeg ]; then \
		IMG=$$(ls image.png image.jpg image.jpeg 2>/dev/null | head -1); \
		echo "Converting $$IMG to $(IMAGE_BIN)..."; \
		$(PY) $(IMAGE_CONVERTER) $$IMG $(IMAGE_BIN) $(IMAGE_FRAME_DIVIDER); \
	else \
		echo "No image.png/jpg found, trying to fetch random image from picsum.photos..."; \
		WIDTH=$$(shuf -n 1 some_primes.txt); \
		HEIGHT=$$(shuf -n 1 some_primes.txt); \
		URL="https://picsum.photos/$$WIDTH/$$HEIGHT"; \
		echo "Fetching: $$URL"; \
		if curl -L -o image.jpg "$$URL" 2>/dev/null; then \
			echo "Successfully downloaded image ($$WIDTH x $$HEIGHT)"; \
			$(PY) $(IMAGE_CONVERTER) image.jpg $(IMAGE_BIN) $(IMAGE_FRAME_DIVIDER); \
		else \
			echo "Failed to fetch image, creating empty placeholder..."; \
			dd if=/dev/zero of=$(IMAGE_BIN) bs=10 count=1 2>/dev/null; \
		fi \
	fi

# Convert font to flash format
$(FONT_BIN): $(FONT_CONVERTER) host/font.py | $(BUILD)
	$(PY) $(FONT_CONVERTER) $(FONT_BIN)

# Combined binary: bitstream at 0x020000 (slot 1), image at 0x0b0000 (userdata)
# CRITICAL: 0x00000-0x1ffff is bootloader - DO NOT OVERWRITE!
$(COMBINED_BIN): $(BIN) $(IMAGE_BIN)
	@echo "Creating combined binary..."
	@dd if=/dev/zero of=$@ bs=1024 count=1024 2>/dev/null
	@dd if=$(BIN) of=$@ bs=1 seek=$$((0x020000)) conv=notrunc 2>/dev/null
	@dd if=$(IMAGE_BIN) of=$@ bs=1 seek=$$((0x0b0000)) conv=notrunc 2>/dev/null
	@echo "Created $@ (bitstream @ 0x020000 + image @ 0x0b0000)"

# Nick binary
NICK_TXT = nick.txt
NICK_BIN = build/nick.bin
NICK_CONVERTER = host/nick_convert.py

$(NICK_BIN): $(NICK_TXT) $(NICK_CONVERTER)
	@mkdir -p $(BUILD)
	@if [ -f "$(NICK_TXT)" ]; then \
		$(PY) $(NICK_CONVERTER) $(NICK_TXT) $(NICK_BIN); \
	else \
		echo "Warning: $(NICK_TXT) not found, creating placeholder"; \
		$(PY) $(NICK_CONVERTER) /dev/null $(NICK_BIN); \
	fi

image: $(IMAGE_BIN)

font: $(FONT_BIN)

nick: $(NICK_BIN)

combined: $(COMBINED_BIN)

clean:
	rm -rf $(BUILD)

# Programming: bare_metal_bootloader
# Preferred method: use tinyprog (pip install tinyprog)
prog:flash
flash: $(BIN)
	$(TINYPROG) -p $(BIN)

# Flash image data to 0x0b0000
flash-image: $(IMAGE_BIN)
	$(TINYPROG) -a 0x0b0000 -p $(IMAGE_BIN)

# Flash nick data to 0x0a0000
flash-nick: $(NICK_BIN)
	$(TINYPROG) -a 0x0a0000 -p $(NICK_BIN)

# Flash font data to 0x080000
flash-font: $(FONT_BIN)
	$(TINYPROG) -a 0x080000 -p $(FONT_BIN)

# Flash both bitstream and image (separate commands to preserve bootloader)
flash-combined: $(BIN) $(IMAGE_BIN)
	@echo "Flashing bitstream to slot 1..."
	$(TINYPROG) -p $(BIN)
	@echo "Flashing image to 0x0b0000..."
	$(TINYPROG) -a 0x0b0000 -p $(IMAGE_BIN)
	@echo "Flash complete!"

boot:run
run:
	tinyprog -b

# Resource utilization report
report: $(ASC)
	@echo "============================================"
	@echo "  Resource Utilization Report"
	@echo "  Device: iCE40UP5K-SG48 (bare_metal)"
	@echo "============================================"
	@echo ""
	@icebox_stat $(ASC) 2>/dev/null || echo "icebox_stat not found, using nextpnr log..."
	@echo ""
	@echo "--- From nextpnr Place & Route ---"
	@grep -A 20 "Device utilisation:" build/nextpnr.log 2>/dev/null || \
		$(NEXTPNR) --$(DEVICE) --package $(PKG) --json $(JSON) --pcf $(PCF) --asc $(ASC) 2>&1 | tee build/nextpnr.log | grep -A 20 "Device utilisation:"
	@echo ""
	@echo "--- Timing Summary ---"
	@grep "Max frequency for clock" build/nextpnr.log 2>/dev/null || \
		grep "Max frequency for clock" <($(NEXTPNR) --$(DEVICE) --package $(PKG) --json $(JSON) --pcf $(PCF) --asc $(ASC) 2>&1 | tee build/nextpnr.log)
	@echo ""
	@echo "Binary size: $$(ls -lh $(BIN) | awk '{print $$5}')"
	@echo "============================================"

# Detailed timing analysis
timing: $(ASC)
	@echo "Detailed Timing Report:"
	@grep -A 50 "Critical path report" build/nextpnr.log 2>/dev/null || \
		$(NEXTPNR) --$(DEVICE) --package $(PKG) --json $(JSON) --pcf $(PCF) --asc $(ASC) 2>&1 | tee build/nextpnr.log | grep -A 50 "Critical path report"

# Quick stats (resource usage only)
stats: $(ASC)
	@grep -A 10 "Device utilisation:" build/nextpnr.log 2>/dev/null || \
		$(NEXTPNR) --$(DEVICE) --package $(PKG) --json $(JSON) --pcf $(PCF) --asc $(ASC) 2>&1 | tee build/nextpnr.log | grep -A 10 "Device utilisation:"

# Help target
help:
	@echo "======================================================================"
	@echo "  bare_metal - Build System"
	@echo "======================================================================"
	@echo ""
	@echo "info: Flash memory layout (bootloader-safe)"
	@echo "  0x000000-0x01ffff: USB bootloader (know what you do!)"
	@echo "  0x020000-0x03ffff: Slot 1 - user bitstream (tinyprog writes here)"
	@echo "  0x040000-0x07ffff: Slots 2-3 (reserved)"
	@echo "  0x080000-0x08ffff: Font data (64 KB)"
	@echo "  0x090000-0x09ffff: Game data (64 KB)"
	@echo "  0x0a0000-0x0affff: Nicknames (64 KB)"
	@echo "  0x0b0000-0x0fffff: Media - images/video (~15.3 MB)"
	@echo ""
	@echo "main targets:"
	@echo "  make              Build bitstream (build/top.bin)"
	@echo "  make image        Convert image.png/jpg to flash format"
	@echo "  make font         Convert font to flash format"
	@echo "  make combined     Build bitstream + image (build/combined.bin)"
	@echo "  make flash        Flash bitstream to slot 1 (preserves bootloader)"
	@echo "  make flash-image  Flash image data to 0x0b0000"
	@echo "  make flash-font   Flash font data to 0x080000"
	@echo "  make flash-combined  Flash both bitstream and image"
	@echo "  make boot         Exit bootloader and run"
	@echo "  make clean        Remove all build artifacts"
	@echo ""
	@echo "analysis targets:"
	@echo "  make report       Full resource utilization + timing"
	@echo "  make stats        Quick resource usage"
	@echo "  make timing       Detailed timing analysis"
	@echo ""
	@echo "configuration:"
	@echo "  IMAGE_FRAME_DIVIDER=$(IMAGE_FRAME_DIVIDER)  (frames between image moves)"
	@echo ""
	@echo "Usage:"
	@echo "  1. Place image.png or image.jpg in project root"
	@echo "  2. Place nick.txt  in project root"
	@echo "  3. Run: make flash && make flash-image && make flash-nick && make flash-font"
	@echo "  4. Run: make boot"
	@echo ""
	@echo "Note: tinyprog automatically writes to slot 1 (0x020000), not 0x000000!"
	@echo "======================================================================"

