//! No credential command-line value, no plaintext logging, no Steam ownership override.
use anyhow::{ensure, Context, Result};
use std::path::Path;
pub fn reset() -> Result<()> {
    crate::discovery::stopped()?;
    let base =
        std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA missing")?);
    let folder = crate::manifest::safe(&base, "NebulaPreservation")?;
    if !folder.exists() {
        println!("No provisioner configuration exists.");
        return Ok(());
    }
    let config = crate::manifest::safe(&folder, "public-access.conf")?;
    let token = crate::manifest::safe(&folder, "account-token.dpapi")?;
    if token.exists() {
        let bytes = crate::manifest::read_bounded(&token, 65536)?;
        ensure!(
            bytes.len() >= 8
                && bytes.len() <= 65536
                && bytes.starts_with(b"NPA1")
                && u32::from_le_bytes(bytes[4..8].try_into()?) as usize == bytes.len() - 8,
            "Refusing unknown protected-token file"
        );
    }
    if config.exists() {
        let bytes = crate::manifest::read_bounded(&config, 4096)?;
        ensure!(bytes.len() <= 4096, "Refusing unknown oversized config");
    }
    if config.exists() {
        std::fs::remove_file(config)?
    }
    if token.exists() {
        std::fs::remove_file(token)?
    }
    println!("Removed only fixed public-access config and provisioner DPAPI token. Other files retained.");
    Ok(())
}
#[cfg(windows)]
pub(crate) fn restrict(path: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::{
            Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW, SetFileSecurityW,
            DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION,
        },
    };
    // OW is the current object's owner; SYSTEM retains recovery access. No inherited grants.
    let sddl: Vec<u16> = "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)"
        .encode_utf16()
        .chain(Some(0))
        .collect();
    let mut descriptor = std::ptr::null_mut();
    ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                1,
                &mut descriptor,
                std::ptr::null_mut(),
            )
        } != 0,
        "Cannot build private ACL"
    );
    let path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let result = unsafe {
        SetFileSecurityW(
            path.as_ptr(),
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            descriptor,
        )
    };
    unsafe {
        LocalFree(descriptor);
    }
    ensure!(result != 0, "Cannot restrict private configuration ACL");
    Ok(())
}
pub fn configure(server: &str, authorization_file: &Path) -> Result<()> {
    crate::discovery::stopped()?;
    crate::endpoint::validate(server, "127.0.0.1")?;
    ensure!(
        server.starts_with("https://"),
        "Public access requires HTTPS"
    );
    #[cfg(windows)]
    {
        use windows_sys::Win32::{
            Foundation::LocalFree,
            Security::Cryptography::{
                CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
            },
        };
        use zeroize::Zeroizing;
        crate::manifest::reject_link(authorization_file)?;
        let bytes = Zeroizing::new(
            crate::manifest::read_bounded(authorization_file, 85)
                .context("Read administrator-issued credential file")?,
        );
        let b64 = |b: &u8| b.is_ascii_alphanumeric() || *b == b'-' || *b == b'_';
        ensure!(
            bytes.len() == 85
                && bytes.starts_with(b"Nebula-Account-v1 ")
                && bytes[18..41].iter().all(b64)
                && bytes[41] == b'.'
                && bytes[42..].iter().all(b64),
            "Invalid account credential grammar (expected exact ASCII authorization value)"
        );
        let base = std::path::PathBuf::from(
            std::env::var_os("LOCALAPPDATA").context("LOCALAPPDATA missing")?,
        );
        crate::manifest::reject_link(&base)?;
        let folder = crate::manifest::safe(&base, "NebulaPreservation")?;
        if !folder.exists() {
            std::fs::create_dir(&folder)?
        }
        crate::manifest::reject_link(&folder)?;
        restrict(&folder)?;
        let config = crate::manifest::safe(&folder, "public-access.conf")?;
        ensure!(!config.exists(),"Public config already exists; retain it and explicitly move aside before provisioning a new account");
        let token = crate::manifest::safe(&folder, "account-token.dpapi")?;
        ensure!(!token.exists(),"Protected token already exists; run reset-public-config explicitly to remove only known protected configuration before reprovisioning");
        let name = token.to_str().context("Private token path is not UTF-8")?;
        ensure!(
            !name.contains(['\r', '\n', '\0']),
            "Private token path contains invalid characters"
        );
        let config_bytes =
            format!("format=nebula-public-access-v1\nserver_url={server}\ntoken_file={name}\n");
        ensure!(
            config_bytes.len() <= 4096
                && std::os::windows::ffi::OsStrExt::encode_wide(token.as_os_str()).count() < 260,
            "Private config exceeds bridge size/path limits"
        );
        let input = CRYPT_INTEGER_BLOB {
            cbData: bytes.len() as u32,
            pbData: bytes.as_ptr() as *mut u8,
        };
        let mut output: CRYPT_INTEGER_BLOB = unsafe { std::mem::zeroed() };
        ensure!(
            unsafe {
                CryptProtectData(
                    &input,
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null(),
                    CRYPTPROTECT_UI_FORBIDDEN,
                    &mut output,
                )
            } != 0,
            "DPAPI CurrentUser protection failed"
        );
        let mut protected = b"NPA1".to_vec();
        protected.extend_from_slice(&output.cbData.to_le_bytes());
        protected.extend_from_slice(unsafe {
            std::slice::from_raw_parts(output.pbData, output.cbData as usize)
        });
        unsafe {
            LocalFree(output.pbData.cast());
        }
        crate::transaction::new_file(&token, &protected)?;
        restrict(&token)?;
        crate::transaction::new_file(&config, config_bytes.as_bytes())?;
        restrict(&config)?;
        crate::endpoint::check_public_config(server)?;
        println!("Protected public-access configuration provisioned for the current Windows user. Source credential file was not modified.");
    }
    #[cfg(not(windows))]
    anyhow::bail!("CurrentUser DPAPI configuration requires Windows");
    Ok(())
}
