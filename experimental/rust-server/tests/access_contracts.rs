use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use nebula_preserved_server::{access::authenticate, state::State};
#[test]
fn credentials_bind_account_and_revocation_persists() {
    let folder = tempfile::tempdir().unwrap();
    let state = State::open(folder.path(), folder.path()).unwrap();
    nebula_preserved_server::access::initialize(&state).unwrap();
    let account = "76561190000000001";
    let token = "a".repeat(43);
    let salt = [3u8; 16];
    let mut verifier = [0; 32];
    scrypt::scrypt(
        token.as_bytes(),
        &salt,
        &scrypt::Params::new(15, 8, 1, 32).unwrap(),
        &mut verifier,
    )
    .unwrap();
    {
        let db = state.connection().unwrap();
        db.execute("INSERT INTO profiles(ps4_id,username,platform,created_at) VALUES(?,?,'StandaloneWindows',1)",[account,"SyntheticCredentialUser"]).unwrap();
        db.execute("INSERT INTO public_access_credentials(ps4_id,salt,verifier,created_at) VALUES(?,?,?,1)",rusqlite::params![account,&salt,&verifier]).unwrap();
    }
    let authorization = format!(
        "Nebula-Account-v1 {}.{token}",
        URL_SAFE_NO_PAD.encode(account)
    );
    assert_eq!(authenticate(&state, Some(&authorization)).unwrap(), account);
    assert_eq!(authenticate(&state, Some(&authorization)).unwrap(), account);
    assert_eq!(authenticate(&state, None).unwrap_err().status, 403);
    assert_eq!(
        authenticate(
            &state,
            Some(&authorization.replace(&token, &"b".repeat(43)))
        )
        .unwrap_err()
        .status,
        403
    );
    state
        .connection()
        .unwrap()
        .execute("UPDATE public_access_credentials SET revoked_at=2", [])
        .unwrap();
    drop(state);
    let reopened = State::open(folder.path(), folder.path()).unwrap();
    assert_eq!(
        authenticate(&reopened, Some(&authorization))
            .unwrap_err()
            .status,
        403
    );
}
#[test]
fn malformed_credentials_fail_without_account_creation() {
    let folder = tempfile::tempdir().unwrap();
    let state = State::open(folder.path(), folder.path()).unwrap();
    for value in [
        "",
        "Basic Zm9v",
        "Nebula-Account-v1 .",
        "Nebula-Account-v1 a.b.c",
        "Nebula-Account-v1 76561190000000001.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ] {
        assert_eq!(authenticate(&state, Some(value)).unwrap_err().status, 403);
    }
    let count: i64 = state
        .connection()
        .unwrap()
        .query_row("SELECT count(*) FROM profiles", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 0);
}
