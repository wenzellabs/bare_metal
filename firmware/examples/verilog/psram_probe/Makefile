# psram_probe - iCE40UP5K-SG48
# Simple example that probes external SPI PSRAM size at runtime and
# displays a proportional bar on the 16x8 SK9822 LED matrix.

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
TOP    = psram_probe_top

# ---- Directories ----
BUILD = build
VSRC  = vsrc

# ---- Flash memory map ----
# Default to slot 3 but allow override
SLOT ?= 3

ifeq ($(SLOT), 1)
  FLASH_ADDR = 0x020000
else ifeq ($(SLOT), 2)
  FLASH_ADDR = 0x040000
else ifeq ($(SLOT), 3)
  FLASH_ADDR = 0x060000
else
  $(error SLOT must be 1, 2, or 3)
endif

# ---- Static sources ----
# We'll include the julia sk9822 controller from that example so we don't
# duplicate it. Add our local vsrc for probe + display.
VSRCS = $(wildcard vsrc/*.v) $(wildcard vsrc/usb_lib/*.v) ../../verilog/julia/vsrc/sk9822_controller.v
PCF   = constraints/bare_metal.pcf

# ---- Output files ----
JSON = $(BUILD)/$(TOP).json
ASC  = $(BUILD)/$(TOP).asc
BIN  ?= $(BUILD)/$(TOP).bin

.PHONY: all clean flash report timing stats help

all: $(BUILD)/$(TOP).bin

$(BUILD):
	mkdir -p $@

# ---- Synthesis ----
$(JSON): $(VSRCS) $(PCF) | $(BUILD)
	$(YOSYS) -q -p "synth_ice40 -top $(TOP) -dsp -json $@" $(VSRCS)

# ---- Place & Route ----
$(ASC): $(JSON)
	$(NEXTPNR) --$(DEVICE) --package $(PKG) --freq 16 --seed $(SEED) \
		--json $< --pcf $(PCF) --asc $@ 2>&1 | tee $(BUILD)/nextpnr.log

# ---- Pack bitstream ----
$(BUILD)/$(TOP).bin: $(ASC)
	$(ICEPACK) $< $@

# ---- Flash bootloader ----
flash: $(BIN)
	$(TINYPROG) -p $< -a $(FLASH_ADDR)

clean:
	rm -rf $(BUILD)

report: $(ASC)
	@echo "=== Resource Utilization (iCE40UP5K-SG48) ==="
	@grep -A 20 "Device utilisation:" $(BUILD)/nextpnr.log 2>/dev/null
	@echo ""
	@echo "=== Timing ==="
	@grep "Max frequency for clock" $(BUILD)/nextpnr.log 2>/dev/null
	@echo "Binary: $$(ls -lh $(BIN) | awk '{print $$5}')"

help:
	@echo "psram_probe example build system"
	@echo "  make              Build bitstream"
	@echo "  make flash        Flash bitstream to SLOT $(SLOT) (default: 3)"
	@echo "  make SLOT=N flash Flash to specific slot (1, 2, or 3)"
