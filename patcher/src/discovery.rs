use crate::manifest;
use anyhow::{bail, ensure, Context, Result};
use serde::Serialize;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
#[derive(Clone, Debug)]
enum Value {
    Text(String),
    Map(BTreeMap<String, Value>),
}
impl Value {
    fn map(&self) -> Result<&BTreeMap<String, Value>> {
        if let Self::Map(v) = self {
            Ok(v)
        } else {
            bail!("Expected VDF map")
        }
    }
    fn text(&self) -> Result<&str> {
        if let Self::Text(v) = self {
            Ok(v)
        } else {
            bail!("Expected VDF string")
        }
    }
}
fn vdf(input: &str) -> Result<BTreeMap<String, Value>> {
    ensure!(input.len() <= 4 * 1024 * 1024, "VDF too large");
    let b = input.as_bytes();
    let mut p = 0;
    let mut tokens = Vec::new();
    while p < b.len() {
        match b[p] {
            b if b.is_ascii_whitespace() => p += 1,
            b'/' if b.get(p + 1) == Some(&b'/') => {
                while p < b.len() && b[p] != b'\n' {
                    p += 1
                }
            }
            b'{' | b'}' => {
                tokens.push((b[p] as char).to_string());
                p += 1
            }
            b'"' => {
                p += 1;
                let mut s = Vec::new();
                let mut closed = false;
                while p < b.len() {
                    if b[p] == b'"' {
                        p += 1;
                        closed = true;
                        break;
                    }
                    if b[p] == b'\\' && p + 1 < b.len() && [b'\\', b'"'].contains(&b[p + 1]) {
                        p += 1;
                    }
                    s.push(b[p]);
                    p += 1;
                }
                ensure!(closed, "Unclosed VDF string");
                tokens.push(String::from_utf8(s)?);
            }
            _ => {
                let start = p;
                while p < b.len() && !b[p].is_ascii_whitespace() && b[p] != b'{' && b[p] != b'}' {
                    p += 1;
                }
                tokens.push(input[start..p].to_string());
            }
        }
    }
    fn parse(
        t: &[String],
        p: &mut usize,
        depth: usize,
        nested: bool,
    ) -> Result<BTreeMap<String, Value>> {
        ensure!(depth < 32, "VDF too deeply nested");
        let mut out = BTreeMap::new();
        while *p < t.len() {
            let key = t[*p].clone();
            *p += 1;
            if key == "}" {
                ensure!(nested, "Unexpected VDF close");
                return Ok(out);
            }
            ensure!(key != "{", "Unexpected VDF open");
            let val = t.get(*p).context("Missing VDF value")?;
            *p += 1;
            let value = if val == "{" {
                Value::Map(parse(t, p, depth + 1, true)?)
            } else {
                ensure!(val != "}", "Missing VDF value");
                Value::Text(val.clone())
            };
            ensure!(out.insert(key, value).is_none(), "Duplicate VDF key");
        }
        ensure!(!nested, "Unclosed VDF map");
        Ok(out)
    }
    parse(&tokens, &mut 0, 0, false)
}

/// Cross-check Steam's active DWORD account against its parsed login-user table.
/// MostRecent and stored account names are deliberately not identity authority.
pub(crate) fn steam_account_from_loginusers(active: u32, input: &str) -> Result<String> {
    ensure!(active != 0, "Start Steam and sign in, then try Start again");
    let id = (76_561_197_960_265_728u64 + u64::from(active)).to_string();
    let root = vdf(input)?;
    let users = root
        .get("users")
        .context("Steam login table unavailable")?
        .map()?;
    users
        .get(&id)
        .context("Steam active account does not match its login table; sign in to Steam again")?
        .map()?;
    Ok(id)
}
#[cfg(windows)]
pub(crate) fn active_steam_account() -> Result<String> {
    use winreg::{enums::HKEY_CURRENT_USER, RegKey};
    let steam = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey("Software\\Valve\\Steam")
        .context("Start Steam and sign in before starting the game")?;
    let active: u32 = steam
        .open_subkey("ActiveProcess")?
        .get_value("ActiveUser")
        .context("Start Steam and sign in before starting the game")?;
    let root: String = steam.get_value("SteamPath")?;
    let path = manifest::safe(Path::new(&root), "config/loginusers.vdf")?;
    let bytes = manifest::read_bounded(&path, 4 * 1024 * 1024)?;
    steam_account_from_loginusers(active, std::str::from_utf8(&bytes)?)
}

#[derive(Serialize, Debug)]
pub struct Install {
    pub game: PathBuf,
    pub app_id: String,
    pub build_id: String,
    pub supported: bool,
}
fn app(steamapps: &Path) -> Result<Install> {
    let data = manifest::read_bounded(&steamapps.join("appmanifest_919290.acf"), 4 * 1024 * 1024)?;
    let root = vdf(std::str::from_utf8(&data)?)?;
    let state = root.get("AppState").context("Missing AppState")?.map()?;
    let field = |key: &str| -> Result<String> {
        Ok(state
            .get(key)
            .context("Missing appmanifest field")?
            .text()?
            .to_string())
    };
    let app_id = field("appid")?;
    let build_id = field("buildid")?;
    let name = field("installdir")?;
    ensure!(
        name == "Nebula Realms" && app_id == manifest::APP,
        "Unexpected Steam app identity"
    );
    Ok(Install {
        game: steamapps.join("common").join(name),
        supported: build_id == manifest::BUILD,
        app_id,
        build_id,
    })
}
pub fn discover() -> Result<Vec<Install>> {
    let mut roots = Vec::<PathBuf>::new();
    if let Some(p) = std::env::var_os("STEAM_DIR") {
        roots.push(p.into());
    }
    #[cfg(windows)]
    {
        use winreg::{
            enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE},
            RegKey,
        };
        for (hive, key, value) in [
            (HKEY_CURRENT_USER, "Software\\Valve\\Steam", "SteamPath"),
            (
                HKEY_LOCAL_MACHINE,
                "SOFTWARE\\WOW6432Node\\Valve\\Steam",
                "InstallPath",
            ),
            (HKEY_LOCAL_MACHINE, "SOFTWARE\\Valve\\Steam", "InstallPath"),
        ] {
            if let Ok(key) = RegKey::predef(hive).open_subkey(key) {
                if let Ok(p) = key.get_value::<String, _>(value) {
                    roots.push(p.into());
                }
            }
        }
        for env in ["ProgramFiles(x86)", "ProgramFiles"] {
            if let Some(p) = std::env::var_os(env) {
                roots.push(PathBuf::from(p).join("Steam"));
            }
        }
    }
    #[cfg(not(windows))]
    {
        if let Some(home) = std::env::var_os("HOME") {
            let home = PathBuf::from(home);
            roots.push(home.join(".steam/steam"));
            roots.push(home.join(".local/share/Steam"));
        }
    }
    #[cfg(windows)]
    for drive in b'C'..=b'Z' {
        // Bounded common locations only; never crawl an entire drive.
        for name in [
            "Steam",
            "SteamLibrary",
            "Games/Steam",
            "Program Files (x86)/Steam",
            "Program Files/Steam",
        ] {
            roots.push(PathBuf::from(format!("{}:/{name}", drive as char)));
        }
    }
    discover_roots(&roots).map(|(installs, warnings)| {
        for warning in warnings {
            eprintln!("Discovery warning: {warning}");
        }
        installs
    })
}
fn libraries_at(root: &Path) -> Result<Vec<PathBuf>> {
    let path = root.join("steamapps/libraryfolders.vdf");
    if !path.exists() {
        return Ok(Vec::new());
    }
    let data = manifest::read_bounded(&path, 4 * 1024 * 1024)?;
    let parsed = vdf(std::str::from_utf8(&data)?)?;
    let folders = parsed
        .get("libraryfolders")
        .or_else(|| parsed.get("LibraryFolders"))
        .context("Missing libraryfolders map")?
        .map()?;
    let mut libraries = Vec::new();
    for (key, value) in folders {
        if !key.is_empty() && key.bytes().all(|b| b.is_ascii_digit()) {
            let path = match value {
                Value::Text(p) => Some(p.as_str()),
                Value::Map(m) => m.get("path").map(Value::text).transpose()?,
            };
            if let Some(p) = path {
                libraries.push(PathBuf::from(p));
            }
        }
    }
    Ok(libraries)
}
fn discover_roots(roots: &[PathBuf]) -> Result<(Vec<Install>, Vec<String>)> {
    let mut libraries = roots.to_vec();
    let mut warnings = Vec::new();
    for root in roots {
        match libraries_at(root) {
            Ok(paths) => libraries.extend(paths),
            Err(error) => warnings.push(format!("{}: {error:#}", root.display())),
        }
    }
    let mut found = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for library in libraries {
        let sa = library.join("steamapps");
        if !sa.join("appmanifest_919290.acf").exists() {
            continue;
        }
        match app(&sa) {
            Ok(mut install) => match install_identity(&install.game) {
                Ok((key, display)) => {
                    if seen.insert(key) {
                        install.game = display;
                        found.push(install);
                    }
                }
                Err(error) => warnings.push(format!("{}: {error:#}", install.game.display())),
            },
            Err(error) => warnings.push(format!("{}: {error:#}", sa.display())),
        }
    }
    Ok((found, warnings))
}
#[cfg(windows)]
type InstallIdentity = (u64, [u8; 16]);
#[cfg(unix)]
type InstallIdentity = (u64, u64);
#[cfg(not(any(windows, unix)))]
type InstallIdentity = PathBuf;

/// Identify the existing directory rather than the spelling used by Steam's
/// registry/VDF/common-path entries. Never resolve a linked ancestor first.
fn install_identity(game: &Path) -> Result<(InstallIdentity, PathBuf)> {
    let absolute = if game.is_absolute() {
        game.to_path_buf()
    } else {
        std::env::current_dir()?.join(game)
    };
    for ancestor in absolute.ancestors() {
        manifest::reject_link(ancestor)?;
    }
    let canonical = std::fs::canonicalize(&absolute)?;
    manifest::reject_link(&canonical)?;
    ensure!(
        canonical.is_dir(),
        "Game installation folder is not a directory"
    );
    #[cfg(windows)]
    {
        use std::os::windows::ffi::{OsStrExt, OsStringExt};
        use windows_sys::Win32::{Foundation::*, Storage::FileSystem::*};
        struct Handle(HANDLE);
        impl Drop for Handle {
            fn drop(&mut self) {
                unsafe {
                    CloseHandle(self.0);
                }
            }
        }
        let path: Vec<u16> = canonical.as_os_str().encode_wide().chain(Some(0)).collect();
        let handle = Handle(unsafe {
            CreateFileW(
                path.as_ptr(),
                FILE_READ_ATTRIBUTES,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                std::ptr::null_mut(),
            )
        });
        ensure!(
            handle.0 != INVALID_HANDLE_VALUE,
            "Cannot identify Steam installation folder"
        );
        let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
        ensure!(
            unsafe { GetFileInformationByHandle(handle.0, &mut info) } != 0,
            "Cannot read Steam installation folder identity"
        );
        ensure!(
            info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT == 0
                && info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0,
            "Linked or nondirectory game installation rejected"
        );
        let mut identity: FILE_ID_INFO = unsafe { std::mem::zeroed() };
        ensure!(
            unsafe {
                GetFileInformationByHandleEx(
                    handle.0,
                    FileIdInfo,
                    (&mut identity as *mut FILE_ID_INFO).cast(),
                    std::mem::size_of::<FILE_ID_INFO>() as u32,
                )
            } != 0,
            "Cannot read stable Steam installation folder identity"
        );
        let key = (identity.VolumeSerialNumber, identity.FileId.Identifier);
        // Keep display paths conventional without lossy Unicode conversion.
        let mut display: Vec<u16> = canonical.as_os_str().encode_wide().collect();
        if display.starts_with(&[92, 92, 63, 92, 85, 78, 67, 92]) {
            display.splice(..8, [92, 92]);
        } else if display.starts_with(&[92, 92, 63, 92])
            && display.len() >= 7
            && display[5] == b':' as u16
            && display[6] == 92
        {
            display.drain(..4);
        }
        Ok((key, PathBuf::from(std::ffi::OsString::from_wide(&display))))
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let metadata = std::fs::metadata(&canonical)?;
        Ok(((metadata.dev(), metadata.ino()), canonical))
    }
    #[cfg(not(any(windows, unix)))]
    Ok((canonical.clone(), canonical))
}
/// File-picker admission: no arbitrary executable or unsupported Steam build.
pub fn select_executable(path: &Path) -> Result<PathBuf> {
    manifest::reject_link(path)?;
    ensure!(
        path.file_name().is_some_and(|name| name
            .to_string_lossy()
            .eq_ignore_ascii_case("Nebula Realms.exe")),
        "Select Nebula Realms.exe"
    );
    let game = select(Some(
        path.parent()
            .context("Executable has no folder")?
            .to_path_buf(),
    ))?;
    ensure!(
        manifest::hash(&manifest::read_bounded(
            &manifest::safe(&game, "Nebula Realms.exe")?,
            16 * 1024 * 1024
        )?) == manifest::EXE,
        "Executable is not the supported Steam build"
    );
    for name in [
        "GameAssembly.dll",
        "Nebula Realms_Data/il2cpp_data/Metadata/global-metadata.dat",
    ] {
        ensure!(
            manifest::safe(&game, name)?.is_file(),
            "Incomplete game installation: {name}"
        );
    }
    Ok(game)
}
pub fn select(explicit: Option<PathBuf>) -> Result<PathBuf> {
    if let Some(p) = explicit {
        manifest::reject_link(&p)?;
        let p = std::fs::canonicalize(p)?;
        manifest::reject_link(&p)?;
        ensure!(p.is_dir(), "Game path is not a directory");
        if let Some(common) = p.parent() {
            if common.file_name().is_some_and(|s| s == "common") {
                if let Some(sa) = common.parent() {
                    if sa.join("appmanifest_919290.acf").exists() {
                        ensure!(app(sa)?.supported, "Unsupported installed Steam build");
                    }
                }
            }
        }
        return Ok(p);
    }
    let found: Vec<_> = discover()?.into_iter().filter(|i| i.supported).collect();
    ensure!(
        found.len() == 1,
        "Expected one supported Steam installation; pass --game explicitly"
    );
    Ok(std::fs::canonicalize(&found[0].game)?)
}
pub fn inspect(game: &Path) -> Result<()> {
    let mut hashes = BTreeMap::new();
    for path in
        std::iter::once("Nebula Realms.exe").chain(manifest::ORIGINALS.iter().map(|(p, _)| *p))
    {
        hashes.insert(
            path,
            manifest::hash(&std::fs::read(manifest::safe(game, path)?)?),
        );
    }
    println!("{}", serde_json::to_string_pretty(&hashes)?);
    Ok(())
}

pub fn stopped() -> Result<()> {
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::{
            Foundation::{CloseHandle, GetLastError, ERROR_NO_MORE_FILES, INVALID_HANDLE_VALUE},
            System::Diagnostics::ToolHelp::*,
        };
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        ensure!(
            snapshot != INVALID_HANDLE_VALUE,
            "Cannot enumerate processes"
        );
        let mut item: PROCESSENTRY32W = std::mem::zeroed();
        item.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        if Process32FirstW(snapshot, &mut item) == 0 {
            CloseHandle(snapshot);
            bail!("Cannot read process census")
        }
        loop {
            let len = item
                .szExeFile
                .iter()
                .position(|c| *c == 0)
                .unwrap_or(item.szExeFile.len());
            let name = String::from_utf16_lossy(&item.szExeFile[..len]);
            if name.eq_ignore_ascii_case("Nebula Realms.exe") {
                CloseHandle(snapshot);
                bail!("Close Nebula Realms before patch/restore")
            };
            if Process32NextW(snapshot, &mut item) == 0 {
                let error = GetLastError();
                CloseHandle(snapshot);
                ensure!(
                    error == ERROR_NO_MORE_FILES,
                    "Process census ended with an error"
                );
                return Ok(());
            }
        }
    }
    #[cfg(not(windows))]
    bail!("Install mutations currently require Windows; Linux server deployment is separate");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn discovery_keeps_valid_library_when_another_manifest_is_bad() {
        let root = std::env::temp_dir().join(format!(
            "nebula-discovery-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let good = root.join("good");
        let bad = root.join("bad");
        std::fs::create_dir_all(good.join("steamapps/common/Nebula Realms")).unwrap();
        std::fs::create_dir_all(bad.join("steamapps")).unwrap();
        std::fs::write(
            good.join("steamapps/appmanifest_919290.acf"),
            "AppState { appid 919290 buildid 11018722 installdir \"Nebula Realms\" }",
        )
        .unwrap();
        std::fs::write(bad.join("steamapps/libraryfolders.vdf"), "broken {").unwrap();
        std::fs::write(
            bad.join("steamapps/appmanifest_919290.acf"),
            "AppState { appid 1 }",
        )
        .unwrap();
        let (found, warnings) = discover_roots(&[bad, good.clone(), good]).unwrap();
        assert_eq!(found.len(), 1);
        assert!(found[0].supported);
        assert_eq!(warnings.len(), 2);
        let canonical = root.canonicalize().unwrap();
        assert!(canonical.starts_with(std::env::temp_dir().canonicalize().unwrap()));
        std::fs::remove_dir_all(canonical).unwrap();
    }
    #[test]
    fn discovery_merges_filesystem_aliases_but_retains_distinct_installations() {
        let root = std::env::temp_dir().join(format!(
            "nebula-discovery-aliases-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let first = root.join("first");
        let second = root.join("second");
        for library in [&first, &second] {
            std::fs::create_dir_all(library.join("steamapps/common/Nebula Realms")).unwrap();
            std::fs::write(
                library.join("steamapps/appmanifest_919290.acf"),
                "AppState { appid 919290 buildid 11018722 installdir \"Nebula Realms\" }",
            )
            .unwrap();
        }
        let aliases = vec![
            first.clone(),
            first.join("."),
            first.join("../first"),
            second.clone(),
        ];
        #[cfg(windows)]
        let aliases = {
            let mut aliases = aliases;
            aliases.push(PathBuf::from(first.to_str().unwrap().replace('\\', "/")));
            aliases.push(PathBuf::from(first.to_str().unwrap().to_uppercase()));
            aliases
        };
        let (found, warnings) = discover_roots(&aliases).unwrap();
        assert!(warnings.is_empty(), "{warnings:?}");
        assert_eq!(found.len(), 2);
        assert_eq!(
            install_identity(&found[0].game).unwrap().0,
            install_identity(&first.join("steamapps/common/Nebula Realms"))
                .unwrap()
                .0
        );
        assert_eq!(
            install_identity(&found[1].game).unwrap().0,
            install_identity(&second.join("steamapps/common/Nebula Realms"))
                .unwrap()
                .0
        );
        #[cfg(windows)]
        assert!(!found[0]
            .game
            .as_os_str()
            .to_string_lossy()
            .starts_with("\\\\?\\"));
        // Delete only the fully resolved, uniquely created fixture below TEMP.
        let canonical = root.canonicalize().unwrap();
        assert!(canonical.starts_with(std::env::temp_dir().canonicalize().unwrap()));
        std::fs::remove_dir_all(canonical).unwrap();
    }
    #[test]
    fn stale_manifest_without_a_game_directory_is_not_an_installation() {
        let root = std::env::temp_dir().join(format!(
            "nebula-discovery-stale-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("steamapps")).unwrap();
        let acf = root.join("steamapps/appmanifest_919290.acf");
        std::fs::write(
            &acf,
            "AppState { appid 919290 buildid 11018722 installdir \"Nebula Realms\" }",
        )
        .unwrap();
        let (found, warnings) = discover_roots(&[root.clone()]).unwrap();
        assert!(found.is_empty());
        assert_eq!(warnings.len(), 1);
        std::fs::remove_file(acf).unwrap();
        std::fs::remove_dir(root.join("steamapps")).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn linked_library_ancestor_is_not_followed_for_identity_deduplication() {
        let root = std::env::temp_dir().join(format!(
            "nebula-discovery-link-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let real = root.join("real");
        std::fs::create_dir_all(real.join("steamapps/common/Nebula Realms")).unwrap();
        let alias = root.join("alias");
        std::os::unix::fs::symlink(&real, &alias).unwrap();
        assert!(install_identity(&alias.join("steamapps/common/Nebula Realms")).is_err());
        assert!(install_identity(&real.join("steamapps/common/Nebula Realms")).is_ok());
        std::fs::remove_file(alias).unwrap();
        let canonical = root.canonicalize().unwrap();
        assert!(canonical.starts_with(std::env::temp_dir().canonicalize().unwrap()));
        std::fs::remove_dir_all(canonical).unwrap();
    }
    #[test]
    fn picker_rejects_arbitrary_executable_before_selection() {
        assert!(select_executable(Path::new("other.exe")).is_err());
    }
    #[test]
    fn vdf_handles_steam_escape_and_rejects_duplicates() {
        let parsed =
            vdf("\"libraryfolders\" { \"0\" { \"path\" \"Z:\\\\ExampleLibrary\" } }").unwrap();
        assert_eq!(
            parsed["libraryfolders"].map().unwrap()["0"].map().unwrap()["path"]
                .text()
                .unwrap(),
            "Z:\\ExampleLibrary"
        );
        assert!(vdf("x 1 x 2").is_err());
        assert!(vdf("x { a b").is_err());
        assert!(vdf("x \"unclosed").is_err());
    }
}

#[cfg(test)]
mod active_account_tests {
    use super::*;
    #[test]
    fn active_account_requires_exact_login_table_membership_not_most_recent() {
        let base = 76_561_197_960_265_728u64;
        let table = format!(
            "\"users\" {{ \"{}\" {{ \"MostRecent\" \"0\" }} \"{}\" {{ \"MostRecent\" \"1\" }} }}",
            base + 42,
            base + 99
        );
        assert_eq!(
            steam_account_from_loginusers(42, &table).unwrap(),
            (base + 42).to_string()
        );
        assert!(steam_account_from_loginusers(0, &table).is_err());
        assert!(steam_account_from_loginusers(43, &table).is_err());
        assert!(steam_account_from_loginusers(42, "\"users\" { ").is_err());
    }
}
