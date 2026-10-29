/* Same-build Win64 IL2CPP compatibility wrapper; never a standalone program.
 * Calls only the exact native RVAs declared in rapid_boat_patch.py.
 * Executed only if a future user starts a separately prepared client copy.
 * No imported function, absolute pointer, external loader or code cave.
 */
.text
.p2align 4
.globl RapidBoatExitWithReport
.def RapidBoatExitWithReport; .scl 2; .type 32; .endef
.seh_proc RapidBoatExitWithReport
RapidBoatExitWithReport:
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
    subq $0x300, %rsp
    .seh_stackalloc 0x300
    .seh_endprologue

    movq %rcx, %rbx                 /* BoatTripManager this */
    xorl %r12d, %r12d               /* eligible pre-exit vehicle */
    xorl %edi, %edi                 /* previous actor identity only */
    testq %rbx, %rbx
    jz .Loriginal
    cmpl $0, 0x30(%rbx)             /* verified shipped rapid index0 */
    jne .Loriginal
    xorl %ecx, %ecx
    call ManagerSingleton
    testq %rax, %rax
    jz .Loriginal
    movq 0x2c0(%rax), %rax
    testq %rax, %rax
    jz .Loriginal
    movq 0x10(%rax), %rax
    testq %rax, %rax
    jz .Loriginal
    movq 0x30(%rax), %rdi           /* rooted local NebulaPlayer */
    testq %rdi, %rdi
    jz .Loriginal
    cmpb $0, 0x9c(%rdi)
    je .Loriginal
    cmpq $0, 0x108(%rdi)
    je .Loriginal
    movl $1, %r12d
.Loriginal:
    movq %rbx, %rcx
    xorl %edx, %edx                 /* original MethodInfo=null */
    call OriginalExit               /* exactly once on every path */
    testl %r12d, %r12d
    jz .Ldone

    /* Re-read the rooted current actor; never dereference a saved actor
       pointer after the native exit. Identity changes fail closed. */
    xorl %ecx, %ecx
    call ManagerSingleton
    testq %rax, %rax
    jz .Ldone
    movq 0x2b8(%rax), %rsi           /* current TCPClient */
    testq %rsi, %rsi
    jz .Ldone
    movq 0x2c0(%rax), %rax
    testq %rax, %rax
    jz .Ldone
    movq 0x10(%rax), %rax
    testq %rax, %rax
    jz .Ldone
    movq 0x30(%rax), %rax
    cmpq %rdi, %rax
    jne .Ldone
    testq %rax, %rax
    jz .Ldone
    cmpb $0, 0x9c(%rax)
    je .Ldone
    cmpq $0, 0x108(%rax)             /* native exit actually cleared vehicle */
    jne .Ldone
    movq %rsi, %rcx
    xorl %edx, %edx
    call TcpIsConnected
    testb %al, %al
    jz .Ldone
    xorl %ecx, %ecx
    call InfoSingleton
    testq %rax, %rax
    jz .Ldone
    movq 0xe8(%rax), %rax           /* immutable session GUID string */
    testq %rax, %rax
    jz .Ldone
    movl 0x10(%rax), %r13d          /* Il2CppString.length */
    cmpl $1, %r13d
    jl .Ldone
    cmpl $256, %r13d
    jg .Ldone

    /* 32-byte Win64 outgoing shadow space remains at rsp+0..31.
       Bounded stack UTF16 buffer: 3+256+8 chars <= 534 bytes. */
    movw $0x33, 0x80(%rsp)
    movw $0x31, 0x82(%rsp)
    movw $0x23, 0x84(%rsp)
    leaq 0x14(%rax), %r9
    leaq 0x86(%rsp), %r10
    movl %r13d, %ecx
.Lcopy:
    movzwl (%r9), %edx
    cmpl $0x23, %edx                /* no token injection */
    je .Ldone
    testl %edx, %edx
    jz .Ldone
    movw %dx, (%r10)
    addq $2, %r9
    addq $2, %r10
    decl %ecx
    jnz .Lcopy
    movw $0x23, 0(%r10)
    movw $0x46, 2(%r10)
    movw $0x61, 4(%r10)
    movw $0x6c, 6(%r10)
    movw $0x73, 8(%r10)
    movw $0x65, 10(%r10)
    movw $0x23, 12(%r10)
    movw $0x30, 14(%r10)
    leaq 0x80(%rsp), %rcx
    leal 11(%r13), %edx
    call StringNewUtf16              /* IL2CPP owns copied immutable string */
    testq %rax, %rax
    jz .Ldone
    movq %rsi, %rcx
    movq %rax, %rdx                 /* managed argument passed directly */
    xorl %r8d, %r8d
    call TcpSend
.Ldone:
    addq $0x300, %rsp
    popq %r13
    popq %r12
    popq %rdi
    popq %rsi
    popq %rbx
    ret
.seh_endproc
