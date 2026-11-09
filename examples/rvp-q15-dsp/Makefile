# SPDX-License-Identifier: MIT
CC = riscv$(XLEN)-unknown-linux-gnu-gcc
HOST_CC ?= cc
LINK_CC = $(CC)
BUILD ?= build
CPPFLAGS ?=
OPTFLAGS ?= -O3
XLEN ?= 32
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
CPPFLAGS += -DQ15_HW_UNALIGNED=1
else ifeq ($(ALIGNMENT),strict)
ALIGNFLAGS = -mstrict-align
CPPFLAGS += -DQ15_HW_UNALIGNED=0
else
$(error ALIGNMENT must be hardware or strict)
endif

COMMON = $(OPTFLAGS) -std=gnu11 -Wall -Wextra -Werror -fno-lto \
         -fno-tree-vectorize -fno-tree-slp-vectorize -fstack-usage \
         -mtune=size -mabi=$(ABI) $(ALIGNFLAGS)

.PHONY: all host clean
all: $(BUILD)/q15-demo
host: $(BUILD)/q15-host-test

$(BUILD):
	mkdir -p $@

$(BUILD)/q15-scalar.o: q15-scalar.c q15.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(BASE_ARCH) -c $< -o $@

$(BUILD)/q15-p.o: q15-p.c q15.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(P_ARCH) -c $< -o $@

$(BUILD)/demo.o: demo.c q15.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(RUNTIME_ARCH) -c $< -o $@

$(BUILD)/q15-demo: $(BUILD)/q15-scalar.o $(BUILD)/q15-p.o $(BUILD)/demo.o
	$(LINK_CC) -march=$(RUNTIME_ARCH) -mabi=$(ABI) -fno-lto -static $^ -o $@

$(BUILD)/q15-host-test: q15-scalar.c demo.c q15.h | $(BUILD)
	$(HOST_CC) $(OPTFLAGS) -std=gnu11 -Wall -Wextra -Werror \
	  -DQ15_SCALAR_ONLY q15-scalar.c demo.c -o $@

clean:
	rm -f $(BUILD)/q15-scalar.o $(BUILD)/q15-p.o $(BUILD)/demo.o \
	  $(BUILD)/q15-demo $(BUILD)/q15-host-test $(BUILD)/*.su
