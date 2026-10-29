.text
.p2align 4

.extern OriginalOccupableInitialize
.extern OriginalGenericInitialize
.extern OriginalInitialSetResult
.extern OriginalSavePreset
.extern OriginalFindObjects
.extern OriginalLoadAfterPrologue
.extern IatLoadLibraryExW
.extern IatGetProcAddress
.extern IatGetModuleHandleW
.extern IatGetModuleFileNameW

# RCX = ASCII export name. Returns RAX = function pointer or zero.
.global BridgeResolve
.def BridgeResolve; .scl 2; .type 32; .endef
.seh_proc BridgeResolve
BridgeResolve:
    pushq %rbx
    .seh_pushreg %rbx
    pushq %rsi
    .seh_pushreg %rsi
    pushq %rdi
    .seh_pushreg %rdi
    subq $0x470, %rsp
    .seh_stackalloc 0x470
    .seh_endprologue
    movq %rcx, %rbx
    leaq GameAssemblyName(%rip), %rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax, %rax
    jz .Lresolve_fail
    movq %rax, %rdi
    movq %rax, %rcx
    leaq 0x20(%rsp), %rdx
    movl $520, %r8d
    call *IatGetModuleFileNameW(%rip)
    testl %eax, %eax
    jz .Lresolve_fail
    cmpl $520, %eax
    jae .Lresolve_fail
    leaq 0x20(%rsp), %rcx
    leaq (%rcx,%rax,2), %rdx
.Lpath_scan:
    cmpq %rcx, %rdx
    jbe .Lresolve_fail
    subq $2, %rdx
    cmpw $'\\', (%rdx)
    je .Lpath_found
    cmpw $'/', (%rdx)
    jne .Lpath_scan
.Lpath_found:
    addq $2, %rdx
    movq %rdx, %rax
    subq %rcx, %rax
    shrq $1, %rax
    cmpq $495, %rax # 24-char basename plus terminator must fit 520 WCHARs
    ja .Lresolve_fail
    leaq DllName(%rip), %rax
.Lpath_copy:
    movw (%rax), %cx
    movw %cx, (%rdx)
    addq $2, %rax
    addq $2, %rdx
    testw %cx, %cx
    jne .Lpath_copy
    leaq 0x20(%rsp), %rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax, %rax
    jnz .Lmodule_ready
    leaq 0x20(%rsp), %rcx
    xorl %edx, %edx
    movl $0x900, %r8d
    call *IatLoadLibraryExW(%rip)
    testq %rax, %rax
    jz .Lresolve_fail
.Lmodule_ready:
    movq %rax, %rsi
    movl $48, 0x430(%rsp)
    movl $1, 0x434(%rsp)
    movq %rdi, 0x438(%rsp)
    movabsq $0x895cf33a9d906fec, %rax
    movq %rax, 0x440(%rsp)
    movabsq $0x3968b803287a28cd, %rax
    movq %rax, 0x448(%rsp)
    movabsq $0x65f7c18b161b5dcd, %rax
    movq %rax, 0x450(%rsp)
    movabsq $0x1be0854c49d2ee17, %rax
    movq %rax, 0x458(%rsp)
    movq %rsi, %rcx
    leaq InitializeName(%rip), %rdx
    call *IatGetProcAddress(%rip)
    testq %rax, %rax
    jz .Lresolve_fail
    leaq 0x430(%rsp), %rcx
    call *%rax
    testl %eax, %eax
    jz .Lresolve_fail
    movq %rsi, %rcx
    movq %rbx, %rdx
    call *IatGetProcAddress(%rip)
    jmp .Lresolve_done
.Lresolve_fail:
    xorl %eax, %eax
.Lresolve_done:
    addq $0x470, %rsp
    popq %rdi
    popq %rsi
    popq %rbx
    ret
.seh_endproc

.macro RECORD_WRAPPER name, original, kind, source, owner_mode
.global \name
.def \name; .scl 2; .type 32; .endef
.seh_proc \name
\name:
    subq $0x58, %rsp
    .seh_stackalloc 0x58
    .seh_endprologue
    movq %rcx, 0x40(%rsp)
.ifc \owner_mode,save
    movq %rbx, 0x48(%rsp)
.else
.ifc \owner_mode,load
    movq 0x10(%r13), %rax
    movq %rax, 0x48(%rsp)
.else
    movq $0, 0x48(%rsp)
.endif
.endif
    call \original
    movq 0x40(%rsp), %rcx
    movq (%rcx), %rax
    movq 0x190(%rax), %rdx
    call *0x188(%rax)
    movl %eax, 0x38(%rsp)
    leaq RecordName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movq 0x48(%rsp), %rcx
    movq %rcx, 0x20(%rsp)
    movq 0x40(%rsp), %rcx
    movl $\kind, %edx
    movl $\source, %r8d
    movl 0x38(%rsp), %r9d
    call *%rax
1:
    addq $0x58, %rsp
    ret
.seh_endproc
.endm

.macro BEGIN_SCAN_WRAPPER name, source, owner_mode
.global \name
.def \name; .scl 2; .type 32; .endef
.seh_proc \name
\name:
    subq $0x38, %rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq %rcx, 0x28(%rsp)
.ifc \owner_mode,save
    movq %rbx, 0x30(%rsp)
.else
    movq $0, 0x30(%rsp)
.endif
    leaq BeginName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movl $\source, %ecx
    movq 0x30(%rsp), %rdx
    call *%rax
1:
    movq 0x28(%rsp), %rcx
    call OriginalFindObjects
    addq $0x38, %rsp
    ret
.seh_endproc
.endm

BEGIN_SCAN_WRAPPER BeginInitialScan, 1, initial
BEGIN_SCAN_WRAPPER BeginSaveScan, 2, save

.global BeginLoad
.def BeginLoad; .scl 2; .type 32; .endef
.seh_proc BeginLoad
BeginLoad:
    movq %rbx, 8(%rsp)
    subq $0x58, %rsp
    .seh_stackalloc 0x58
    .seh_endprologue
    movq %rcx, 0x28(%rsp)
    movq %rdx, 0x30(%rsp)
    movq %r8, 0x38(%rsp)
    movq %r9, 0x40(%rsp)
    leaq BeginName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movl $3, %ecx
    movq 0x28(%rsp), %rdx
    call *%rax
1:
    movq 0x28(%rsp), %rcx
    movq 0x30(%rsp), %rdx
    movq 0x38(%rsp), %r8
    movq 0x40(%rsp), %r9
    addq $0x58, %rsp
    jmp OriginalLoadAfterPrologue
.seh_endproc

RECORD_WRAPPER RecordInitialOccupable, OriginalOccupableInitialize, 2, 1, initial
RECORD_WRAPPER RecordInitialGeneric, OriginalGenericInitialize, 1, 1, initial
RECORD_WRAPPER RecordSaveOccupable, OriginalOccupableInitialize, 2, 2, save
RECORD_WRAPPER RecordSaveGeneric, OriginalGenericInitialize, 1, 2, save
RECORD_WRAPPER RecordLoadOccupable, OriginalOccupableInitialize, 2, 3, load
RECORD_WRAPPER RecordLoadGeneric, OriginalGenericInitialize, 1, 3, load

.global CommitInitial
.def CommitInitial; .scl 2; .type 32; .endef
.seh_proc CommitInitial
CommitInitial:
    subq $0x38, %rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq %rcx, 0x28(%rsp)
    movq %rdx, 0x30(%rsp)
    leaq CommitName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movl $1, %ecx
    xorl %edx, %edx
    call *%rax
1:
    movq 0x28(%rsp), %rcx
    movq 0x30(%rsp), %rdx
    call OriginalInitialSetResult
    addq $0x38, %rsp
    ret
.seh_endproc

.global CommitSave
.def CommitSave; .scl 2; .type 32; .endef
.seh_proc CommitSave
CommitSave:
    subq $0x68, %rsp
    .seh_stackalloc 0x68
    .seh_endprologue
    movq %rcx, 0x40(%rsp)
    movq %rdx, 0x48(%rsp)
    movq %r8, 0x50(%rsp)
    movq %rbx, 0x58(%rsp)
    leaq CaptureSaveName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movq 0x48(%rsp), %rcx
    movq 0x58(%rsp), %rdx
    call *%rax
1:
    movq 0x40(%rsp), %rcx
    movq 0x48(%rsp), %rdx
    movq 0x50(%rsp), %r8
    call OriginalSavePreset
    leaq CommitName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 2f
    movl $2, %ecx
    movq 0x58(%rsp), %rdx
    call *%rax
2:
    addq $0x68, %rsp
    ret
.seh_endproc

# Replaces: mov rdx,[rax+28]; mov rcx,[rax+40]; call [rax+18].
.global CommitLoad
.def CommitLoad; .scl 2; .type 32; .endef
.seh_proc CommitLoad
CommitLoad:
    subq $0x38, %rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq 0x28(%rax), %rdx
    movq 0x40(%rax), %rcx
    call *0x18(%rax)
    leaq CommitName(%rip), %rcx
    call BridgeResolve
    testq %rax, %rax
    jz 1f
    movl $3, %ecx
    movq %r15, %rdx
    call *%rax
1:
    addq $0x38, %rsp
    ret
.seh_endproc

.p2align 1
DllName:
    .short 'N','e','b','u','l','a','R','e','g','i','s','t','r','y','B','r','i','d','g','e','.','d','l','l',0
GameAssemblyName:
    .short 'G','a','m','e','A','s','s','e','m','b','l','y','.','d','l','l',0
InitializeName:
    .asciz "NebulaRegistry_Initialize"
BeginName:
    .asciz "NebulaRegistry_Begin"
RecordName:
    .asciz "NebulaRegistry_Record"
CaptureSaveName:
    .asciz "NebulaRegistry_CaptureSave"
CommitName:
    .asciz "NebulaRegistry_Commit"
