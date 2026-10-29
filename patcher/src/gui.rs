//! Native controls, scalable layout and typed background jobs. No input capture.
use crate::launcher_ui::*;
use anyhow::{ensure, Context, Result};
use std::{
    path::PathBuf,
    ptr::{null, null_mut},
};
use windows_sys::Win32::{
    Foundation::*,
    Graphics::Gdi::*,
    System::LibraryLoader::GetModuleHandleW,
    UI::{
        Controls::{Dialogs::*, *},
        HiDpi::*,
        Input::KeyboardAndMouse::{EnableWindow, GetFocus},
        WindowsAndMessaging::*,
    },
};
const EVENT: u32 = WM_APP + 1;
const BG: u32 = 0x00f8f6f3;
const INK: u32 = 0x00312619;
const MUTED: u32 = 0x00625245;
#[derive(Clone, Copy)]
enum Job {
    Scan,
    Select,
    Import,
    Check,
    Reset,
    Start,
}
enum Outcome {
    Startup {
        folder: Option<PathBuf>,
        server: Option<String>,
        connected: bool,
        note: String,
    },
    Selected(PathBuf),
    Connected(String),
    Reset,
    Launched(u32),
}
enum Event {
    Progress(&'static str),
    Finished(Job, std::result::Result<Outcome, String>),
}
struct State {
    flow: Flow,
    allow_provisional: bool,
    advanced: bool,
    details: bool,
    scroll: i32,
    dpi: u32,
    fonts: [HFONT; 4],
    background: HBRUSH,
    paper: HBRUSH,
}
impl Drop for State {
    fn drop(&mut self) {
        unsafe {
            for font in self.fonts {
                DeleteObject(font);
            }
            DeleteObject(self.background);
            DeleteObject(self.paper);
        }
    }
}
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
unsafe fn state(window: HWND) -> &'static mut State {
    &mut *(GetWindowLongPtrW(window, GWLP_USERDATA) as *mut State)
}
unsafe fn set(window: HWND, id: i32, value: &str) {
    SetWindowTextW(GetDlgItem(window, id), wide(value).as_ptr());
}
unsafe fn get(window: HWND, id: i32) -> String {
    let control = GetDlgItem(window, id);
    let mut value = vec![0u16; GetWindowTextLengthW(control) as usize + 1];
    let n = GetWindowTextW(control, value.as_mut_ptr(), value.len() as i32);
    String::from_utf16_lossy(&value[..n as usize])
}
unsafe fn label(window: HWND, id: i32, text: &str, class: &str, style: u32) -> Result<()> {
    let handle = CreateWindowExW(
        if class == "EDIT" { WS_EX_CLIENTEDGE } else { 0 },
        wide(class).as_ptr(),
        wide(text).as_ptr(),
        WS_CHILD | WS_VISIBLE | style,
        0,
        0,
        1,
        1,
        window,
        id as usize as HMENU,
        GetModuleHandleW(null()),
        null(),
    );
    ensure!(!handle.is_null(), "Cannot create launcher control");
    if class == "EDIT" {
        SendMessageW(
            handle,
            EM_SETLIMITTEXT,
            if id == DETAILS { 32768 } else { 4096 },
            0,
        );
    }
    Ok(())
}
unsafe fn fonts(window: HWND) {
    let s = state(window);
    let old = s.fonts;
    for (index, (size, weight)) in [(14, 400), (26, 600), (18, 600), (12, 400)]
        .into_iter()
        .enumerate()
    {
        s.fonts[index] = CreateFontW(
            -(size * s.dpi as i32 / 96),
            0,
            0,
            0,
            weight,
            0,
            0,
            0,
            DEFAULT_CHARSET as u32,
            OUT_DEFAULT_PRECIS as u32,
            CLIP_DEFAULT_PRECIS as u32,
            CLEARTYPE_QUALITY as u32,
            DEFAULT_PITCH as u32,
            wide("Segoe UI").as_ptr(),
        );
    }
    let new_fonts = s.fonts;
    for id in all_controls() {
        let index = match id {
            TITLE => 1,
            GAME_TITLE | SERVER_TITLE | NEXT => 2,
            SUBTITLE | NOTICE | GAME_HELP | SERVER_HELP | CERT_HELP | NEXT_HELP | ACTIVITY => 3,
            _ => 0,
        };
        SendMessageW(
            GetDlgItem(window, id),
            WM_SETFONT,
            new_fonts[index] as usize,
            1,
        );
    }
    for font in old {
        if !font.is_null() {
            DeleteObject(font);
        }
    }
}
fn all_controls() -> Vec<i32> {
    (SERVER..=DETAILS)
        .chain(BROWSE..=TOGGLE_DETAILS)
        .chain(TITLE..=PROGRESS)
        .collect()
}
unsafe fn reflow(window: HWND) {
    let mut client: RECT = std::mem::zeroed();
    GetClientRect(window, &mut client);
    let s = state(window);
    let width = client.right * 96 / s.dpi as i32;
    let height = client.bottom * 96 / s.dpi as i32;
    let view = layout(width, s.advanced, s.details);
    s.scroll = scroll_position(s.scroll, 0, view.height, height);
    let dpi = s.dpi;
    let scroll = s.scroll;
    let mut ordered = view.controls.clone();
    ordered.sort_by_key(|(_, r)| (r.1, r.0));
    let mut previous = HWND_TOP;
    for (id, rect) in ordered {
        let handle = GetDlgItem(window, id);
        let Rect(x, y, w, h) = rect.scaled(dpi, scroll);
        SetWindowPos(
            handle,
            previous,
            x,
            y,
            w,
            h,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        );
        previous = handle;
    }
    for id in all_controls() {
        let handle = GetDlgItem(window, id);
        if !view.controls.iter().any(|(key, _)| *key == id) {
            ShowWindow(handle, SW_HIDE);
        }
    }
    let info = SCROLLINFO {
        cbSize: std::mem::size_of::<SCROLLINFO>() as u32,
        fMask: SIF_RANGE | SIF_PAGE | SIF_POS,
        nMin: 0,
        nMax: view.height - 1,
        nPage: height.max(1) as u32,
        nPos: scroll,
        nTrackPos: 0,
    };
    SetScrollInfo(window, SB_VERT, &info, 1);
    InvalidateRect(window, null(), 1);
}
unsafe fn reveal_focus(window: HWND) {
    let id = GetDlgCtrlID(GetFocus());
    let mut client: RECT = std::mem::zeroed();
    GetClientRect(window, &mut client);
    let s = state(window);
    let height = client.bottom * 96 / s.dpi as i32;
    let view = layout(client.right * 96 / s.dpi as i32, s.advanced, s.details);
    if let Some((_, r)) = view.controls.iter().find(|(key, _)| *key == id) {
        let before = s.scroll;
        if r.1 < s.scroll {
            s.scroll = (r.1 - 12).max(0);
        } else if r.1 + r.3 > s.scroll + height {
            s.scroll = r.1 + r.3 - height + 12;
        }
        if s.scroll != before {
            reflow(window);
        }
    }
}
unsafe fn scroll_to_details(window: HWND) {
    let mut client: RECT = std::mem::zeroed();
    GetClientRect(window, &mut client);
    let s = state(window);
    let view = layout(client.right * 96 / s.dpi as i32, s.advanced, s.details);
    s.scroll = scroll_position(0, i32::MAX, view.height, client.bottom * 96 / s.dpi as i32);
}
unsafe fn refresh(window: HWND) {
    let s = state(window);
    // End state borrows before synchronous control messages can reenter.
    let (busy, can_start, game_ready, connected, advanced, details) = (
        s.flow.busy,
        s.flow.can_start(),
        s.flow.game_ready,
        s.flow.verified_origin.is_some(),
        s.advanced,
        s.details,
    );
    let (title, help) = s.flow.next();
    for id in [
        SERVER,
        GAME,
        ACCOUNT,
        CA,
        PIN,
        BROWSE,
        SCAN,
        IMPORT,
        RESET,
        PICK_ACCOUNT,
        PICK_CA,
        CHECK,
        ADVANCED,
    ] {
        EnableWindow(GetDlgItem(window, id), i32::from(!busy));
    }
    EnableWindow(GetDlgItem(window, START), i32::from(can_start));
    EnableWindow(GetDlgItem(window, IMPORT), i32::from(!busy && !connected));
    set(window, NEXT, title);
    set(window, NEXT_HELP, help);
    set(
        window,
        START,
        if busy {
            "Please wait…"
        } else {
            "&Start the game"
        },
    );
    set(
        window,
        GAME_TITLE,
        if game_ready {
            "1   Game found"
        } else {
            "1   Find your game"
        },
    );
    set(
        window,
        SERVER_TITLE,
        if connected {
            "2   Connection checked"
        } else {
            "2   Connect to your server"
        },
    );
    set(
        window,
        ADVANCED,
        if advanced {
            "Hide certificate se&ttings"
        } else {
            "Certificate se&ttings"
        },
    );
    set(
        window,
        TOGGLE_DETAILS,
        if details {
            "Hide technical &details"
        } else {
            "Show technical &details"
        },
    );
    SendMessageW(
        GetDlgItem(window, PROGRESS),
        PBM_SETMARQUEE,
        busy as usize,
        35,
    );
    set(
        window,
        IMPORT,
        if connected {
            "Connection saved"
        } else {
            "Save &connection"
        },
    );
    set(
        window,
        SERVER_HELP,
        if connected {
            "Saved for this Windows user. Use certificate settings to change accounts."
        } else {
            "Server IPv4 or HTTPS address, supplied by your server owner."
        },
    );
}
unsafe fn note(window: HWND, activity: &str, details: &str) {
    set(window, ACTIVITY, activity);
    set(window, DETAILS, details);
}
fn post(window: usize, event: Event) {
    let ptr = Box::into_raw(Box::new(event));
    unsafe {
        if PostMessageW(window as HWND, EVENT, 0, ptr as isize) == 0 {
            drop(Box::from_raw(ptr));
        }
    }
}
fn worker(window: HWND, job: Job, work: impl FnOnce(usize) -> Result<Outcome> + Send + 'static) {
    let handle = window as usize;
    unsafe {
        state(window).flow.busy = true;
        refresh(window);
    }
    std::thread::spawn(move || {
        let outcome = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| work(handle)))
        {
            Ok(result) => result.map_err(|e| format!("{e:#}")),
            Err(_) => Err(
                "An internal error interrupted the operation. Reopen the launcher before retrying."
                    .into(),
            ),
        };
        post(handle, Event::Finished(job, outcome));
    });
}
fn stage(window: usize, message: &'static str) {
    post(window, Event::Progress(message));
}
unsafe fn pick(window: HWND, kind: i32) -> Result<Option<PathBuf>> {
    let mut name = vec![0u16; 32768];
    let filter = wide(match kind {
        GAME => "Nebula Realms executable\0Nebula Realms.exe\0\0",
        CA => "DER certificate\0*.der\0All files\0*.*\0\0",
        _ => "Account credential\0*.txt;*.auth;*.credential\0All files\0*.*\0\0",
    });
    let title = wide(match kind {
        GAME => "Choose your installed Nebula Realms.exe",
        CA => "Choose the server owner's DER certificate",
        _ => "Choose your own account credential file",
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
unsafe fn action(window: HWND, id: i32) -> Result<()> {
    match id {
        ADVANCED => { state(window).advanced = !state(window).advanced; refresh(window); reflow(window); }
        TOGGLE_DETAILS => { state(window).details = !state(window).details; refresh(window); reflow(window); }
        SCAN => worker(window, Job::Scan, move |handle| {
            stage(handle, "Searching Steam libraries…");
            let installs = crate::discovery::discover()?;
            let supported: Vec<_> = installs.iter().filter(|i| i.supported).collect();
            let folder = (supported.len() == 1).then(|| supported[0].game.clone());
            let mut note = match supported.len() { 0 => "Game not found. Choose Nebula Realms.exe to locate it.".into(),
                1 => "Game found. Checking your saved connection…".into(),
                _ => "Several copies found. Choose the Nebula Realms.exe you want to use.".into() };
            let (server, damaged_profile) = match crate::remote::saved_server() {
                Ok(server) => (server,false), Err(_) => (None,true),
            };
            let connected = server.as_deref().is_some_and(|server| {
                stage(handle, "Checking the saved connection and server…");
                crate::launcher::probe(server).is_ok()
            });
            if folder.is_some() {
                note = if connected {"Game found. Your saved connection is ready.".into()}
                    else if server.is_some() {"Saved connection found, but the server could not be reached. Check the address and try Check server.".into()}
                    else {"Game found. Enter the server address and choose your account file.".into()};
            }
            if damaged_profile { note = "Saved connection needs attention. Open certificate settings and check the saved connection before importing again.".into(); }
            Ok(Outcome::Startup { folder, server, connected, note })
        }),
        BROWSE => if let Some(path) = pick(window, GAME)? {
            worker(window, Job::Select, move |handle| { stage(handle, "Verifying the selected Steam installation…");
                Ok(Outcome::Selected(crate::discovery::select_executable(&path)?)) });
        },
        PICK_ACCOUNT | PICK_CA => if let Some(path) = pick(window, if id == PICK_ACCOUNT {ACCOUNT} else {CA})? {
            set(window, if id == PICK_ACCOUNT {ACCOUNT} else {CA}, path.to_str().context("Selected path must be Unicode")?);
        },
        CHECK => {
            let server = crate::launcher::origin(&get(window, SERVER))?;
            worker(window, Job::Check, move |handle| { stage(handle, "Checking the saved certificate and server…");
                crate::launcher::probe(&server)?; Ok(Outcome::Connected(server)) });
        }
        IMPORT => {
            let server = crate::launcher::origin(&get(window, SERVER))?;
            let account = PathBuf::from(get(window, ACCOUNT)); let ca = PathBuf::from(get(window, CA));
            let pin = get(window, PIN).trim().to_ascii_lowercase();
            ensure!(!account.as_os_str().is_empty(), "Choose your own account credential file using Choose file");
            if ca.as_os_str().is_empty() || crate::manifest::sha(&pin).is_err() {
                state(window).advanced = true; reflow(window); refresh(window);
                anyhow::bail!("Open Certificate settings and supply the server certificate and its trusted 64-character SHA256 fingerprint");
            }
            worker(window, Job::Import, move |handle| {
                stage(handle, "Checking the certificate fingerprint…"); crate::remote::validate_ca_file(&ca, &pin)?;
                stage(handle, "Protecting your account connection for this Windows user…"); crate::credentials::configure(&server, &account)?;
                crate::remote::configure(&server, &ca, &pin)?;
                stage(handle, "Verifying TLS and the server response…"); crate::launcher::probe(&server)?;
                Ok(Outcome::Connected(server))
            });
        }
        RESET => {
            if MessageBoxW(window, wide("Forget the saved connection on this PC? Your server account, items, game files and patch backups are kept. You will need your account file and the server certificate to connect again.").as_ptr(),
                wide("Forget saved connection?").as_ptr(), MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) == IDYES {
                worker(window, Job::Reset, |_| { crate::remote::reset()?; crate::credentials::reset()?; Ok(Outcome::Reset) });
            }
        }
        START => {
            ensure!(state(window).flow.can_start(), "Complete the game and connection steps first");
            let provisional = state(window).allow_provisional;
            let server = crate::launcher::origin(&get(window, SERVER))?; let game = get(window, GAME);
            worker(window, Job::Start, move |handle| {
                stage(handle, "Checking the reviewed patch bundle…"); let (bundle, manifest, pin) = crate::launcher::bundle(provisional)?;
                crate::discovery::stopped()?;
                stage(handle, "Verifying the game installation…");
                let folder = crate::discovery::select(Some(PathBuf::from(game)))?;
                crate::discovery::select_executable(&folder.join("Nebula Realms.exe"))?;
                stage(handle, "Checking the server and secure connection…"); crate::launcher::probe(&server)?;
                stage(handle, "Verifying backups and applying the patch…");
                crate::transaction::patch(&folder,&bundle,&manifest,&pin,&server,"127.0.0.1",None,false,true)?;
                stage(handle, "Checking installed files and starting the game…");
                Ok(Outcome::Launched(crate::transaction::launch_verified(&folder,&manifest,&pin,&server,provisional)?))
            });
        }
        _ => {}
    }
    Ok(())
}
unsafe fn finish(window: HWND, job: Job, result: std::result::Result<Outcome, String>) {
    state(window).flow.busy = false;
    match result {
        Ok(Outcome::Startup {
            folder,
            server,
            connected,
            note: text,
        }) => {
            if let Some(path) = folder {
                set(window, GAME, &path.to_string_lossy());
                state(window).flow.game_ready = true;
            }
            if let Some(server) = server {
                set(window, SERVER, &server);
                state(window).flow.verified_origin = connected.then_some(server);
            } else {
                state(window).flow.verified_origin = None;
            }
            note(window, &text, "Steam discovery and saved connection checks finished. Server reachability does not prove account login or world loading.");
        }
        Ok(Outcome::Selected(folder)) => {
            set(window, GAME, &folder.to_string_lossy());
            state(window).flow.game_ready = true;
            note(
                window,
                "Game installation verified.",
                "Start checks all game files and backups again before making changes.",
            );
        }
        Ok(Outcome::Connected(server)) => {
            set(window, SERVER, &server);
            state(window).flow.verified_origin = Some(server);
            note(window, "Connection checked. The game will sign in with your account.", "The saved profile, certificate, hostname and preservation backend response passed. This read-only check does not authenticate the account or prove world loading.");
        }
        Ok(Outcome::Reset) => {
            state(window).flow.verified_origin = None;
            note(window, "Saved connection forgotten. Choose your account file to set up again.", "Only fixed local account/trust configuration was removed. Your server account and patch backups were retained.");
        }
        Ok(Outcome::Launched(pid)) => {
            note(window, "Game started. Continue signing in inside Nebula Realms.", &format!("Started verified process {pid}. A process start does not prove login, world loading or multiplayer."));
        }
        Err(error) => {
            if matches!(job, Job::Check | Job::Import | Job::Reset) {
                state(window).flow.verified_origin = None;
            }
            let help = match job {
                Job::Scan | Job::Select => "Game check stopped. Choose your installed Nebula Realms.exe; see details.",
                Job::Check => "Connection check stopped. Check the server address and saved connection; see details.",
                Job::Import => "Setup stopped. Check your account file and certificate; see details.",
                Job::Reset => "Connection reset stopped. See details before retrying.",
                Job::Start => "Start stopped. Read the details below before retrying.",
            };
            state(window).details = true;
            scroll_to_details(window);
            let recovery = if matches!(job, Job::Import) {
                "\r\n\r\nIf an earlier import was interrupted, open Certificate settings, use Forget connection, then import the trusted files again."
            } else {
                ""
            };
            note(window, help, &format!("{error}{recovery}"));
        }
    }
    refresh(window);
    reflow(window);
}
unsafe fn paint(window: HWND) {
    let mut ps: PAINTSTRUCT = std::mem::zeroed();
    let dc = BeginPaint(window, &mut ps);
    let mut client: RECT = std::mem::zeroed();
    GetClientRect(window, &mut client);
    let s = state(window);
    let (background, paper, dpi, advanced, details, scroll) = (
        s.background,
        s.paper,
        s.dpi,
        s.advanced,
        s.details,
        s.scroll,
    );
    FillRect(dc, &client, background);
    let view = layout(client.right * 96 / dpi as i32, advanced, details);
    let pen = CreatePen(PS_SOLID, 1, 0x00e6dfd8);
    let old_pen = SelectObject(dc, pen);
    let old_brush = SelectObject(dc, paper);
    for card in view.cards {
        let Rect(x, y, w, h) = card.scaled(dpi, scroll);
        RoundRect(dc, x, y, x + w, y + h, 12, 12);
    }
    SelectObject(dc, old_pen);
    SelectObject(dc, old_brush);
    DeleteObject(pen);
    EndPaint(window, &ps);
}
unsafe extern "system" fn procedure(
    window: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    let ready = GetWindowLongPtrW(window, GWLP_USERDATA) != 0;
    match message {
        WM_COMMAND if ready => {
            let id = (wparam & 0xffff) as i32;
            let notification = wparam >> 16;
            if id == SERVER && notification == EN_CHANGE as usize {
                state(window).flow.verified_origin = None;
                refresh(window);
            } else if notification == BN_CLICKED as usize
                && (!state(window).flow.busy || id == TOGGLE_DETAILS)
            {
                if let Err(e) = action(window, id) {
                    state(window).details = true;
                    scroll_to_details(window);
                    note(
                        window,
                        "One more thing is needed. Read the details below.",
                        &format!("{e:#}"),
                    );
                    refresh(window);
                    reflow(window);
                }
            }
            0
        }
        EVENT if ready => {
            match *Box::from_raw(lparam as *mut Event) {
                Event::Progress(text) => set(window, ACTIVITY, text),
                Event::Finished(job, result) => finish(window, job, result),
            }
            0
        }
        WM_SIZE if ready => {
            reflow(window);
            0
        }
        WM_DPICHANGED if ready => {
            state(window).dpi = (wparam & 0xffff) as u32;
            fonts(window);
            let r = &*(lparam as *const RECT);
            SetWindowPos(
                window,
                null_mut(),
                r.left,
                r.top,
                r.right - r.left,
                r.bottom - r.top,
                SWP_NOZORDER | SWP_NOACTIVATE,
            );
            reflow(window);
            0
        }
        WM_GETMINMAXINFO => {
            let dpi = if ready { state(window).dpi } else { 96 };
            let info = &mut *(lparam as *mut MINMAXINFO);
            info.ptMinTrackSize.x = 570 * dpi as i32 / 96;
            info.ptMinTrackSize.y = 430 * dpi as i32 / 96;
            0
        }
        WM_VSCROLL | WM_MOUSEWHEEL if ready => {
            let mut info: SCROLLINFO = std::mem::zeroed();
            info.cbSize = std::mem::size_of::<SCROLLINFO>() as u32;
            info.fMask = SIF_ALL;
            GetScrollInfo(window, SB_VERT, &mut info);
            let delta = if message == WM_MOUSEWHEEL {
                -((wparam >> 16) as u16 as i16 as i32) * 48 / 120
            } else {
                match wparam as u16 as i32 {
                    SB_LINEUP => -36,
                    SB_LINEDOWN => 36,
                    SB_PAGEUP => -(info.nPage as i32),
                    SB_PAGEDOWN => info.nPage as i32,
                    SB_THUMBTRACK | SB_THUMBPOSITION => info.nTrackPos - info.nPos,
                    SB_TOP => -info.nPos,
                    SB_BOTTOM => info.nMax,
                    _ => 0,
                }
            };
            state(window).scroll =
                scroll_position(info.nPos, delta, info.nMax + 1, info.nPage as i32);
            reflow(window);
            0
        }
        WM_CTLCOLORSTATIC | WM_CTLCOLOREDIT if ready => {
            let dc = wparam as HDC;
            let id = GetDlgCtrlID(lparam as HWND);
            SetTextColor(
                dc,
                if [
                    SUBTITLE,
                    NOTICE,
                    GAME_HELP,
                    SERVER_HELP,
                    CERT_HELP,
                    NEXT_HELP,
                    ACTIVITY,
                ]
                .contains(&id)
                {
                    MUTED
                } else {
                    INK
                },
            );
            if [
                GAME,
                ACCOUNT,
                CA,
                DETAILS,
                SERVER,
                PIN,
                GAME_TITLE,
                GAME_HELP,
                SERVER_TITLE,
                SERVER_HELP,
                ACCOUNT_LABEL,
                CERT_LABEL,
                PIN_LABEL,
                CERT_HELP,
            ]
            .contains(&id)
            {
                SetBkColor(dc, 0x00ffffff);
                state(window).paper as isize
            } else {
                SetBkColor(dc, BG);
                state(window).background as isize
            }
        }
        WM_PAINT if ready => {
            paint(window);
            0
        }
        WM_ERASEBKGND if ready => 1,
        WM_CLOSE if ready => {
            if state(window).flow.busy {
                set(
                    window,
                    ACTIVITY,
                    "Please let the current check or patch finish before closing.",
                );
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
        // The embedded manifest enables per-monitor DPI and themed native controls.
        let common = INITCOMMONCONTROLSEX {
            dwSize: std::mem::size_of::<INITCOMMONCONTROLSEX>() as u32,
            dwICC: ICC_PROGRESS_CLASS,
        };
        InitCommonControlsEx(&common);
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
        let dpi = GetDpiForSystem().max(96);
        let mut work: RECT = std::mem::zeroed();
        ensure!(
            SystemParametersInfoW(SPI_GETWORKAREA, 0, (&mut work as *mut RECT).cast(), 0) != 0,
            "Cannot read available window area"
        );
        let width = (780 * dpi as i32 / 96).min(work.right - work.left - 24);
        let height = (820 * dpi as i32 / 96).min(work.bottom - work.top - 24);
        let window = CreateWindowExW(
            0,
            class.as_ptr(),
            wide(if allow_provisional {
                "Nebula Preserved — Developer launcher"
            } else {
                "Nebula Preserved"
            })
            .as_ptr(),
            WS_OVERLAPPEDWINDOW | WS_VSCROLL | WS_CLIPCHILDREN,
            work.left + (work.right - work.left - width) / 2,
            work.top + (work.bottom - work.top - height) / 2,
            width,
            height,
            null_mut(),
            null_mut(),
            instance,
            null(),
        );
        ensure!(!window.is_null(), "Cannot open launcher window");
        let available = option_env!("NEBULA_BUNDLE_SHA256")
            .is_some_and(|pin| crate::manifest::sha(pin).is_ok());
        let mut owned = Box::new(State {
            flow: Flow {
                bundle_available: available,
                ..Flow::default()
            },
            allow_provisional,
            advanced: false,
            details: false,
            scroll: 0,
            dpi: GetDpiForWindow(window).max(96),
            fonts: [null_mut(); 4],
            background: CreateSolidBrush(BG),
            paper: CreateSolidBrush(0x00ffffff),
        });
        SetWindowLongPtrW(window, GWLP_USERDATA, &mut *owned as *mut State as isize);
        for (id, text) in [
            (TITLE, "Nebula Preserved"),
            (
                SUBTITLE,
                "Reconnect with your community. Your original Steam game is required.",
            ),
            (
                NOTICE,
                if allow_provisional {
                    "Development mode · Provisional game acceptance only"
                } else if available {
                    "Community preservation project · Original game UI and controls"
                } else {
                    "Development build · A reviewed player bundle is needed to play"
                },
            ),
            (GAME_TITLE, "1   Find your game"),
            (
                GAME_HELP,
                "Steam libraries are detected automatically. You can also choose the game.",
            ),
            (SERVER_TITLE, "2   Connect to your server"),
            (
                SERVER_HELP,
                "Server IPv4 or HTTPS address, supplied by your server owner.",
            ),
            (
                ACCOUNT_LABEL,
                "Your account file — supplied by the server owner",
            ),
            (CERT_LABEL, "Server certificate (.der)"),
            (PIN_LABEL, "Certificate fingerprint (SHA256)"),
            (CERT_HELP, "Confirm the fingerprint with the server owner."),
            (NEXT, "Find your game"),
            (NEXT_HELP, ""),
            (ACTIVITY, "Searching Steam libraries…"),
        ] {
            label(window, id, text, "STATIC", 0)?;
        }
        let edit = WS_TABSTOP | ES_AUTOHSCROLL as u32;
        for (id, value, readonly) in [
            (GAME, String::new(), true),
            (
                SERVER,
                option_env!("NEBULA_DEFAULT_SERVER").unwrap_or("").into(),
                false,
            ),
            (ACCOUNT, String::new(), true),
            (CA, String::new(), true),
            (
                PIN,
                option_env!("NEBULA_CA_SHA256").unwrap_or("").into(),
                false,
            ),
        ] {
            label(
                window,
                id,
                &value,
                "EDIT",
                edit | if readonly { ES_READONLY as u32 } else { 0 },
            )?;
        }
        for (id, text) in [
            (SCAN, "&Find game"),
            (BROWSE, "&Browse…"),
            (CHECK, "Check ser&ver"),
            (PICK_ACCOUNT, "Choose f&ile"),
            (PICK_CA, "Choose C&A"),
            (ADVANCED, "Certificate se&ttings"),
            (IMPORT, "Save &connection"),
            (RESET, "Forget c&onnection"),
            (START, "&Start the game"),
            (TOGGLE_DETAILS, "Show technical &details"),
        ] {
            label(
                window,
                id,
                text,
                "BUTTON",
                WS_TABSTOP
                    | if id == START {
                        BS_DEFPUSHBUTTON as u32
                    } else {
                        0
                    },
            )?;
        }
        label(
            window,
            DETAILS,
            "",
            "EDIT",
            WS_TABSTOP
                | ES_READONLY as u32
                | ES_MULTILINE as u32
                | ES_AUTOVSCROLL as u32
                | WS_VSCROLL,
        )?;
        label(window, PROGRESS, "", "msctls_progress32", PBS_MARQUEE)?;
        let ca = crate::embedded::ca()?.unwrap_or(
            std::env::current_exe()?
                .parent()
                .context("Launcher folder")?
                .join("operator-ca.der"),
        );
        if ca.is_file() {
            set(window, CA, ca.to_str().unwrap_or(""));
        }
        // Missing trust material is visible during first setup; prepared releases stay compact.
        owned.advanced = !ca.is_file() || crate::manifest::sha(&get(window, PIN)).is_err();
        fonts(window);
        refresh(window);
        reflow(window);
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
            } else {
                reveal_focus(window);
            }
        }
        Ok(())
    }
}
