# hackerstacker_demo — iCE40UP5K-SG48 (bare_metal)
# Amaranth HDL → Yosys → nextpnr-ice40 → icepack

# ---- Toolchain ----
PY       ?= python3
YOSYS    ?= yosys
NEXTPNR  ?= nextpnr-ice40
ICEPACK  ?= icepack
TINYPROG ?= tinyprog
SEED     ?= 1

# ---- FPGA ----
DEVICE = up5k
PKG    = sg48
TOP    = top

# ---- Directories ----
BUILD = build
VSRC  = vsrc
FONTS = fonts

# ---- Flash memory map ----
#
# 0x000_0000 - 0x000_009f =160b, multiboot header, slot table
# 0x000_00a0 - 0x001_efff ~124kB, slot 0, bare_metal_bootloader
# 0x001_f000 - 0x001_ffff =4kB, bootmetadata
# 0x002_0000 - 0x003_ffff =128kB, slot 1, user bitstream, hackerstacker_demo by default
# 0x004_0000 - 0x005_ffff =128kB, slot 2, transputers anyone?
# 0x006_0000 - 0x007_ffff ~128kB, slot 3, hooray for transputers
# 0x008_0000 - 0x100_0000 user data, images, fonts, text, sounds, etc
#
# here, in hackerstacker_demo, we reserve the first 512 KB for bootloader and bitstreams,
# and use the rest for user data:
# 0x008_0000 - 0x008_ffff = 64 kB, font data
# 0x009_0000 - 0x009_ffff = 64 kB, game data
# 0x00a_0000 - 0x00a_ffff = 64 kB, nick names
# 0x00b_0000 - 0x0ff_ffff = ~15.3MB images, video

ADDR_FONT  = 0x080000
ADDR_NICK  = 0x0a0000
ADDR_IMAGE = 0x0b0000

# ---- Nick fonts: path:height (first = default) ----
NICK_FONTS = $(FONTS)/04B_03B_.TTF:8 $(FONTS)/04B_30__.TTF:16

# ---- Image settings ----
IMAGE_FRAME_DIVIDER ?= 32

# ---- Source → Verilog module name mapping ----
# Each src/foo.py has verilog.convert(name="bar") producing build/bar.v
# Map: src_basename → verilog_module_name
MOD_sk9822           = sk9822_controller
MOD_rainbow          = rainbow_module
MOD_pattern          = pattern_module
MOD_button           = button_handler
MOD_mainmenu         = mainmenu
MOD_flash_controller = flash_controller
MOD_image            = image_module
MOD_nick             = nick_module
MOD_stacker          = stacker_module
MOD_font_render      = font_render

# Collect all src/*.py and derive verilog outputs
AMARANTH_SRC := $(wildcard src/*.py)
SRC_BASES    := $(basename $(notdir $(AMARANTH_SRC)))
VGEN_ALL     := $(foreach b,$(SRC_BASES),$(BUILD)/$(MOD_$(b)).v)

# ---- Static sources ----
WRAP = $(VSRC)/board_top.v
PCF  = constraints/top.pcf

# ---- Output files ----
JSON      = $(BUILD)/$(TOP).json
ASC       = $(BUILD)/$(TOP).asc
BIN       = $(BUILD)/$(TOP).bin
FONT_BIN  = $(BUILD)/font.bin
NICK_BIN  = $(BUILD)/nick.bin
IMAGE_BIN = $(BUILD)/image.bin

# ---- Host tools ----
FONT_CONVERTER  = host/font_convert.py
NICK_CONVERTER  = host/nick_convert.py
IMAGE_CONVERTER = host/image_convert.py

# ---- Image source (prefer image.txt, fallback to single file) ----
IMAGE_SOURCE = $(firstword $(wildcard image.txt image.png image.jpg image.jpeg))
NICK_TXT     = nick.txt

# ===========================================================================
.PHONY: all clean flash boot run image font nick report timing stats help

all: $(BIN)

$(BUILD):
	mkdir -p $@

# ---- Amaranth → Verilog (one rule per module, generated from mapping) ----
define VGEN_RULE
$(BUILD)/$(MOD_$(1)).v: src/$(1).py | $(BUILD)
	$$(PY) $$< $$@
endef
$(foreach b,$(SRC_BASES),$(eval $(call VGEN_RULE,$(b))))

# ---- Synthesis ----
$(JSON): $(VGEN_ALL) $(WRAP) $(PCF)
	$(YOSYS) -q -p "synth_ice40 -top $(TOP) -dsp -json $@" $(VGEN_ALL) $(WRAP)

# ---- Place & Route ----
$(ASC): $(JSON)
	$(NEXTPNR) --$(DEVICE) --package $(PKG) --freq 16 --seed $(SEED) \
		--json $< --pcf $(PCF) --asc $@ 2>&1 | tee $(BUILD)/nextpnr.log

# ---- Pack bitstream ----
$(BIN): $(ASC)
	$(ICEPACK) $< $@

# ---- Font binary ----
$(FONT_BIN): $(FONT_CONVERTER) $(wildcard $(FONTS)/*.TTF $(FONTS)/*.ttf) | $(BUILD)
	$(PY) $(FONT_CONVERTER) $(NICK_FONTS) -o $@

# ---- Nick binary ----
$(NICK_BIN): $(NICK_TXT) $(NICK_CONVERTER) | $(BUILD)
	@if [ -f "$(NICK_TXT)" ]; then \
		$(PY) $(NICK_CONVERTER) $(NICK_TXT) -o $@; \
	else \
		echo "Warning: $(NICK_TXT) not found, creating placeholder"; \
		printf 'N\x03\x00\x00\x00\x00\x00\x00' > $@; \
	fi

# ---- Image binary ----
$(IMAGE_BIN): $(IMAGE_CONVERTER) $(IMAGE_SOURCE) | $(BUILD)
	@if [ -f image.txt ]; then \
		echo "Converting images from image.txt..."; \
		$(PY) $(IMAGE_CONVERTER) image.txt $@ $(IMAGE_FRAME_DIVIDER); \
	elif [ -f image.png ] || [ -f image.jpg ] || [ -f image.jpeg ]; then \
		IMG=$$(ls image.png image.jpg image.jpeg 2>/dev/null | head -1); \
		echo "Converting $$IMG..."; \
		$(PY) $(IMAGE_CONVERTER) $$IMG $@ $(IMAGE_FRAME_DIVIDER); \
	else \
		echo "No image found, fetching random from picsum.photos..."; \
		W=$$(shuf -n 1 some_primes.txt); H=$$(shuf -n 1 some_primes.txt); \
		curl -L -o image.jpg "https://picsum.photos/$$W/$$H" 2>/dev/null && \
		$(PY) $(IMAGE_CONVERTER) image.jpg $@ $(IMAGE_FRAME_DIVIDER) || \
		dd if=/dev/zero of=$@ bs=10 count=1 2>/dev/null; \
	fi

# ---- Convenience ----
image: $(IMAGE_BIN)
font:  $(FONT_BIN)
nick:  $(NICK_BIN)

clean:
	rm -rf $(BUILD)

# ---- Flash targets ----
flash: $(BIN)
	$(TINYPROG) -p $<

flash-font: $(FONT_BIN)
	$(TINYPROG) -a $(ADDR_FONT) -p $<

flash-nick: $(NICK_BIN)
	$(TINYPROG) -a $(ADDR_NICK) -p $<

flash-image: $(IMAGE_BIN)
	$(TINYPROG) -a $(ADDR_IMAGE) -p $<

flash-all: $(BIN) $(FONT_BIN) $(NICK_BIN) $(IMAGE_BIN)
	$(TINYPROG) -p $(BIN)
	$(TINYPROG) -a $(ADDR_FONT) -p $(FONT_BIN)
	$(TINYPROG) -a $(ADDR_NICK) -p $(NICK_BIN)
	$(TINYPROG) -a $(ADDR_IMAGE) -p $(IMAGE_BIN)
	@echo "All flashed. Run: make boot"

boot: run
run:
	$(TINYPROG) -b

# ---- Analysis ----
report: $(ASC)
	@echo "=== Resource Utilization (iCE40UP5K-SG48) ==="
	@grep -A 20 "Device utilisation:" $(BUILD)/nextpnr.log 2>/dev/null
	@echo ""
	@echo "=== Timing ==="
	@grep "Max frequency for clock" $(BUILD)/nextpnr.log 2>/dev/null
	@echo "Binary: $$(ls -lh $(BIN) | awk '{print $$5}')"

timing: $(ASC)
	@grep -A 50 "Critical path report" $(BUILD)/nextpnr.log 2>/dev/null

stats: $(ASC)
	@grep -A 10 "Device utilisation:" $(BUILD)/nextpnr.log 2>/dev/null

# ---- Help ----
help:
	@echo "hackerstacker_demo build system"
	@echo ""
	@echo "Flash memory map:"
	@echo "  0x000_0000 - 0x000_009f =160b, multiboot header, slot table"
	@echo "  0x000_00a0 - 0x001_efff ~124kB, slot 0, bare_metal_bootloader"
	@echo "  0x001_f000 - 0x001_ffff =4kB, bootmetadata"
	@echo "  0x002_0000 - 0x003_ffff =128kB, slot 1, user bitstream (hackerstacker_demo)"
	@echo "  0x004_0000 - 0x005_ffff =128kB, slot 2, transputers anyone?"
	@echo "  0x006_0000 - 0x007_ffff ~128kB, slot 3, hooray for transputers"
	@echo "  0x008_0000 - 0x008_ffff = 64kB, font data"
	@echo "  0x009_0000 - 0x009_ffff = 64kB, game data"
	@echo "  0x00a_0000 - 0x00a_ffff = 64kB, nick names"
	@echo "  0x00b_0000 - 0x0ff_ffff =~15.3MB, images, video"
	@echo ""
	@echo "Targets:"
	@echo "  make              Build bitstream"
	@echo "  make font         Build font.bin"
	@echo "  make nick         Build nick.bin"
	@echo "  make image        Build image.bin"
	@echo "  make flash        Flash bitstream to slot 1"
	@echo "  make flash-font   Flash font  → $(ADDR_FONT)"
	@echo "  make flash-nick   Flash nick  → $(ADDR_NICK)"
	@echo "  make flash-image  Flash image → $(ADDR_IMAGE)"
	@echo "  make flash-all    Flash everything"
	@echo "  make boot         Boot into user bitstream"
	@echo "  make clean        Remove build/"
	@echo "  make stats        Quick resource usage"
	@echo "  make report       Full utilization + timing"
	@echo ""
	@echo "Fonts: $(NICK_FONTS)"
