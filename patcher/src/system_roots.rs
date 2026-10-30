//! Snapshot the Windows ROOT store without writing it or honoring SSL_CERT_*.
//! Trust remains rustls' normal chain/signature/hostname/time verification.
use anyhow::{ensure, Result};
use rustls::{pki_types::CertificateDer, RootCertStore};
use std::{ffi::CStr, mem::size_of, ptr::null_mut};
use windows_sys::Win32::{Foundation::*, Security::Cryptography::*};

struct Store(HCERTSTORE);
impl Drop for Store {
    fn drop(&mut self) {
        unsafe {
            CertCloseStore(self.0, 0);
        }
    }
}
struct Cursor(*const CERT_CONTEXT);
impl Drop for Cursor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                CertFreeCertificateContext(self.0);
            }
        }
    }
}

unsafe fn permits_server_auth(cert: *const CERT_CONTEXT) -> Result<bool> {
    let mut size = 0;
    ensure!(
        CertGetEnhancedKeyUsage(cert, 0, null_mut(), &mut size) != 0,
        "Cannot read Windows root certificate usage"
    );
    ensure!(
        (size_of::<CTL_USAGE>()..=65536).contains(&(size as usize)),
        "Windows root certificate usage exceeds bounds"
    );
    // CTL_USAGE contains pointers. A usize allocation supplies its alignment.
    let mut buffer = vec![0usize; (size as usize).div_ceil(size_of::<usize>())];
    let usage = buffer.as_mut_ptr().cast::<CTL_USAGE>();
    SetLastError(0);
    ensure!(
        CertGetEnhancedKeyUsage(cert, 0, usage, &mut size) != 0,
        "Cannot read Windows root certificate usage"
    );
    let error = GetLastError();
    let usage = &*usage;
    if usage.cUsageIdentifier == 0 {
        // Empty allowed EKU and unrestricted EKU are distinct Windows policies.
        return Ok(error == CRYPT_E_NOT_FOUND as u32);
    }
    ensure!(
        usage.cUsageIdentifier <= 1024 && !usage.rgpszUsageIdentifier.is_null(),
        "Windows root certificate usage exceeds bounds"
    );
    for index in 0..usage.cUsageIdentifier as usize {
        let oid = *usage.rgpszUsageIdentifier.add(index);
        ensure!(!oid.is_null(), "Invalid Windows root certificate usage");
        if CStr::from_ptr(oid.cast()).to_bytes() == b"1.3.6.1.5.5.7.3.1" {
            return Ok(true);
        }
    }
    Ok(false)
}

pub fn load() -> Result<RootCertStore> {
    unsafe {
        let name: Vec<u16> = "ROOT".encode_utf16().chain(Some(0)).collect();
        let store = Store(CertOpenStore(
            CERT_STORE_PROV_SYSTEM_W,
            0,
            0,
            CERT_SYSTEM_STORE_CURRENT_USER
                | CERT_STORE_OPEN_EXISTING_FLAG
                | CERT_STORE_READONLY_FLAG,
            name.as_ptr().cast(),
        ));
        ensure!(
            !store.0.is_null(),
            "Cannot open Windows trusted certificate store"
        );
        let mut current = Cursor(std::ptr::null());
        let mut roots = RootCertStore::empty();
        let mut count = 0;
        loop {
            // CertEnumCertificatesInStore frees the previous context, including
            // on failure. Cursor releases only the final still-owned context.
            current.0 = CertEnumCertificatesInStore(store.0, current.0);
            if current.0.is_null() {
                let error = GetLastError();
                ensure!(
                    error == CRYPT_E_NOT_FOUND as u32 || error == ERROR_NO_MORE_FILES,
                    "Cannot enumerate Windows trusted certificates"
                );
                break;
            }
            count += 1;
            ensure!(
                count <= 4096,
                "Windows root certificate store exceeds bounds"
            );
            let cert = &*current.0;
            ensure!(
                cert.cbCertEncoded > 0
                    && cert.cbCertEncoded <= 1024 * 1024
                    && !cert.pbCertEncoded.is_null()
                    && !cert.pCertInfo.is_null(),
                "Invalid Windows root certificate bounds"
            );
            if CertVerifyTimeValidity(std::ptr::null(), cert.pCertInfo) != 0
                || !permits_server_auth(current.0)?
            {
                continue;
            }
            let der = std::slice::from_raw_parts(cert.pbCertEncoded, cert.cbCertEncoded as usize);
            // Windows can retain certificate encodings unsupported by webpki.
            // Such a root grants no trust; it is never a reason to bypass TLS.
            let _ = roots.add(CertificateDer::from(der.to_vec()));
        }
        ensure!(!roots.is_empty(), "Windows has no usable trusted TLS roots; update Windows certificates or use the explicit pinned private-CA option");
        Ok(roots)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn windows_root_snapshot_is_read_only_and_has_usable_server_roots() {
        assert!(!super::load().unwrap().is_empty());
    }
}
