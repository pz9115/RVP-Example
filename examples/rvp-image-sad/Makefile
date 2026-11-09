# CC and its runtime must match XLEN and ABI and support P draft 0.6.
CC = riscv64-unknown-linux-gnu-gcc
LINK_CC = $(CC)
BUILD ?= build
CPPFLAGS ?=
OPTFLAGS ?= -O3
XLEN ?= 64
ALIGNMENT ?= strict
ifeq ($(XLEN),32)
ABI = ilp32
BASE_ARCH = rv32imc_zba_zbb
P_ARCH = rv32imcp0p6_zba_zbb
RUNTIME_ARCH = rv32imac
else ifeq ($(XLEN),64)
ABI = lp64d
BASE_ARCH = rv64gc_zba_zbb
P_ARCH = rv64gc_p0p6
RUNTIME_ARCH = rv64gc
else
$(error XLEN must be 32 or 64)
endif
ifeq ($(ALIGNMENT),hardware)
ALIGNFLAGS = -mno-strict-align
CPPFLAGS += -DSAD_HW_UNALIGNED=1
else ifeq ($(ALIGNMENT),strict)
ALIGNFLAGS = -mstrict-align
CPPFLAGS += -DSAD_HW_UNALIGNED=0
else
$(error ALIGNMENT must be hardware or strict)
endif
COMMON = $(OPTFLAGS) -std=gnu11 -Wall -Wextra -Werror -fno-lto \
         -fno-tree-vectorize -fno-tree-slp-vectorize -fstack-usage \
         -mtune=size -mabi=$(ABI) $(ALIGNFLAGS)

.PHONY: all clean
all: $(BUILD)/sad-demo

$(BUILD):
	mkdir -p $@

$(BUILD)/sad-scalar.o: sad-scalar.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(BASE_ARCH) -c $< -o $@

$(BUILD)/sad-p.o: sad-p.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(P_ARCH) -c $< -o $@

$(BUILD)/demo.o: demo.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(RUNTIME_ARCH) -c $< -o $@

$(BUILD)/sad-demo: $(BUILD)/sad-scalar.o $(BUILD)/sad-p.o $(BUILD)/demo.o
	$(LINK_CC) -march=$(RUNTIME_ARCH) -mabi=$(ABI) -fno-lto -static $^ -o $@

clean:
	rm -f $(BUILD)/sad-scalar.o $(BUILD)/sad-p.o $(BUILD)/demo.o \
	      $(BUILD)/sad-demo $(BUILD)/*.su
