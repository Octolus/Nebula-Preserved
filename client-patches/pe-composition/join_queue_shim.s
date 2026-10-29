.text
.p2align 4
.extern IatGetModuleHandleW
.extern IatGetProcAddress
.extern OriginalProcessTasks

# Original Update is exactly xor edx,edx; jmp ProcessTasks. Preserve that
# untouched callee and its exception behavior by tail-calling after the gate.
.global JoinQueueUpdate
.def JoinQueueUpdate; .scl 2; .type 32; .endef
.seh_proc JoinQueueUpdate
JoinQueueUpdate:
    subq $0x38,%rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq %rcx,0x28(%rsp)
    leaq HelperName(%rip),%rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax,%rax
    jz .Ldone
    movq %rax,%rcx
    leaq GateName(%rip),%rdx
    call *IatGetProcAddress(%rip)
    testq %rax,%rax
    jz .Ldone
    movq 0x28(%rsp),%rcx
    call *%rax
    cmpl $1,%eax
    jne .Ldone
    movq 0x28(%rsp),%rcx
    xorl %edx,%edx
    addq $0x38,%rsp
    jmp OriginalProcessTasks
.Ldone:
    addq $0x38,%rsp
    ret
.seh_endproc

.p2align 1
HelperName: .short 'N','e','b','u','l','a','A','u','t','o','m','a','t','i','o','n','.','d','l','l',0
GateName: .asciz "NebulaAutomation_JoinQueueReady"
