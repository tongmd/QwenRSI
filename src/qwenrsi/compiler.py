"""Compile the same bounded C controller to native and RV32IM executables."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LINKER = """ENTRY(_start)
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
"""
RV_WRAPPER = r"""
volatile int input_state[16] __attribute__((section(".input"))) = {0};
static void emit(int x) {
    register int a0 __asm__("a0") = x;
    register int a7 __asm__("a7") = 1;
    __asm__ volatile("ecall" : : "r"(a0), "r"(a7) : "memory");
}
void _start(void) __attribute__((section(".text.init"), noreturn));
void _start(void) {
    int s[16]; for (int i=0; i<16; ++i) s[i]=input_state[i];
    int result = s[15] ? select_candidate(s) : policy(s);
    emit(result);
    register int a0 __asm__("a0") = 0;
    register int a7 __asm__("a7") = 93;
    __asm__ volatile("ecall" : : "r"(a0), "r"(a7) : "memory");
    for (;;) {}
}
"""
NATIVE_WRAPPER = r"""
#include <stdio.h>
int main(void) {
    int s[16]; for(int i=0;i<16;i++) if(scanf("%d", &s[i])!=1) return 2;
    printf("%d\n", s[15] ? select_candidate(s) : policy(s));
    return 0;
}
"""


class CompileError(RuntimeError):
    pass


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _command(command, timeout=90):
    p = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise CompileError(p.stderr[-6000:])
    return p


def build(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = source.read_text()
    # No includes, macros, inline assembly, or dynamic host APIs in the public controller ABI.
    # This is a language restriction, not an OS sandbox. Run untrusted proposals in a container.
    import re

    if re.search(r"^\s*#|\b(?:asm|__asm__|__attribute__|include)\b", text, re.MULTILINE):
        raise CompileError("Controller C must be freestanding: no preprocessor or assembly.")
    native = out / "native.c"
    native.write_text(text + "\n" + NATIVE_WRAPPER)
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("cc")
    if not cc:
        raise CompileError("Install a native C compiler (cc/clang/gcc).")
    _command([cc, "-std=c11", "-O2", "-Wall", "-Werror", str(native), "-o", str(out / "controller")])
    rv = out / "firmware.c"
    rv.write_text(text + "\n" + RV_WRAPPER)
    (out / "rom.ld").write_text(LINKER)
    zig = shutil.which("zig")
    if zig:
        driver = [zig]
    else:
        try:
            import ziglang  # noqa: F401
        except ImportError as exc:
            raise CompileError("Install ziglang: pip install ziglang") from exc
        driver = [sys.executable, "-m", "ziglang"]
    _command(
        driver
        + [
            "cc",
            "-target",
            "riscv32-freestanding",
            "-mcpu=generic_rv32+m-a-c-d-f",
            "-mabi=ilp32",
            "-O2",
            "-std=c11",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-nostdlib",
            "-mno-relax",
            "-Wl,-T," + str(out / "rom.ld"),
            str(rv),
            "-o",
            str(out / "controller.elf"),
        ],
        timeout=180,
    )
    (out / "source.c").write_text(text)
    manifest = {
        "schema_version": 1,
        "source_sha256": sha256(source),
        "elf_sha256": sha256(out / "controller.elf"),
        "abi": "qwenrsi-controller-v1",
        "input_address": 256,
        "isa": "rv32im",
        "compiler": driver,
        "source": "source.c",
        "firmware": "controller.elf",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def state_vector(state, mode=0):
    vals = list(state)
    if len(vals) > 15 or any(type(x) is not int or not -(2**31) <= x < 2**31 for x in vals):
        raise ValueError("Expected up to 15 signed int32 state values")
    return vals + [0] * (15 - len(vals)) + [mode]


class NativeController:
    def __init__(self, directory):
        self.directory = Path(directory)

    def decide(self, state, mode=0):
        p = subprocess.run(
            [str((self.directory / "controller").resolve())],
            input=" ".join(map(str, state_vector(state, mode))),
            text=True,
            capture_output=True,
            timeout=10,
        )
        if p.returncode:
            raise RuntimeError(f"Controller exited with code {p.returncode}")
        return int(p.stdout.strip())


class ReferenceController:
    def __init__(self, directory):
        from qwenrsi import enable_chipformer

        enable_chipformer()
        from chipformer.rv import elf

        self.program = elf.program(Path(directory) / "controller.elf")

    def machine(self, state, mode=0):
        from chipformer.rv.ref import Machine

        m = Machine.from_program(self.program)
        for i, value in enumerate(state_vector(state, mode)):
            m.ram[64 + i] = value & 0xFFFFFFFF
        return m

    def decide(self, state, mode=0):
        m = self.machine(state, mode)
        m.run(10000)
        if not m.halted or m.fault or len(m.out) != 1 or m.exit_code != 0:
            raise RuntimeError(f"RV32 controller fault/hang: {m.fault}")
        return m.out[0]
