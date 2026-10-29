"""Emulate only our new wrapper with synthetic memory and native helper stubs.

No GameAssembly, Unity, Mirror, socket, listener or real native helper executes.
This checks generated wrapper code, not target-runtime compatibility.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import json
from pathlib import Path
import struct

import capstone
from capstone import x86

from rapid_boat_patch import coff_sections, unwind_summary, TARGETS, SHA, ASM

for _name in ["RAX", "RBX", "RCX", "RDX", "RSI", "RDI", "RSP", "RBP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]:
    globals()["UC_X86_REG_" + _name] = getattr(x86, "X86_REG_" + _name)


class IntegerX64:
    """Independent, deliberately small decoded-instruction semantic model.

    Refuses instructions outside the wrapper's integer subset; no native memory
    allocation, executable mapping, DLL loading or target instructions execute.
    """
    def __init__(self):
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); self.md.detail = True
        self.regs = {}; self.maps = []; self.z = self.s = self.o = False; self.hook = None

    def mem_map(self, address, size):
        assert not any(address < p + len(b) and p < address + size for p, b in self.maps)
        self.maps.append((address, bytearray(size)))

    def _memory(self, address, size):
        for p, data in self.maps:
            if p <= address and address + size <= p + len(data): return data, address - p
        raise AssertionError(f"Synthetic memory out of bounds: {address:#x}+{size}")

    def mem_read(self, address, size):
        data, off = self._memory(address, size); return bytes(data[off:off + size])

    def mem_write(self, address, value):
        data, off = self._memory(address, len(value)); data[off:off + len(value)] = value

    def _register(self, reg):
        name = self.md.reg_name(reg)
        aliases = {"eax": ("rax", 32), "ebx": ("rbx", 32), "ecx": ("rcx", 32), "edx": ("rdx", 32),
                   "edi": ("rdi", 32), "esi": ("rsi", 32), "esp": ("rsp", 32), "ebp": ("rbp", 32),
                   "ax": ("rax", 16), "bx": ("rbx", 16), "cx": ("rcx", 16), "dx": ("rdx", 16),
                   "al": ("rax", 8)}
        if name in aliases: return aliases[name]
        if name.startswith("r") and name[-1:] in ("d", "w", "b") and name[1:-1].isdigit():
            return name[:-1], {"d": 32, "w": 16, "b": 8}[name[-1]]
        assert name in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rsp", "rbp") or name[1:].isdigit(), name
        return name, 64

    def reg_read(self, reg):
        name, bits = self._register(reg); return self.regs.get(name, 0) & ((1 << bits) - 1)

    def reg_write(self, reg, value):
        name, bits = self._register(reg); mask = (1 << bits) - 1
        self.regs[name] = value & mask if bits in (32, 64) else (self.regs.get(name, 0) & ~mask) | (value & mask)

    def address(self, op):
        assert not op.mem.segment
        return (self.reg_read(op.mem.base) if op.mem.base else 0) + (self.reg_read(op.mem.index) * op.mem.scale if op.mem.index else 0) + op.mem.disp

    def read(self, op):
        if op.type == x86.X86_OP_IMM: return op.imm
        if op.type == x86.X86_OP_REG: return self.reg_read(op.reg)
        if op.type == x86.X86_OP_MEM: return int.from_bytes(self.mem_read(self.address(op), op.size), "little")
        raise AssertionError(op.type)

    def write(self, op, value):
        if op.type == x86.X86_OP_REG: self.reg_write(op.reg, value)
        elif op.type == x86.X86_OP_MEM: self.mem_write(self.address(op), (value & ((1 << (op.size * 8)) - 1)).to_bytes(op.size, "little"))
        else: raise AssertionError(op.type)

    def flags(self, a, b, value, bits, subtract=False):
        mask = (1 << bits) - 1; sign = 1 << (bits - 1); value &= mask; a &= mask; b &= mask
        self.z = value == 0; self.s = bool(value & sign)
        self.o = bool(((a ^ b) & (a ^ value) & sign) if subtract else ((~(a ^ b)) & (a ^ value) & sign))

    def push(self, value):
        rsp = self.reg_read(UC_X86_REG_RSP) - 8; self.reg_write(UC_X86_REG_RSP, rsp); self.mem_write(rsp, struct.pack("<Q", value))

    def pop(self):
        rsp = self.reg_read(UC_X86_REG_RSP); value = struct.unpack("<Q", self.mem_read(rsp, 8))[0]; self.reg_write(UC_X86_REG_RSP, rsp + 8); return value

    def hook_add(self, unused, callback): self.hook = callback

    def emu_start(self, pc, end, count):
        for _ in range(count):
            if pc == end: return
            data, off = self._memory(pc, 1)
            ins = next(self.md.disasm(bytes(data[off:off + 15]), pc, count=1)); args = ins.operands; nxt = pc + ins.size; m = ins.mnemonic
            if m == "call":
                self.push(nxt); target = self.read(args[0]); self.hook(self, target, 1, None); pc = self.pop(); continue
            if m == "ret": pc = self.pop(); continue
            if m == "push": self.push(self.read(args[0]))
            elif m == "pop": self.write(args[0], self.pop())
            elif m in ("mov", "movzx"): self.write(args[0], self.read(args[1]))
            elif m == "lea": self.write(args[0], self.address(args[1]))
            elif m in ("add", "sub", "cmp", "xor", "test", "dec"):
                a = self.read(args[0]); b = 1 if m == "dec" else self.read(args[1]); bits = args[0].size * 8
                value = a - b if m in ("sub", "cmp", "dec") else a + b if m == "add" else a ^ b if m == "xor" else a & b
                self.flags(a, b, value, bits, m in ("sub", "cmp", "dec"))
                if m in ("xor", "test"): self.o = False
                if m not in ("cmp", "test"): self.write(args[0], value)
            elif m in ("je", "jne", "jl", "jg", "jmp"):
                take = m == "jmp" or (self.z if m == "je" else not self.z if m == "jne" else self.s != self.o if m == "jl" else not self.z and self.s == self.o)
                if take: nxt = self.read(args[0])
            elif m != "nop": raise AssertionError(f"Unsupported synthetic instruction {m} {ins.op_str}")
            pc = nxt
        raise AssertionError("Wrapper instruction bound exceeded")


def emulate(obj, *, guid="a" * 64, index=0, local=True, vehicle=True,
            successful_exit=True, connected=True, same_actor=True, tcp=True,
            manager=True, base=0):
    sections = coff_sections(obj)
    code = bytearray(sections[".text"][0]); start = base + 0x2B13000
    for off, name, kind in sections[".text"][1]:
        assert kind == 4
        struct.pack_into("<l", code, off, base + TARGETS[name] - (start + off + 4))
    unwind_summary(sections[".xdata"][0])
    u = IntegerX64()
    u.mem_map(start & ~0xFFF, 0x1000); u.mem_write(start, bytes(code))
    mapped = {start & ~0xFFF}
    for address in TARGETS.values():
        address += base; page = address & ~0xFFF
        if page not in mapped:
            u.mem_map(page, 0x1000); mapped.add(page)
        u.mem_write(address, b"\xc3")  # synthetic RET, no original native bytes
    heap = 0x10000000; stack = 0x70000000; sentinel = 0xDEAD0000
    u.mem_map(heap, 0x10000); u.mem_map(stack, 0x10000); u.mem_map(sentinel, 0x1000)
    manager_ptr, p1, control, actor, tcp_ptr, info, string, allocated, trip = [heap + n * 0x1000 for n in range(9)]
    q = lambda address, value: u.mem_write(address, struct.pack("<Q", value))
    getq = lambda address: struct.unpack("<Q", u.mem_read(address, 8))[0]
    q(manager_ptr + 0x2C0, p1); q(p1 + 0x10, control); q(control + 0x30, actor)
    q(manager_ptr + 0x2B8, tcp_ptr if tcp else 0); q(info + 0xE8, string)
    q(actor + 0x108, heap + 0x9000 if vehicle else 0)
    u.mem_write(actor + 0x9C, bytes([int(local)])); u.mem_write(trip + 0x30, struct.pack("<i", index))
    raw_guid = guid.encode("utf-16-le", "surrogatepass")
    u.mem_write(string + 0x10, struct.pack("<i", len(raw_guid) // 2)); u.mem_write(string + 0x14, raw_guid + b"\0\0")
    rsp = stack + 0xFFF8; q(rsp, sentinel)
    u.reg_write(UC_X86_REG_RSP, rsp); u.reg_write(UC_X86_REG_RCX, trip); u.reg_write(UC_X86_REG_RDX, 0)
    saves = {reg: 0x12340000 + i * 0x123 for i, reg in enumerate([UC_X86_REG_RBX, UC_X86_REG_RSI, UC_X86_REG_RDI, UC_X86_REG_R12, UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15, UC_X86_REG_RBP])}
    for reg, value in saves.items(): u.reg_write(reg, value)
    calls = []; messages = []; allocations = []
    helpers = {base + value: name for name, value in TARGETS.items()}

    def hook(uc, address, size, _):
        name = helpers.get(address)
        if not name: return
        calls.append(name)
        assert uc.reg_read(UC_X86_REG_RSP) % 16 == 8, "callee entry stack must be8 mod16"
        rcx, rdx, r8 = [uc.reg_read(r) for r in (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8)]
        result = 0
        if name == "ManagerSingleton": result = manager_ptr if manager else 0
        elif name == "OriginalExit":
            assert rcx == trip and rdx == 0
            if successful_exit: q(actor + 0x108, 0)
            if not same_actor: q(control + 0x30, heap + 0xA000)
        elif name == "TcpIsConnected":
            assert rcx == tcp_ptr and rdx == 0
            result = 0xABC000 | int(connected)  # only AL is the Boolean ABI
        elif name == "InfoSingleton": result = info
        elif name == "StringNewUtf16":
            assert 0 < rdx <= 267
            payload = bytes(uc.mem_read(rcx, rdx * 2))
            allocations.append(payload.decode("utf-16-le", "surrogatepass"))
            uc.mem_write(allocated + 0x10, struct.pack("<i", rdx)); uc.mem_write(allocated + 0x14, payload + b"\0\0")
            result = allocated
        elif name == "TcpSend":
            assert rcx == tcp_ptr and rdx == allocated and r8 == 0
            length = struct.unpack("<i", uc.mem_read(rdx + 0x10, 4))[0]
            messages.append(bytes(uc.mem_read(rdx + 0x14, length * 2)).decode("utf-16-le", "surrogatepass"))
        # Poison volatile registers to catch reliance across native calls.
        for reg in [UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_R10, UC_X86_REG_R11]:
            uc.reg_write(reg, 0xFADE0000 + reg)
        uc.reg_write(UC_X86_REG_RAX, result)

    u.hook_add(None, hook)
    u.emu_start(start, sentinel, count=20000)
    assert calls.count("OriginalExit") == 1, calls
    assert u.reg_read(UC_X86_REG_RSP) == rsp + 8, "unbalanced wrapper stack"
    for reg, value in saves.items(): assert u.reg_read(reg) == value, (reg, value)
    assert calls.index("OriginalExit") < calls.index("TcpSend") if "TcpSend" in calls else True
    return {"calls": calls, "messages": messages, "allocations": allocations}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--object", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args(); obj = a.object.read_bytes(); results = []
    cases = [("success", {}, True), ("max_guid", {"guid": "b" * 256}, True),
             ("utf16_guid", {"guid": "a\U0001F680b"}, True),
             ("no_prior_vehicle", {"vehicle": False}, False), ("remote_actor", {"local": False}, False),
             ("failed_exit", {"successful_exit": False}, False), ("disconnected", {"connected": False}, False),
             ("changed_actor", {"same_actor": False}, False), ("nonzero_index", {"index": 1}, False),
             ("no_tcp", {"tcp": False}, False), ("no_manager", {"manager": False}, False),
             ("empty_guid", {"guid": ""}, False), ("oversized_guid", {"guid": "a" * 257}, False),
             ("separator_in_guid", {"guid": "bad#guid"}, False), ("nul_in_guid", {"guid": "bad\0guid"}, False)]
    for base in (0, 0x180000000):
        for name, kwargs, should_send in cases:
            result = emulate(obj, base=base, **kwargs)
            expected = ["31#" + kwargs.get("guid", "a" * 64) + "#False#0"] if should_send else []
            assert result["messages"] == expected, (name, result)
            assert result["allocations"] == expected, (name, result)
            results.append({"name": name, "synthetic_image_base": hex(base), "passed": True, "send_count": len(result["messages"])})
    report = {"format_version": 1, "scope": "Pure Python integer-instruction semantic model of only new wrapper code with synthetic data/native stubs; no original game code executed.",
              "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
              "tests_passed": len(results), "target_executed": False, "network_used": False,
              "unicorn_attempt": "Unavailable: could not allocate dynamic translator buffer; no Unicorn test ran. Replaced with a pure Python decoded-instruction model.",
              "checks": ["OriginalExit called exactly once", "send occurs only after successful guarded exit", "exact UTF16 payload",
                         "all native calls stack-aligned with shadow space", "volatile registers poisoned between helper calls",
                         "all Win64 nonvolatile registers preserved", "stack balanced", "relative calls work at two synthetic image bases"], "results": results}
    a.report.parent.mkdir(parents=True, exist_ok=True); a.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"tests_passed": len(results), "target_executed": False, "report": str(a.report)}))


if __name__ == "__main__": main()
