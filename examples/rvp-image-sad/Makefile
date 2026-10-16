# CC must support RV64 P v0.6; LINK_CC may be a compatible Linux GCC driver.
CC = riscv64-unknown-linux-gnu-gcc
LINK_CC = $(CC)
BUILD ?= build
CPPFLAGS ?=
OPTFLAGS ?= -O3
ALIGNFLAGS ?= -mstrict-align
COMMON = $(OPTFLAGS) -std=gnu11 -Wall -Wextra -Werror -fno-lto \
         -fno-tree-vectorize -fno-tree-slp-vectorize -mabi=lp64d $(ALIGNFLAGS)
BASE_ARCH = rv64gc_zba_zbb
P_ARCH = rv64gc_p0p6

.PHONY: all clean
all: $(BUILD)/sad-demo

$(BUILD):
	mkdir -p $@

$(BUILD)/sad-scalar.o: sad-scalar.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(BASE_ARCH) -c $< -o $@

$(BUILD)/sad-p.o: sad-p.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(P_ARCH) -c $< -o $@

$(BUILD)/demo.o: demo.c sad.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(COMMON) -march=$(BASE_ARCH) -c $< -o $@

$(BUILD)/sad-demo: $(BUILD)/sad-scalar.o $(BUILD)/sad-p.o $(BUILD)/demo.o
	$(LINK_CC) -march=$(BASE_ARCH) -mabi=lp64d -fno-lto -static $^ -o $@

clean:
	rm -f $(BUILD)/sad-scalar.o $(BUILD)/sad-p.o $(BUILD)/demo.o \
	      $(BUILD)/sad-demo
