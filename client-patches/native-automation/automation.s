.text
.p2align 4
.extern OriginalSteamUpdate
.extern IatGetEnvironmentVariableW
.extern IatGetModuleHandleW
.extern IatGetModuleFileNameW
.extern IatLoadLibraryExW
.extern IatGetProcAddress

# Original PS4Info.Update is a leaf: manager=this+238, manager?.Update().
# The original callback always runs first, including automation-disabled mode.
.global AutomationUpdate
.def AutomationUpdate; .scl 2; .type 32; .endef
.seh_proc AutomationUpdate
AutomationUpdate:
    subq $0x38,%rsp
    .seh_stackalloc 0x38
    .seh_endprologue
    movq %rcx,0x28(%rsp)
    movq 0x238(%rcx),%rcx
    testq %rcx,%rcx
    jz .Lafter_original
    xorl %edx,%edx
    call OriginalSteamUpdate
.Lafter_original:
    leaq ModeName(%rip),%rcx
    leaq 0x20(%rsp),%rdx
    movl $4,%r8d
    call *IatGetEnvironmentVariableW(%rip)
    cmpl $1,%eax
    jne .Lupdate_done
    cmpw $'1',0x20(%rsp)
    jne .Lupdate_done
    cmpw $0,0x22(%rsp)
    jne .Lupdate_done
    call AutomationResolve
    testq %rax,%rax
    jz .Lupdate_done
    movq 0x28(%rsp),%rcx
    call *%rax
.Lupdate_done:
    addq $0x38,%rsp
    ret
.seh_endproc

.p2align 4
.global AutomationResolve
.def AutomationResolve; .scl 2; .type 32; .endef
.seh_proc AutomationResolve
AutomationResolve:
    subq $0x438,%rsp
    .seh_stackalloc 0x438
    .seh_endprologue
    leaq GameName(%rip),%rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax,%rax
    jz .Lresolve_fail
    movq %rax,%rcx
    leaq 0x20(%rsp),%rdx
    movl $520,%r8d
    call *IatGetModuleFileNameW(%rip)
    testl %eax,%eax
    jz .Lresolve_fail
    cmpl $520,%eax
    jae .Lresolve_fail
    leaq 0x20(%rsp),%rcx
    leaq (%rcx,%rax,2),%rdx
.Lscan:
    cmpq %rcx,%rdx
    jbe .Lresolve_fail
    subq $2,%rdx
    cmpw $'\\',(%rdx)
    je .Lfound
    cmpw $'/',(%rdx)
    jne .Lscan
.Lfound:
    addq $2,%rdx
    movq %rdx,%rax
    subq %rcx,%rax
    shrq $1,%rax
    cmpq $499,%rax # 20-character basename +NUL, capacity520 WCHARs
    ja .Lresolve_fail
    leaq HelperName(%rip),%rax
.Lcopy:
    movw (%rax),%cx
    movw %cx,(%rdx)
    addq $2,%rax
    addq $2,%rdx
    testw %cx,%cx
    jne .Lcopy
    # Absolute-path lookup does not increment the module reference every frame.
    leaq 0x20(%rsp),%rcx
    call *IatGetModuleHandleW(%rip)
    testq %rax,%rax
    jnz .Lloaded
    leaq 0x20(%rsp),%rcx
    xorl %edx,%edx
    movl $0x900,%r8d # LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | SYSTEM32
    call *IatLoadLibraryExW(%rip)
    testq %rax,%rax
    jz .Lresolve_fail
.Lloaded:
    movq %rax,%rcx
    leaq PumpName(%rip),%rdx
    call *IatGetProcAddress(%rip)
    jmp .Lresolve_done
.Lresolve_fail:
    xorl %eax,%eax
.Lresolve_done:
    addq $0x438,%rsp
    ret
.seh_endproc

.p2align 1
ModeName: .short 'N','E','B','U','L','A','_','A','U','T','O','M','A','T','I','O','N',0
GameName: .short 'G','a','m','e','A','s','s','e','m','b','l','y','.','d','l','l',0
HelperName: .short 'N','e','b','u','l','a','A','u','t','o','m','a','t','i','o','n','.','d','l','l',0
PumpName: .asciz "NebulaAutomation_Pump"
