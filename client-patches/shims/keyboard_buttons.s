/* Exact-build Win64 IL2CPP keyboard fallback for PadPS4 button methods.
 * Entry redirects preserve controller behavior by calling the full original
 * method first. Keyboard is consulted only after an original false result and
 * only while this->isBlockedControls (+0x10) is false.
 */
.text
.p2align 4

.macro BUTTON_STUB name, key
.globl Keyboard\name
.def Keyboard\name; .scl 2; .type 32; .endef
Keyboard\name:
    movl $\key, %r10d
    leaq Original\name(%rip), %r11
    jmp KeyboardButtonCommon
.endm

BUTTON_STUB Cross, 101       /* E */
BUTTON_STUB Circle, 27       /* Escape */
BUTTON_STUB Square, 9        /* Tab */
BUTTON_STUB Triangle, 102    /* F */
BUTTON_STUB L1, 113          /* Q */
BUTTON_STUB R1, 114          /* R */
BUTTON_STUB L3, 304          /* LeftShift */
BUTTON_STUB R3, 99           /* C */
BUTTON_STUB Share, 112       /* P */
BUTTON_STUB Options, 109     /* M */

.p2align 4
.globl KeyboardButtonCommon
.def KeyboardButtonCommon; .scl 2; .type 32; .endef
.seh_proc KeyboardButtonCommon
KeyboardButtonCommon:
    pushq %rbx
    .seh_pushreg %rbx
    pushq %rsi
    .seh_pushreg %rsi
    pushq %rdi
    .seh_pushreg %rdi
    subq $0x30, %rsp
    .seh_stackalloc 0x30
    .seh_endprologue

    movq %rcx, %rbx                 /* PadPS4 this */
    movzbl %dl, %esi                /* _bResetGameKey */
    movl %r10d, %edi                /* fallback Unity KeyCode */
    movq %r8, 0x20(%rsp)            /* original MethodInfo */
    movq %r11, 0x28(%rsp)           /* selected original trampoline */
    movq %rbx, %rcx
    movl %esi, %edx
    movq 0x20(%rsp), %r8
    call *0x28(%rsp)                /* entire original method first */
    testb %al, %al
    jnz .Ltrue
    cmpb $0, 0x10(%rbx)
    jne .Lfalse
    movl %edi, %ecx
    xorl %edx, %edx                 /* Unity Input helper MethodInfo */
    testl %esi, %esi
    jz .Lheld
    call UnityGetKeyDownInt
    jmp .Lnormalize
.Lheld:
    call UnityGetKeyInt
.Lnormalize:
    movzbl %al, %eax
    jmp .Ldone
.Ltrue:
    movl $1, %eax
    jmp .Ldone
.Lfalse:
    xorl %eax, %eax
.Ldone:
    addq $0x30, %rsp
    popq %rdi
    popq %rsi
    popq %rbx
    ret
.seh_endproc

/* Each trampoline reproduces the exact five-byte first instruction from its
 * original entry and then resumes at entry+5. The existing function's own
 * remaining prologue, body, epilogue, and unwind record stay authoritative.
 */
.macro ORIGINAL_TRAMPOLINE name
.p2align 4
Original\name:
    movq %rbx, 8(%rsp)
    jmp Original\name\()Continue
.endm

ORIGINAL_TRAMPOLINE Cross
ORIGINAL_TRAMPOLINE Circle
ORIGINAL_TRAMPOLINE Square
ORIGINAL_TRAMPOLINE Triangle
ORIGINAL_TRAMPOLINE L1
ORIGINAL_TRAMPOLINE R1
ORIGINAL_TRAMPOLINE L3
ORIGINAL_TRAMPOLINE R3
ORIGINAL_TRAMPOLINE Share
ORIGINAL_TRAMPOLINE Options
