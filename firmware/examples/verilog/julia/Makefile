# julia demo - iCE40UP5K-SG48
# Verilog -> Yosys -> nextpnr-ice40 -> icepack

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
TOP    = julia_top

# ---- Directories ----
BUILD = build
VSRC  = vsrc

# ---- Flash memory map ----
# Default to slot 2 but allow override
SLOT ?= 2

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
VSRCS = $(wildcard $(VSRC)/*.v)
PCF   = constraints/bare_metal.pcf

# ---- Output files ----
JSON = $(BUILD)/$(TOP).json
ASC  = $(BUILD)/$(TOP).asc
BIN  ?= $(BUILD)/$(TOP).bin

# ===========================================================================
.PHONY: all clean flash

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
