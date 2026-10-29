"""Pure-Python instruction-model tests for the authored notification wrapper.

No GameAssembly instruction, DLL, Unity process, listener, socket, or native
helper executes.  Synthetic helper hooks poison volatile registers.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import json
from pathlib import Path
import struct

from capstone import x86

from notification_text_patch import (ASM, OBJECT_SHA256, SHA, TARGETS,
                                     coff_sections, unwind_summary)
from rapid_boat_offline_tests import IntegerX64

for _name in ["RAX", "RBX", "RCX", "RDX", "RSI", "RDI", "RSP", "RBP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]:
    globals()["REG_" + _name] = getattr(x86, "X86_REG_" + _name)


class RipIntegerX64(IntegerX64):
    """The shared integer model plus RIP-relative reads used by this wrapper."""
    next_pc = 0

    def reg_read(self, reg):
        if reg == x86.X86_REG_RIP:
            return self.next_pc
        return super().reg_read(reg)

    def emu_start(self, pc, end, count):
        for _ in range(count):
            if pc == end: return
            data, off = self._memory(pc, 1)
            ins = next(self.md.disasm(bytes(data[off:off + 15]), pc, count=1))
            args = ins.operands; nxt = pc + ins.size; self.next_pc = nxt; m = ins.mnemonic
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
            elif m in ("je", "jne", "jmp"):
                take = m == "jmp" or (self.z if m == "je" else not self.z)
                if take: nxt = self.read(args[0])
            elif m != "nop": raise AssertionError(f"Unsupported synthetic instruction {m} {ins.op_str}")
            pc = nxt
        raise AssertionError("Wrapper instruction bound exceeded")


def emulate(obj: bytes, *, kind=3, body_length=0, has_value=True,
            body_null=False, arguments_null=False, base=0):
    sections = coff_sections(obj)
    code = bytearray(sections[".text"][0]); start = base + 0x2B16000
    for off, name, kind_reloc in sections[".text"][1]:
        assert kind_reloc == 4
        struct.pack_into("<l", code, off, base + TARGETS[name] - (start + off + 4))
    unwind_summary(sections[".xdata"][0])
    machine = RipIntegerX64()
    mapped = set()

    def map_page(address):
        page = address & ~0xFFF
        if page not in mapped:
            machine.mem_map(page, 0x1000); mapped.add(page)

    map_page(start); machine.mem_write(start, code)
    for address in TARGETS.values():
        map_page(base + address)
        if address in (TARGETS["StringConcat3"], TARGETS["StringFormat4"]):
            machine.mem_write(base + address, b"\xc3")
    heap = 0x31000000; stack = 0x71000000; sentinel = 0xDEAD1000
    machine.mem_map(heap, 0x10000); machine.mem_map(stack, 0x10000); machine.mem_map(sentinel, 0x1000)
    entry, empty_body, nonempty_body, argument = [heap + n * 0x1000 for n in range(4)]
    prefix, suffix, reward, colored, timestamp, fmt, concat_result, format_result = [heap + 0x5000 + n * 0x100 for n in range(8)]

    def q(address, value): machine.mem_write(address, struct.pack("<Q", value))
    q(base + TARGETS["GiftPrefixLiteral"], prefix)
    q(base + TARGETS["GiftSuffixLiteral"], suffix)
    q(base + TARGETS["RewardLiteral"], reward)
    machine.mem_write(empty_body + 0x10, struct.pack("<i", 0))
    machine.mem_write(nonempty_body + 0x10, struct.pack("<i", body_length))
    machine.mem_write(entry + 0x108, bytes([int(has_value)]))
    machine.mem_write(entry + 0x110, struct.pack("<i", kind))
    q(entry + 0x130, 0 if arguments_null else argument)
    body = 0 if body_null else (empty_body if body_length == 0 else nonempty_body)
    rsp = stack + 0xFEF8; q(rsp, sentinel); q(rsp + 0x28, 0xBAD5)
    machine.reg_write(REG_RSP, rsp); machine.reg_write(REG_RDI, entry)
    machine.reg_write(REG_RCX, fmt); machine.reg_write(REG_RDX, timestamp)
    machine.reg_write(REG_R8, colored); machine.reg_write(REG_R9, body)
    saves = {reg: 0x76540000 + index * 0x111 for index, reg in enumerate(
             [REG_RBX, REG_RSI, REG_RDI, REG_R12, REG_R13, REG_R14, REG_R15, REG_RBP])}
    saves[REG_RDI] = entry
    for reg, value in saves.items(): machine.reg_write(reg, value)
    calls = []; format_args = []; concat_args = []
    helpers = {base + value: name for name, value in TARGETS.items()
               if name in ("StringConcat3", "StringFormat4")}

    def hook(cpu, address, size, unused):
        name = helpers.get(address)
        if not name: return
        calls.append(name)
        assert cpu.reg_read(REG_RSP) % 16 == 8
        args = tuple(cpu.reg_read(reg) for reg in (REG_RCX, REG_RDX, REG_R8, REG_R9))
        fifth = struct.unpack("<Q", cpu.mem_read(cpu.reg_read(REG_RSP) + 0x28, 8))[0]
        if name == "StringConcat3":
            concat_args.append(args); assert args == (prefix, 0 if arguments_null else argument, suffix, 0)
            result = concat_result
        else:
            format_args.append((*args, fifth)); result = format_result
        for reg in (REG_RCX, REG_RDX, REG_R8, REG_R9, REG_R10, REG_R11):
            cpu.reg_write(reg, 0xFADE0000 + reg)
        cpu.reg_write(REG_RAX, result)

    machine.hook_add(None, hook)
    machine.emu_start(start, sentinel, count=1000)
    assert machine.reg_read(REG_RSP) == rsp + 8
    for reg, value in saves.items(): assert machine.reg_read(reg) == value
    assert machine.reg_read(REG_RAX) == format_result
    return {"calls": calls, "concat_args": concat_args, "format_args": format_args,
            "original_body": body, "gift_body": concat_result, "reward_body": reward}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(); obj = args.object.read_bytes()
    if SHA(obj) != OBJECT_SHA256: parser.error("COFF object hash differs from reviewed wrapper")
    if args.report.resolve().exists() or "steamapps" in [x.lower() for x in args.report.resolve().parts]:
        parser.error("Report must be a new path outside steamapps")
    cases = [
        ("gift_empty", {}, "gift"),
        ("gift_empty_null_arguments", {"arguments_null": True}, "gift"),
        ("reward_empty", {"kind": 4}, "reward"),
        ("gift_nonempty", {"body_length": 5}, "same"),
        ("reward_nonempty", {"kind": 4, "body_length": 5}, "same"),
        ("other_empty", {"kind": 5}, "same"),
        ("gift_no_nullable_value", {"has_value": False}, "same"),
        ("gift_null_body", {"body_null": True}, "same"),
    ]
    results = []
    for base in (0, 0x180000000):
        for name, kwargs, expected in cases:
            result = emulate(obj, base=base, **kwargs)
            assert result["calls"][-1:] == ["StringFormat4"]
            if expected == "gift":
                assert result["calls"] == ["StringConcat3", "StringFormat4"]
                assert result["format_args"][0][3] == result["gift_body"]
            elif expected == "reward":
                assert result["calls"] == ["StringFormat4"]
                assert result["format_args"][0][3] == result["reward_body"]
            else:
                assert result["calls"] == ["StringFormat4"]
                assert result["format_args"][0][3] == result["original_body"]
            assert result["format_args"][0][4] == 0
            results.append({"name": name, "synthetic_image_base": hex(base), "passed": True,
                            "helper_calls": result["calls"]})
    report = {
        "format_version": 1,
        "scope": "Pure Python decoded-instruction model of only the new wrapper with synthetic memory/helper stubs.",
        "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
        "tests_passed": len(results), "target_executed": False, "network_used": False,
        "checks": ["Gift empty-body reconstruction only", "Reward empty-body literal only",
                   "nonempty and other-type pass-through", "nullable-value gate", "null-body pass-through",
                   "Win64 call alignment and shadow/fifth argument", "volatile-register poisoning",
                   "nonvolatile-register preservation", "balanced stack", "two synthetic image bases"],
        "limitations": ["No original game instruction or native helper executed.",
                        "This does not test Unity rendering, IL2CPP GC, or Windows exception dispatch."],
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"tests_passed": len(results), "target_executed": False, "report": str(args.report)}))


if __name__ == "__main__":
    main()
