.text
.extern OriginalVertical
.extern OriginalHorizontal
.extern IatGetModuleHandleW
.extern IatGetProcAddress

# Only these four movement callsites are redirected. RBX retains the shipped
# NebulaPlayerControl* at all four sites. Never modify RBX or hook getters globally.
# The original getter always executes first with original RCX/RDX.
.macro AXIS name,original,site
.p2align 4
.global \name
.def \name; .scl 2; .type 32; .endef
.seh_proc \name
\name:
    subq $0x48,%rsp
    .seh_stackalloc 0x48
    .seh_endprologue
    movq %rcx,0x20(%rsp)
    call \original
    movd %xmm0,0x28(%rsp)
    leaq HelperName(%rip),%rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax,%rax
    jz .Loriginal\@
    movq %rax,%rcx
    leaq AxisName(%rip),%rdx
    call *IatGetProcAddress(%rip)
    testq %rax,%rax
    jz .Loriginal\@
    movq %rbx,%rcx
    movq 0x20(%rsp),%rdx
    movl $\site,%r8d
    movl 0x28(%rsp),%r9d
    # uint32_t callback(Control*,PadPS4*,uint32_t site,uint32_t original_bits)
    call *%rax
    movd %eax,%xmm0
    jmp .Ldone\@
.Loriginal\@:
    movd 0x28(%rsp),%xmm0
.Ldone\@:
    addq $0x48,%rsp
    ret
.seh_endproc
.endm

AXIS MovementMoveV,OriginalVertical,0
AXIS MovementMoveH,OriginalHorizontal,1
AXIS MovementRotateV,OriginalVertical,2
AXIS MovementRotateH,OriginalHorizontal,3
.p2align 1
HelperName: .short 'N','e','b','u','l','a','A','u','t','o','m','a','t','i','o','n','.','d','l','l',0
AxisName: .asciz "NebulaAutomation_MovementAxis"
