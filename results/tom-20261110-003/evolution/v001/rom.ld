ENTRY(_start)
MEMORY { RAM (rw) : ORIGIN = 0x100, LENGTH = 0x6f00
DROM (r) : ORIGIN = 0x20000, LENGTH = 128K
ROM (rx) : ORIGIN = 0x40000, LENGTH = 256K }
SECTIONS {
 .text : { *(.text.init) *(.text .text.*) } > ROM
 .rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > DROM
 .input : { KEEP(*(.input)) } > RAM
 .data : { *(.data .data.* .sdata .sdata.*) } > RAM
 .bss : { *(.bss .bss.* .sbss .sbss.*) *(COMMON) } > RAM
 /DISCARD/ : { *(.comment) *(.eh_frame*) *(.riscv.attributes) }
}
