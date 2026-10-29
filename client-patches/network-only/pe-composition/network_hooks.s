.text
.extern IatPublicGet
.extern IatJoinReady
.extern OriginalProcessTasks
.global PublicGetThunk
.def PublicGetThunk; .scl 2; .type 32; .endef
PublicGetThunk:
    jmp *IatPublicGet(%rip)

# Preserve the original queue owner and EDX=0 tail-call ABI. The unchanged
# networking gate is imported directly, so no automation loader is required.
.p2align 4
.global JoinQueueUpdate
.def JoinQueueUpdate; .scl 2; .type 32; .endef
.seh_proc JoinQueueUpdate
JoinQueueUpdate:
    subq $0x38,%rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq %rcx,0x28(%rsp)
    call *IatJoinReady(%rip)
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
