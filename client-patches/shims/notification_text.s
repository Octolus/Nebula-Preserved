/* Same-build Win64 IL2CPP notification-text compatibility wrapper.
 * Intercepts only ChatEntry.set_notification's final String.Format call.
 * If and only if its body is an empty managed string and the copied nullable
 * notification is Gift(3) or Reward(4), reconstruct the body from the same
 * literal slots used by the original setter. All other calls pass through.
 */
.text
.p2align 4
.globl NotificationTextFormat
.def NotificationTextFormat; .scl 2; .type 32; .endef
.seh_proc NotificationTextFormat
NotificationTextFormat:
    pushq %rbx
    .seh_pushreg %rbx
    pushq %rsi
    .seh_pushreg %rsi
    pushq %rdi
    .seh_pushreg %rdi
    pushq %r12
    .seh_pushreg %r12
    pushq %r13
    .seh_pushreg %r13
    subq $0x30, %rsp
    .seh_stackalloc 0x30
    .seh_endprologue

    movq %rcx, %rbx                 /* original format */
    movq %rdx, %rsi                 /* original timestamp */
    movq %r8, %r12                  /* original colored player name */
    movq %r9, %r13                  /* original body */
    testq %r13, %r13
    jz .Lformat
    cmpl $0, 0x10(%r13)             /* Il2CppString.length */
    jne .Lformat
    testq %rdi, %rdi                /* caller keeps ChatEntry in RDI */
    jz .Lformat
    cmpb $0, 0x108(%rdi)            /* Nullable<T>.HasValue */
    je .Lformat
    movl 0x110(%rdi), %eax          /* NotificationData.type */
    cmpl $3, %eax
    je .Lgift
    cmpl $4, %eax
    jne .Lformat
    movq RewardLiteral(%rip), %r13
    jmp .Lformat

.Lgift:
    movq GiftPrefixLiteral(%rip), %rcx
    movq 0x130(%rdi), %rdx          /* NotificationData.arguments */
    movq GiftSuffixLiteral(%rip), %r8
    xorl %r9d, %r9d                 /* MethodInfo */
    call StringConcat3
    movq %rax, %r13

.Lformat:
    movq %rbx, %rcx
    movq %rsi, %rdx
    movq %r12, %r8
    movq %r13, %r9
    movq $0, 0x20(%rsp)             /* String.Format MethodInfo */
    call StringFormat4
    addq $0x30, %rsp
    popq %r13
    popq %r12
    popq %rdi
    popq %rsi
    popq %rbx
    ret
.seh_endproc
