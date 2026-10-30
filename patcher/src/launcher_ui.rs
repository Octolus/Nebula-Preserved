//! Desktop-independent launcher state and layout; no files, network or input.
pub const SERVER: i32 = 101;
pub const GAME: i32 = 102;
pub const ACCOUNT: i32 = 103;
pub const CA: i32 = 104;
pub const PIN: i32 = 105;
pub const DETAILS: i32 = 106;
pub const BROWSE: i32 = 201;
pub const SCAN: i32 = 202;
pub const IMPORT: i32 = 203;
pub const START: i32 = 204;
pub const RESET: i32 = 205;
pub const PICK_ACCOUNT: i32 = 206;
pub const PICK_CA: i32 = 207;
pub const CHECK: i32 = 208;
pub const ADVANCED: i32 = 209;
pub const TOGGLE_DETAILS: i32 = 210;
pub const SYSTEM_TRUST: i32 = 211;
pub const TITLE: i32 = 301;
pub const SUBTITLE: i32 = 302;
pub const NOTICE: i32 = 303;
pub const GAME_TITLE: i32 = 304;
pub const GAME_HELP: i32 = 305;
pub const SERVER_TITLE: i32 = 306;
pub const SERVER_HELP: i32 = 307;
pub const ACCOUNT_LABEL: i32 = 308;
pub const CERT_LABEL: i32 = 309;
pub const PIN_LABEL: i32 = 310;
pub const CERT_HELP: i32 = 311;
pub const NEXT: i32 = 312;
pub const NEXT_HELP: i32 = 313;
pub const ACTIVITY: i32 = 314;
pub const PROGRESS: i32 = 315;

#[derive(Default)]
pub struct Flow {
    pub game_ready: bool,
    pub verified_origin: Option<String>,
    pub bundle_available: bool,
    pub busy: bool,
}
impl Flow {
    pub fn can_start(&self) -> bool {
        !self.busy && self.game_ready && self.verified_origin.is_some() && self.bundle_available
    }
    pub fn next(&self) -> (&'static str, &'static str) {
        if self.busy {
            ("Working…", "Please let the current check or patch finish.")
        } else if !self.game_ready {
            (
                "Find your game",
                "Choose Nebula Realms.exe, or search your Steam libraries.",
            )
        } else if self.verified_origin.is_none() {
            (
                "Connect your account",
                "Save your connection below, or check an existing saved connection.",
            )
        } else if !self.bundle_available {
            ("A player release is needed", "This source build has no reviewed patch bundle. Ask the server owner for the player launcher.")
        } else {
            ("Ready to patch and play", "Start checks the game, server and patch again, keeps backups, then opens the game.")
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Rect(pub i32, pub i32, pub i32, pub i32);
impl Rect {
    pub fn scaled(self, dpi: u32, scroll: i32) -> Self {
        let s = |n: i32| (n * dpi as i32 + if n < 0 { -48 } else { 48 }) / 96;
        Self(s(self.0), s(self.1 - scroll), s(self.2), s(self.3))
    }
}
pub struct Layout {
    pub controls: Vec<(i32, Rect)>,
    pub cards: [Rect; 2],
    pub height: i32,
}
pub fn layout(width: i32, advanced: bool, details: bool) -> Layout {
    let width = width.max(540);
    let right = width - 44;
    let inner = width - 88;
    let extra = if advanced { 226 } else { 0 };
    let bottom = 480 + extra;
    let mut controls = vec![
        (TITLE, Rect(28, 22, width - 56, 36)),
        (SUBTITLE, Rect(28, 62, width - 56, 24)),
        (NOTICE, Rect(28, 96, width - 56, 34)),
        (GAME_TITLE, Rect(44, 154, inner, 26)),
        (GAME_HELP, Rect(44, 184, inner, 22)),
        (GAME, Rect(44, 212, inner - 218, 34)),
        (SCAN, Rect(right - 208, 212, 94, 34)),
        (BROWSE, Rect(right - 104, 212, 104, 34)),
        (SERVER_TITLE, Rect(44, 286, inner, 26)),
        (SERVER_HELP, Rect(44, 316, inner, 22)),
        (SERVER, Rect(44, 344, inner - 146, 34)),
        (CHECK, Rect(right - 136, 344, 136, 34)),
        (ACCOUNT_LABEL, Rect(44, 392, inner, 22)),
        (ACCOUNT, Rect(44, 420, inner - 122, 34)),
        (PICK_ACCOUNT, Rect(right - 112, 420, 112, 34)),
        (ADVANCED, Rect(44, bottom, 196, 34)),
        (IMPORT, Rect(right - 154, bottom, 154, 34)),
        (NEXT, Rect(28, bottom + 68, width - 286, 28)),
        (NEXT_HELP, Rect(28, bottom + 114, width - 56, 36)),
        (START, Rect(width - 234, bottom + 62, 206, 44)),
        (ACTIVITY, Rect(28, bottom + 156, width - 56, 24)),
        (PROGRESS, Rect(28, bottom + 184, width - 56, 5)),
        (TOGGLE_DETAILS, Rect(28, bottom + 202, 192, 30)),
    ];
    if advanced {
        controls.extend([
            (SYSTEM_TRUST, Rect(44, 478, inner, 30)),
            (CERT_LABEL, Rect(44, 522, inner, 22)),
            (CA, Rect(44, 550, inner - 122, 34)),
            (PICK_CA, Rect(right - 112, 550, 112, 34)),
            (PIN_LABEL, Rect(44, 596, inner, 22)),
            (PIN, Rect(44, 624, inner, 34)),
            (CERT_HELP, Rect(44, 668, inner - 182, 30)),
            (RESET, Rect(right - 172, 668, 172, 30)),
        ]);
    }
    if details {
        controls.push((DETAILS, Rect(28, bottom + 244, width - 56, 126)));
    }
    Layout {
        controls,
        cards: [
            Rect(28, 140, width - 56, 122),
            Rect(28, 272, width - 56, bottom - 272 + 50),
        ],
        height: bottom + if details { 398 } else { 260 },
    }
}
pub fn scroll_position(current: i32, delta: i32, content: i32, viewport: i32) -> i32 {
    current
        .saturating_add(delta)
        .clamp(0, (content - viewport).max(0))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn launch_requires_every_prerequisite_and_no_active_job() {
        for bits in 0..16 {
            let flow = Flow {
                game_ready: bits & 1 != 0,
                verified_origin: (bits & 2 != 0).then(|| "https://play.example.org:8444".into()),
                bundle_available: bits & 4 != 0,
                busy: bits & 8 != 0,
            };
            assert_eq!(flow.can_start(), bits == 7);
        }
    }
    #[test]
    fn changing_server_or_resetting_connection_blocks_launch() {
        let mut flow = Flow {
            game_ready: true,
            verified_origin: Some("saved".into()),
            bundle_available: true,
            busy: false,
        };
        assert!(flow.can_start());
        flow.verified_origin = None;
        assert!(!flow.can_start());
        assert_eq!(flow.next().0, "Connect your account");
    }
    #[test]
    fn development_build_explains_why_play_is_unavailable() {
        let flow = Flow {
            game_ready: true,
            verified_origin: Some("saved".into()),
            ..Flow::default()
        };
        assert_eq!(flow.next().0, "A player release is needed");
        assert!(!flow.can_start());
    }
    #[test]
    fn layout_contains_unique_nonoverlapping_controls_at_supported_widths() {
        for width in [540, 620, 760, 960, 1280] {
            for advanced in [false, true] {
                for details in [false, true] {
                    let view = layout(width, advanced, details);
                    let mut ids = std::collections::BTreeSet::new();
                    for (id, r) in &view.controls {
                        assert!(ids.insert(id));
                        assert!(r.0 >= 0 && r.1 >= 0 && r.2 > 0 && r.3 > 0);
                        assert!(r.0 + r.2 <= width && r.1 + r.3 <= view.height, "{id}");
                    }
                    for (index, (a, x)) in view.controls.iter().enumerate() {
                        for (b, y) in &view.controls[index + 1..] {
                            assert!(
                                x.0 + x.2 <= y.0
                                    || y.0 + y.2 <= x.0
                                    || x.1 + x.3 <= y.1
                                    || y.1 + y.3 <= x.1,
                                "controls overlap: {a}/{b}"
                            );
                        }
                    }
                }
            }
        }
    }
    #[test]
    fn scaling_and_scrolling_keep_the_last_action_reachable() {
        for dpi in [96, 120, 144, 192, 288] {
            let view = layout(620, true, true);
            let scroll = scroll_position(0, i32::MAX, view.height, 360);
            let last = view
                .controls
                .iter()
                .find(|(id, _)| *id == DETAILS)
                .unwrap()
                .1;
            let scaled = last.scaled(dpi, scroll);
            assert!(scaled.1 >= 0 && scaled.1 + scaled.3 <= 360 * dpi as i32 / 96);
            assert_eq!(scroll_position(scroll, -i32::MAX, view.height, 360), 0);
        }
    }
}
