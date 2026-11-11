"""Trace compiler for the RV32 controller ABI.

The circuit runs a guarded complete invocation. Memory is invocation-local and
only the action byte is observable. Runtime guards are computed by the same
SwiGLU graph as the action. Unsupported instructions and guard misses use RV32.
"""

import time
from collections import Counter
from dataclasses import dataclass

from qwenrsi import enable_chipformer
from qwenrsi.circuit import CircuitController, capture_cuda_step, trace_action
from qwenrsi.compiler import state_vector

enable_chipformer()
from chipformer.q35.prims import Circ  # noqa: E402
from chipformer.rv import ref  # noqa: E402
from chipformer.rv import spec as S  # noqa: E402

WORD = 32
MASK = (1 << WORD) - 1


class UnsupportedTrace(ValueError):
    pass


@dataclass(frozen=True)
class Instruction:
    pc: int
    word: int
    next_pc: int
    syscall: int | None


def observe(machine, generated, max_instructions=256):
    """Recover instruction boundaries and verify the full GPU trace before compiling."""
    instructions = []
    trace = [S.tok("GO")]
    while not machine.halted:
        if len(instructions) >= max_instructions or len(trace) > len(generated):
            raise UnsupportedTrace("trace exceeds the compilation budget")
        if machine.n == S.N_MAX:
            trace.extend(machine.record())
            continue
        pc = machine.pc
        word = machine.rom[(pc - S.ROM_BASE) >> 2]
        syscall = machine.x[17] if word == 0x73 else None
        trace.extend(machine.record())
        instructions.append(Instruction(pc, word, machine.pc, syscall))
    if trace != generated:
        raise RuntimeError("GPU trace disagrees with the RV32 reference during JIT profiling")
    if machine.fault or machine.exit_code != 0 or len(machine.out) != 1:
        raise UnsupportedTrace("expected one action byte and a clean exit")
    return tuple(instructions)


def bits(value, width=WORD):
    return tuple((value >> i) & 1 for i in range(width))


def constant(word):
    if all(isinstance(bit, int) for bit in word):
        return sum(bit << i for i, bit in enumerate(word))
    return None


def pack_state(state, mode):
    return sum((word & MASK) << (WORD * i) for i, word in enumerate(state_vector(state, mode)))


class TraceCompiler:
    def __init__(self, machine):
        self.circuit = Circ()
        self.machine = machine
        self.registers = [bits(v) for v in machine.x]
        self.memory = {}
        self.guards = []
        self.output = None

    def invert(self, bit):
        return 1 - bit if isinstance(bit, int) else self.circuit.one - bit

    def and_bits(self, values):
        unique = {}
        for bit in values:
            if isinstance(bit, int):
                if bit == 0:
                    return 0
            else:
                unique[tuple(sorted(bit.terms.items()))] = bit
        values = list(unique.values())
        if not values:
            return 1
        if len(values) == 1:
            return values[0]
        return self.circuit.and_(values, "and")

    def or_bits(self, values):
        return self.invert(self.and_bits(self.invert(bit) for bit in values))

    def xor(self, a, b):
        if isinstance(a, int):
            return self.invert(b) if a else b
        if isinstance(b, int):
            return self.invert(a) if b else a
        if a.terms == b.terms:
            return 0
        return a + b - 2 * self.and_bits((a, b))

    def equal(self, a, b):
        return self.and_bits(self.invert(self.xor(x, y)) for x, y in zip(a, b))

    def less(self, a, b, signed):
        if signed:
            a = (*a[:-1], self.invert(a[-1]))
            b = (*b[:-1], self.invert(b[-1]))
        matches = [self.invert(self.xor(x, y)) for x, y in zip(a, b)]
        # Exactly one term can hold. Compare at the highest differing bit.
        terms = [self.and_bits((self.invert(x), y, *matches[i + 1 :])) for i, (x, y) in enumerate(zip(a, b))]
        result = sum(terms)
        return result

    def add(self, a, b, carry=0):
        result = []
        for x, y in zip(a, b):
            propagate = self.xor(x, y)
            result.append(self.xor(propagate, carry))
            # Generate and propagate are mutually exclusive.
            carry = self.and_bits((x, y)) + self.and_bits((propagate, carry))
        return tuple(result)

    def alu(self, op, a, b):
        x, y = constant(a), constant(b)
        if x is not None and y is not None:
            return bits(ref.alu(op, x, y))
        if op in {"ADD", "ADDI"}:
            return self.add(a, b)
        if op == "SUB":
            return self.add(a, tuple(map(self.invert, b)), 1)
        if op in ref.ZBA:
            shift = ref.ZBA[op]
            return self.add((0,) * shift + a[: WORD - shift], b)
        if op in {"XOR", "XORI"}:
            return tuple(self.xor(x, y) for x, y in zip(a, b))
        if op in {"AND", "ANDI", "OR", "ORI"}:
            gate = self.and_bits if op.startswith("AND") else self.or_bits
            return tuple(gate((x, y)) for x, y in zip(a, b))
        if op in {"SLT", "SLTI", "SLTU", "SLTIU"}:
            return (self.less(a, b, not op.endswith("U")),) + (0,) * (WORD - 1)
        if op in {"SLL", "SLLI", "SRL", "SRLI", "SRA", "SRAI"} and y is not None:
            shift = y & 31
            if op.startswith("SLL"):
                return (0,) * shift + a[: WORD - shift]
            fill = a[-1] if op.startswith("SRA") else 0
            return a[shift:] + (fill,) * shift
        raise UnsupportedTrace(f"dynamic {op}")

    def memory_word(self, address):
        if address in self.memory:
            return self.memory[address]
        if 0x100 <= address < 0x140:
            start = (address - 0x100) * 8
            word = tuple(
                self.circuit.token_feature(f"input.{i}", lambda token, i=i: (token >> i) & 1, full=True)
                for i in range(start, start + WORD)
            )
        else:
            index = self.machine.ram_index(address)
            value = self.machine.ram[index] if index is not None else self.machine.drom_word(address)
            if value is None:
                raise UnsupportedTrace("load outside RAM and DROM")
            word = bits(value)
        self.memory[address] = word
        return word

    def step(self, record):
        ins = ref.decode(record.word)
        op = ins.op
        a, b = self.registers[ins.rs1], self.registers[ins.rs2]
        value = None
        if op in ref.LOAD_OPS | ref.STORE_OPS:
            address = constant(a)
            if address is None:
                raise UnsupportedTrace("data-dependent memory address")
            address = (address + ins.imm) & MASK
            width = {"B": 1, "H": 2, "W": 4}[op[1]]
            if address % width:
                raise UnsupportedTrace("misaligned memory access")
            offset = (address & 3) * 8
            aligned = address & ~3
            if op in ref.STORE_OPS:
                if self.machine.ram_index(address) is None:
                    raise UnsupportedTrace("store outside RAM")
                old = self.memory_word(aligned) if width != 4 else ()
                self.memory[aligned] = old[:offset] + b[: width * 8] + old[offset + width * 8 :]
            elif ins.rd:
                value = self.memory_word(aligned)[offset : offset + width * 8]
                value += ((value[-1] if op in {"LB", "LH"} else 0),) * (WORD - len(value))
            else:
                if self.machine.ram_index(address) is None and self.machine.drom_word(address) is None:
                    raise UnsupportedTrace("load outside RAM and DROM")
        elif op in ref.BRANCH_OPS:
            if op in {"BEQ", "BNE"}:
                condition = self.equal(a, b)
                if op == "BNE":
                    condition = self.invert(condition)
            else:
                condition = self.less(a, b, not op.endswith("U"))
                if op.startswith("BGE"):
                    condition = self.invert(condition)
            taken = record.next_pc == (record.pc + ins.imm) & MASK
            self.guards.append(condition if taken else self.invert(condition))
        elif op in {"LUI", "AUIPC"}:
            value = bits(ins.imm + (record.pc if op == "AUIPC" else 0))
        elif op in {"JAL", "JALR"}:
            if op == "JALR":
                target = self.add(a, bits(ins.imm))
                self.guards.append(self.equal((0, *target[1:]), bits(record.next_pc)))
            value = bits(record.pc + 4)
        elif op == "ECALL":
            self.guards.append(self.equal(self.registers[17], bits(record.syscall)))
            arg = self.registers[10]
            if record.syscall == 1 and self.output is None:
                self.guards.append(self.invert(arg[8]))
                self.output = arg[:8]
            elif record.syscall == 93 and self.output is not None:
                self.guards.append(self.equal(arg, bits(0)))
            else:
                raise UnsupportedTrace("unsupported syscall sequence")
        elif op in ref.WRITES_RD:
            if ins.rd:
                value = self.alu(op, a, bits(ins.imm) if op in ref.IMM_OPS else b)
        elif op != "FENCE":
            raise UnsupportedTrace(f"instruction {op}")
        if value is not None and ins.rd:
            self.registers[ins.rd] = value

    def compile(self, instructions):
        for record in instructions:
            self.step(record)
            if len(self.circuit.dims) > 4096 or self.circuit.n_layers() > 64:
                raise UnsupportedTrace("circuit exceeds the compilation budget")
        if self.output is None:
            raise UnsupportedTrace("trace did not emit an action")
        guard = self.and_bits(self.guards)
        expressions = [guard, *self.output]
        dims = []
        for value in expressions:
            expr = self.circuit.ffn([(1, value, self.circuit.one)], "result")
            dims.append(next(iter(expr.terms)))
        return self.circuit, dims


class CompiledTrace:
    def __init__(self, circuit, dims, device):
        import torch
        from chipformer.rv.tritonexec import Executor2

        self.executor = Executor2(circuit, 1, device)
        self.x = torch.zeros((1, self.executor.D), device=device)
        self.dims = torch.tensor(dims, device=device)
        self.output = torch.zeros(len(dims), device=device)

        def step():
            self.executor.step(self.x)
            self.output.copy_(self.x[0, self.dims])

        with torch.inference_mode(), torch.cuda.device(device):
            self.graph = capture_cuda_step(torch, device, step)

    def decide(self, packed):
        self.x.copy_(self.executor.embed([packed]))
        self.graph.replay()
        guard, *output = self.output.tolist()
        if guard == 0:
            return None
        if guard != 1 or any(value not in (0, 1) for value in output):
            raise RuntimeError("Non-binary JIT circuit output")
        return sum(int(bit) << i for i, bit in enumerate(output))


class JITController(CircuitController):
    def __init__(self, directory, device="cuda:0", checkpoint=None, *, threshold=2, max_paths=8):
        super().__init__(directory, device, checkpoint)
        if threshold < 1 or max_paths < 1:
            raise ValueError("JIT threshold and cache size must be positive")
        self.threshold, self.max_paths = threshold, max_paths
        self.hotness = Counter()
        self.rejected = set()
        self.paths = []
        self.calls = Counter()
        self.compile_seconds = 0.0
        self.compilations = []

    def decide(self, state, mode=0):
        state = tuple(state)
        packed = pack_state(state, mode)
        with self.torch.inference_mode(), self.torch.cuda.device(self.device):
            for path in self.paths:
                value = path.decide(packed)
                self.calls["guard_checks"] += 1
                if value is not None:
                    self.calls["hits"] += 1
                    return value
            trace = self.trace(state, mode)
            value = trace_action(trace)
            self.calls["generic_calls"] += 1
            self.calls["generic_tokens"] += len(trace)
            if len(self.paths) >= self.max_paths:
                return value
            try:
                key = observe(self.machine(state, mode), trace)
            except UnsupportedTrace:
                self.calls["unsupported_observations"] += 1
                return value
            if key not in self.hotness and len(self.hotness) >= 128:
                return value
            self.hotness[key] += 1
            if self.hotness[key] < self.threshold or key in self.rejected:
                return value
            start = time.perf_counter()
            try:
                circuit, dims = TraceCompiler(self.machine(state, mode)).compile(key)
                candidate = CompiledTrace(circuit, dims, self.device)
                if candidate.decide(packed) != value:
                    raise UnsupportedTrace("compiled circuit disagrees on its training trace")
            except UnsupportedTrace as exc:
                self.rejected.add(key)
                self.compilations.append({"status": "unsupported", "reason": str(exc)})
            else:
                self.paths.append(candidate)
                self.compilations.append({"status": "compiled", "instructions": len(key), **circuit.stats()})
            finally:
                self.compile_seconds += time.perf_counter() - start
            return value

    def statistics(self):
        return {
            **self.calls,
            "compiled_paths": len(self.paths),
            "compile_seconds": self.compile_seconds,
            "compilations": self.compilations,
        }
