"""Pure decoded-instruction tests for the authored keyboard-button wrapper.

No GameAssembly instruction, Unity helper, input API, listener, or game process
executes. Original methods and Unity helpers are synthetic ABI stubs.
"""
from __future__ import annotations

from _research_paths import workspace, output_root, game_path

import argparse
import json
from pathlib import Path
import struct

from capstone import x86

from keyboard_buttons_patch import (ASM, BUTTONS, EXTERNALS, OBJECT_SHA256,
                                    SHA, coff, unwind_summary)
from rapid_boat_offline_tests import IntegerX64

for _name in ["RAX", "RBX", "RCX", "RDX", "RSI", "RDI", "RSP", "RBP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]:
    globals()["REG_" + _name] = getattr(x86, "X86_REG_" + _name)


class KeyboardModel(IntegerX64):
    next_pc = 0

    def __init__(self, original_targets):
        super().__init__(); self.original_targets = original_targets; self.original_stub = None

    def reg_read(self, reg):
        if reg == x86.X86_REG_RIP: return self.next_pc
        return super().reg_read(reg)

    def _register(self, reg):
        if self.md.reg_name(reg) == "dl": return "rdx", 8
        return super()._register(reg)

    def emu_start(self, pc, end, count):
        for _ in range(count):
            if pc == end: return
            if pc in self.original_targets:
                self.original_stub(self, pc)
                pc = self.pop(); continue
            data, off = self._memory(pc, 1)
            ins = next(self.md.disasm(bytes(data[off:off + 15]), pc, count=1))
            args = ins.operands; nxt = pc + ins.size; self.next_pc = nxt; m = ins.mnemonic
            if m == "call":
                target = self.read(args[0]); self.push(nxt)
                try:
                    self._memory(target, 1); pc = target
                except AssertionError:
                    self.hook(self, target, 1, None); pc = self.pop()
                continue
            if m == "ret": pc = self.pop(); continue
            if m == "push": self.push(self.read(args[0]))
            elif m == "pop": self.write(args[0], self.pop())
            elif m in ("mov", "movzx"): self.write(args[0], self.read(args[1]))
            elif m == "lea": self.write(args[0], self.address(args[1]))
            elif m in ("add", "sub", "cmp", "xor", "test"):
                try:
                    a = self.read(args[0]); b = self.read(args[1]); bits = args[0].size * 8
                except AssertionError as error:
                    raise AssertionError((hex(pc), m, ins.op_str)) from error
                value = a - b if m in ("sub", "cmp") else a + b if m == "add" else a ^ b if m == "xor" else a & b
                self.flags(a, b, value, bits, m in ("sub", "cmp"))
                if m in ("xor", "test"): self.o = False
                if m not in ("cmp", "test"): self.write(args[0], value)
            elif m in ("je", "jne", "jmp"):
                take = m == "jmp" or (self.z if m == "je" else not self.z)
                if take: nxt = self.read(args[0])
            elif m != "nop": raise AssertionError(f"Unsupported synthetic instruction {m} {ins.op_str}")
            pc = nxt
        raise AssertionError("Authored wrapper instruction bound exceeded")


def emulate(obj: bytes, button: str, *, original_result=False, blocked=False,
            reset=True, key_result=True, base=0):
    sections, symbols = coff(obj); code = bytearray(sections[".text"][0]); start = base + 0x2E40000
    for off, name, kind in sections[".text"][1]:
        assert kind == 4
        struct.pack_into("<l", code, off, base + EXTERNALS[name] - (start + off + 4))
    unwind_summary(sections[".xdata"][0])
    original_targets = {base + row["rva"] + 5: name for name, row in BUTTONS.items()}
    machine = KeyboardModel(original_targets)
    machine.mem_map(start & ~0xFFF, 0x2000); machine.mem_write(start, code)
    heap = 0x33000000; stack = 0x73000000; sentinel = 0xDEAD3000; this = heap + 0x1000
    machine.mem_map(heap, 0x4000); machine.mem_map(stack, 0x10000); machine.mem_map(sentinel, 0x1000)
    machine.mem_write(this + 0x10, bytes([int(blocked)]))
    rsp = stack + 0xFEF8
    machine.mem_write(rsp, struct.pack("<Q", sentinel))
    method_info = heap + 0x2000
    machine.reg_write(REG_RSP, rsp); machine.reg_write(REG_RCX, this)
    machine.reg_write(REG_RDX, int(reset)); machine.reg_write(REG_R8, method_info)
    saves = {reg: 0x45670000 + index * 0x321 for index, reg in enumerate(
             [REG_RBX, REG_RSI, REG_RDI, REG_R12, REG_R13, REG_R14, REG_R15, REG_RBP])}
    for reg, value in saves.items(): machine.reg_write(reg, value)
    calls = []; original_args = []; helper_args = []
    helper_targets = {base + EXTERNALS["UnityGetKeyDownInt"]: "GetKeyDownInt",
                      base + EXTERNALS["UnityGetKeyInt"]: "GetKeyInt"}

    def original_stub(cpu, address):
        name = original_targets[address]; calls.append("Original" + name)
        assert name == button
        assert cpu.reg_read(REG_RSP) % 16 == 8
        assert struct.unpack("<Q", cpu.mem_read(cpu.reg_read(REG_RSP) + 8, 8))[0] == this
        original_args.append((cpu.reg_read(REG_RCX), cpu.reg_read(REG_RDX), cpu.reg_read(REG_R8)))
        assert original_args[-1] == (this, int(reset), method_info)
        for reg in (REG_RCX, REG_RDX, REG_R8, REG_R9, REG_R10, REG_R11): cpu.reg_write(reg, 0xABCD0000 + reg)
        cpu.reg_write(REG_RAX, int(original_result))

    def helper_stub(cpu, address, size, unused):
        name = helper_targets.get(address)
        if not name: return
        calls.append(name); assert cpu.reg_read(REG_RSP) % 16 == 8
        helper_args.append((cpu.reg_read(REG_RCX), cpu.reg_read(REG_RDX)))
        assert helper_args[-1] == (BUTTONS[button]["keycode"], 0)
        for reg in (REG_RCX, REG_RDX, REG_R8, REG_R9, REG_R10, REG_R11): cpu.reg_write(reg, 0xFADE0000 + reg)
        cpu.reg_write(REG_RAX, int(key_result))

    machine.original_stub = original_stub; machine.hook_add(None, helper_stub)
    stub = start + symbols["Keyboard" + button]["value"]
    machine.emu_start(stub, sentinel, count=1000)
    assert machine.reg_read(REG_RSP) == rsp + 8
    for reg, value in saves.items(): assert machine.reg_read(reg) == value
    expected = bool(original_result or (not blocked and key_result))
    assert bool(machine.reg_read(REG_RAX) & 0xFF) == expected, (button, calls, machine.reg_read(REG_RAX), expected)
    assert calls[0] == "Original" + button
    if original_result or blocked:
        assert len(calls) == 1
    else:
        assert calls[1] == ("GetKeyDownInt" if reset else "GetKeyInt")
    return {"calls": calls, "result": expected, "key": BUTTONS[button]["key"],
            "keycode": BUTTONS[button]["keycode"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(); obj = args.object.read_bytes()
    if SHA(obj) != OBJECT_SHA256: parser.error("COFF object differs from reviewed wrapper")
    report_path = args.report.resolve()
    if report_path.exists() or "steamapps" in [part.lower() for part in report_path.parts]:
        parser.error("Report must be a new path outside steamapps")
    cases = [
        ("controller_true", {"original_result": True, "key_result": False}),
        ("blocked", {"blocked": True, "key_result": True}),
        ("keydown_true", {"reset": True, "key_result": True}),
        ("keydown_false", {"reset": True, "key_result": False}),
        ("held_true", {"reset": False, "key_result": True}),
        ("held_false", {"reset": False, "key_result": False}),
    ]
    results = []
    for base in (0, 0x180000000):
        for button in BUTTONS:
            for case, kwargs in cases:
                result = emulate(obj, button, base=base, **kwargs)
                results.append({"button": button, "case": case, "synthetic_image_base": hex(base),
                                "passed": True, **result})
    report = {
        "format_version": 1,
        "scope": "Pure Python decoded-instruction model of only authored stubs/common wrapper/trampolines with synthetic original/helper ABI stubs.",
        "assembly_source_sha256": SHA(ASM.read_bytes()), "coff_sha256": SHA(obj),
        "tests_passed": len(results), "target_executed": False, "network_used": False,
        "checks": ["all ten entry stubs and keycodes", "original method always first",
                   "original true suppresses keyboard", "blocked controls suppress keyboard",
                   "reset true selects GetKeyDownInt", "reset false selects GetKeyInt",
                   "false and true keyboard results", "original MethodInfo preserved",
                   "Unity helper MethodInfo null", "Win64 call alignment", "volatile-register poisoning",
                   "all used nonvolatile registers preserved", "balanced stack", "two synthetic image bases"],
        "limitations": ["No original GameAssembly or Unity helper instruction executed.",
                        "This does not test physical input, Unity polling, or Windows exception dispatch."],
        "results": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream: stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"tests_passed": len(results), "report": str(report_path), "target_executed": False}))


if __name__ == "__main__": main()
