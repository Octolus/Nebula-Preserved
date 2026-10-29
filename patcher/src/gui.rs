//! Small native Windows UI. Hashing, TLS and file work run off the UI thread.
use anyhow::{ensure, Context, Result};
use std::{
    path::PathBuf,
    ptr::{null, null_mut},
};
use windows_sys::Win32::{
    Foundation::*,
    Graphics::Gdi::*,
    System::LibraryLoader::GetModuleHandleW,
    UI::{Controls::Dialogs::*, Input::KeyboardAndMouse::EnableWindow, WindowsAndMessaging::*},
};
const SERVER: i32 = 101;
const GAME: i32 = 102;
const ACCOUNT: i32 = 103;
const CA: i32 = 104;
const PIN: i32 = 105;
const STATUS: i32 = 106;
const BROWSE: i32 = 201;
const SCAN: i32 = 202;
const IMPORT: i32 = 203;
const START: i32 = 204;
const RESET: i32 = 205;
const PICK_ACCOUNT: i32 = 206;
const PICK_CA: i32 = 207;
const COMPLETE: u32 = WM_APP + 1;
struct State {
    busy: bool,
    allow_provisional: bool,
}
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(Some(0)).collect()
}
unsafe fn set(window: HWND, id: i32, value: &str) {
    SetWindowTextW(GetDlgItem(window, id), wide(value).as_ptr());
}
unsafe fn get(window: HWND, id: i32) -> String {
    let control = GetDlgItem(window, id);
    let mut text = vec![0u16; GetWindowTextLengthW(control) as usize + 1];
    let len = GetWindowTextW(control, text.as_mut_ptr(), text.len() as i32);
    String::from_utf16_lossy(&text[..len as usize])
}
unsafe fn control(
    window: HWND,
    class: &str,
    title: &str,
    id: i32,
    rect: (i32, i32, i32, i32),
    style: u32,
) {
    let (x, y, w, h) = rect;
    let handle = CreateWindowExW(
        0,
        wide(class).as_ptr(),
        wide(title).as_ptr(),
        WS_CHILD | WS_VISIBLE | style,
        x,
        y,
        w,
        h,
        window,
        id as usize as HMENU,
        GetModuleHandleW(null()),
        null(),
    );
    SendMessageW(
        handle,
        WM_SETFONT,
        GetStockObject(DEFAULT_GUI_FONT) as usize,
        1,
    );
}
unsafe fn busy(window: HWND, value: bool) {
    let state = &mut *(GetWindowLongPtrW(window, GWLP_USERDATA) as *mut State);
    state.busy = value;
    for id in [
        SERVER,
        GAME,
        ACCOUNT,
        CA,
        PIN,
        BROWSE,
        SCAN,
        IMPORT,
        START,
        RESET,
        PICK_ACCOUNT,
        PICK_CA,
    ] {
        EnableWindow(GetDlgItem(window, id), i32::from(!value));
    }
}
unsafe fn pick(window: HWND, game: bool) -> Result<Option<PathBuf>> {
    let mut name = vec![0u16; 32768];
    let filter = if game {
        wide("Nebula Realms executable\0Nebula Realms.exe\0\0")
    } else {
        wide("Files\0*.*\0\0")
    };
    let title = wide(if game {
        "Select the installed Nebula Realms.exe"
    } else {
        "Select the operator-provided file"
    });
    let mut dialog: OPENFILENAMEW = std::mem::zeroed();
    dialog.lStructSize = std::mem::size_of::<OPENFILENAMEW>() as u32;
    dialog.hwndOwner = window;
    dialog.lpstrFile = name.as_mut_ptr();
    dialog.nMaxFile = name.len() as u32;
    dialog.lpstrFilter = filter.as_ptr();
    dialog.lpstrTitle = title.as_ptr();
    dialog.Flags = OFN_FILEMUSTEXIST
        | OFN_PATHMUSTEXIST
        | OFN_NOCHANGEDIR
        | OFN_EXPLORER
        | OFN_DONTADDTORECENT;
    if GetOpenFileNameW(&mut dialog) == 0 {
        ensure!(CommDlgExtendedError() == 0, "Windows file picker failed");
        return Ok(None);
    }
    let len = name.iter().position(|c| *c == 0).unwrap_or(name.len());
    use std::os::windows::ffi::OsStringExt;
    Ok(Some(PathBuf::from(std::ffi::OsString::from_wide(
        &name[..len],
    ))))
}
fn worker(window: HWND, action: impl FnOnce() -> Result<String> + Send + 'static) {
    let handle = window as usize;
    unsafe {
        busy(window, true);
        set(
            window,
            STATUS,
            "Working: checking files and connection. You can move the mouse normally.",
        );
    }
    std::thread::spawn(move || {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(action));
        let text = match result {
            Ok(Ok(message)) => message,
            Ok(Err(error)) => format!("Stopped: {error:#}\r\nNo game was launched unless explicitly reported above."),
            Err(_) => "Stopped: an internal error occurred. Reopen the launcher and inspect the installation before retrying.".into(),
        };
        let ptr = Box::into_raw(Box::new(text));
        unsafe {
            if PostMessageW(handle as HWND, COMPLETE, 0, ptr as isize) == 0 {
                drop(Box::from_raw(ptr));
            }
        }
    });
}
unsafe fn action(window: HWND, id: i32) -> Result<()> {
    match id {
        SCAN => worker(window, move || {
            let installs = crate::discovery::discover()?;
            let supported: Vec<_> = installs.iter().filter(|i| i.supported).collect();
            if supported.len() == 1 {
                // Return data through the completion message; no cross-thread UI access.
                return Ok(format!("FOUND:{}", supported[0].game.display()));
            }
            Ok(if supported.is_empty() { "No supported Steam build found. Use Browse executable to select Nebula Realms.exe. Unsupported or incomplete installations are refused.".into() }
                else { format!("Found {} supported installations. Use Browse executable to choose the one you want.", supported.len()) })
        }),
        BROWSE => {
            if let Some(path) = pick(window, true)? {
                worker(window, move || {
                    let folder = crate::discovery::select_executable(&path)?;
                    Ok(format!("FOUND:{}", folder.display()))
                });
            }
        }
        PICK_ACCOUNT | PICK_CA => if let Some(path) = pick(window,false)? { set(window,if id == PICK_ACCOUNT {ACCOUNT} else {CA},path.to_str().context("Selected path must be Unicode")?); },
        IMPORT => {
            let server = crate::launcher::origin(&get(window,SERVER))?;
            let account = PathBuf::from(get(window,ACCOUNT)); let ca = PathBuf::from(get(window,CA)); let pin = get(window,PIN);
            ensure!(!account.as_os_str().is_empty() && !ca.as_os_str().is_empty(), "Select your account credential and the server CA certificate first");
            crate::manifest::sha(&pin)?;
            worker(window,move || {
                crate::credentials::configure(&server,&account)?;
                crate::remote::configure(&server,&ca,&pin)?;
                crate::launcher::probe(&server)?;
                Ok("Connection imported for this Windows user. TLS and the backend response were verified. The account is authenticated by the game on login. Click Start the game.".into())
            });
        }
        RESET => {
            if MessageBoxW(window,wide("Remove this Windows user's saved account credential and server trust profile? This does not delete your server account, inventory, game files or patch backups. You will need your account file and trusted CA to reconnect.").as_ptr(),wide("Reset saved connection").as_ptr(),MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) == IDYES {
                worker(window,|| { crate::remote::reset()?; crate::credentials::reset()?; Ok("Saved connection removed. Import the new server's account credential and trusted CA before starting.".into()) });
            }
        }
        START => {
            let allow_provisional = (*(GetWindowLongPtrW(window, GWLP_USERDATA) as *const State)).allow_provisional;
            let server = crate::launcher::origin(&get(window,SERVER))?;
            let game = get(window,GAME);
            worker(window,move || {
                let (bundle, manifest, pin) = crate::launcher::bundle(allow_provisional)?;
                crate::discovery::stopped()?;
                let folder = crate::discovery::select(if game.is_empty() {None} else {Some(PathBuf::from(game))})?;
                crate::discovery::select_executable(&folder.join("Nebula Realms.exe"))?;
                crate::remote::check(&server)?;
                crate::launcher::probe(&server)?;
                crate::transaction::patch(&folder,&bundle,&manifest,&pin,&server,"127.0.0.1",None,false,true)?;
                let pid = crate::transaction::launch_verified(&folder,&manifest,&pin,&server,allow_provisional)?;
                Ok(format!("Started the verified game (process {pid}). Steam ownership still applies. Connection, login and world loading are shown inside the game; this launcher does not claim those have completed."))
            });
        }
        _ => {}
    }
    Ok(())
}
unsafe extern "system" fn procedure(
    window: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_COMMAND => {
            if (wparam >> 16) == 0
                && GetWindowLongPtrW(window, GWLP_USERDATA) != 0
                && !(*(GetWindowLongPtrW(window, GWLP_USERDATA) as *const State)).busy
            {
                if let Err(error) = action(window, (wparam & 0xffff) as i32) {
                    set(window, STATUS, &format!("Stopped: {error:#}"));
                }
            }
            0
        }
        COMPLETE => {
            let text = *Box::from_raw(lparam as *mut String);
            busy(window, false);
            if let Some(folder) = text.strip_prefix("FOUND:") {
                set(window, GAME, folder);
                set(window,STATUS,"Game folder found. Start verifies the executable, Steam build, patch bundle, backups and all installed output hashes before launch.");
            } else {
                set(window, STATUS, &text);
            }
            0
        }
        WM_CLOSE => {
            let state = GetWindowLongPtrW(window, GWLP_USERDATA) as *const State;
            if !state.is_null() && (*state).busy {
                set(window,STATUS,"Please wait for the current verification or file transaction to finish before closing.");
            } else {
                DestroyWindow(window);
            }
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(window, message, wparam, lparam),
    }
}
pub fn run(allow_provisional: bool) -> Result<()> {
    unsafe {
        let instance = GetModuleHandleW(null());
        let class = wide("NebulaPreservationLauncher");
        let registration = WNDCLASSW {
            lpfnWndProc: Some(procedure),
            hInstance: instance,
            lpszClassName: class.as_ptr(),
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            hbrBackground: (COLOR_WINDOW + 1) as HBRUSH,
            ..std::mem::zeroed()
        };
        ensure!(
            RegisterClassW(&registration) != 0,
            "Cannot register launcher window"
        );
        let window = CreateWindowExW(
            0,
            class.as_ptr(),
            wide(if allow_provisional {
                "Nebula Preservation — DEVELOPMENT provisional acceptance"
            } else {
                "Nebula Preservation — Launcher"
            })
            .as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            740,
            510,
            null_mut(),
            null_mut(),
            instance,
            null(),
        );
        ensure!(!window.is_null(), "Cannot open launcher window");
        let mut state = Box::new(State {
            busy: false,
            allow_provisional,
        });
        SetWindowLongPtrW(window, GWLP_USERDATA, &mut *state as *mut State as isize);
        let edit = WS_BORDER | WS_TABSTOP | ES_AUTOHSCROLL as u32;
        control(
            window,
            "STATIC",
            "Server IPv4 or HTTPS origin",
            0,
            (20, 18, 650, 20),
            0,
        );
        control(
            window,
            "EDIT",
            option_env!("NEBULA_DEFAULT_SERVER").unwrap_or(""),
            SERVER,
            (20, 40, 690, 25),
            edit,
        );
        control(
            window,
            "STATIC",
            "Installed game folder",
            0,
            (20, 78, 650, 20),
            0,
        );
        control(
            window,
            "EDIT",
            "",
            GAME,
            (20, 100, 435, 25),
            edit | ES_READONLY as u32,
        );
        control(
            window,
            "BUTTON",
            "Browse executable",
            BROWSE,
            (465, 98, 145, 28),
            WS_TABSTOP,
        );
        control(
            window,
            "BUTTON",
            "Scan",
            SCAN,
            (620, 98, 90, 28),
            WS_TABSTOP,
        );
        control(
            window,
            "STATIC",
            "First connection: import your own operator-issued account file and trusted CA",
            0,
            (20, 145, 690, 20),
            0,
        );
        control(
            window,
            "EDIT",
            "",
            ACCOUNT,
            (20, 170, 545, 25),
            edit | ES_READONLY as u32,
        );
        control(
            window,
            "BUTTON",
            "Account file",
            PICK_ACCOUNT,
            (575, 168, 135, 28),
            WS_TABSTOP,
        );
        let ca_default = crate::embedded::ca()?.unwrap_or(
            std::env::current_exe()?
                .parent()
                .context("Launcher directory")?
                .join("operator-ca.der"),
        );
        control(
            window,
            "EDIT",
            if ca_default.is_file() {
                ca_default.to_str().unwrap_or("")
            } else {
                ""
            },
            CA,
            (20, 205, 545, 25),
            edit | ES_READONLY as u32,
        );
        control(
            window,
            "BUTTON",
            "CA certificate",
            PICK_CA,
            (575, 203, 135, 28),
            WS_TABSTOP,
        );
        control(
            window,
            "STATIC",
            "CA SHA256 — confirm with your server operator through a trusted channel",
            0,
            (20, 244, 690, 20),
            0,
        );
        control(
            window,
            "EDIT",
            option_env!("NEBULA_CA_SHA256").unwrap_or(""),
            PIN,
            (20, 268, 690, 25),
            edit,
        );
        control(
            window,
            "BUTTON",
            "Import connection",
            IMPORT,
            (20, 310, 150, 32),
            WS_TABSTOP,
        );
        control(
            window,
            "BUTTON",
            "Reset connection",
            RESET,
            (180, 310, 150, 32),
            WS_TABSTOP,
        );
        control(
            window,
            "BUTTON",
            "Start the game",
            START,
            (510, 310, 200, 32),
            WS_TABSTOP | BS_DEFPUSHBUTTON as u32,
        );
        control(
            window,
            "EDIT",
            "Detecting Steam libraries…",
            STATUS,
            (20, 360, 690, 95),
            WS_BORDER
                | ES_READONLY as u32
                | ES_MULTILINE as u32
                | ES_AUTOVSCROLL as u32
                | WS_VSCROLL,
        );
        ShowWindow(window, SW_SHOW);
        UpdateWindow(window);
        action(window, SCAN)?;
        let mut message: MSG = std::mem::zeroed();
        loop {
            let result = GetMessageW(&mut message, null_mut(), 0, 0);
            ensure!(result != -1, "Windows message loop failed");
            if result == 0 {
                break;
            }
            if IsDialogMessageW(window, &message) == 0 {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
        Ok(())
    }
}
