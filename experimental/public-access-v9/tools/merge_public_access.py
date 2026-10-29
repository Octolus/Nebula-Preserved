"""Deterministically stage the reviewed public-access integration.

The canonical source tree is never modified.  This command verifies exact
base hashes, copies it to a new target, performs bounded exact replacements,
adds the new modules/configuration, and writes a merge receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


BASE_HASHES = {
    "backend/server.py": "7f3ba745d4cc3ee8b622a9de3145095be32e98cb90815b0da3ef0af7607fa411",
    "backend/state.py": "041a262c6249e8ea7d8da5382254be0b3eb1a46b17f6399f7876272df6c8c8fd",
    "backend/service.py": "eed54bd758780f1ee91e2341a02b8d65bf7c75ba350e0ec366a11d0c83e5de10",
    "backend/housing.py": "88056d9a5d43170c02bdc65155cc52c4f7563d7d1b02a268c31e7488afcb1f2d",
    "tools/instance_supervisor.py": "d6357ced2733805582e26f3cb4db90e76d999b50c4c80a8f4b4945e27e4bef37",
}
ECONOMY_ADMIN_SHA256 = "a5f5933c88377429a18d99d61e2b557698268442a51cbfa31119df463a675eff"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected one integration anchor in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    target = args.target.resolve(strict=False)
    stage = Path(__file__).resolve().parents[1]
    economy_stage = stage.parent / "economy/backend/economy_admin.py"
    if target.exists():
        parser.error("target already exists")
    for relative, expected in BASE_HASHES.items():
        actual = sha256(source / relative)
        if actual != expected:
            parser.error(f"base hash mismatch for {relative}: {actual}")
    if not economy_stage.is_file() or sha256(economy_stage) != ECONOMY_ADMIN_SHA256:
        parser.error("reviewed economy administrator stage is absent or changed")
    # Package only runtime inputs.  Copying the entire workspace would pull in
    # Unity's transient Library/cache tree (including Windows path lengths that
    # are not portable) and unrelated evidence.  Every imported backend/tool
    # module, protocol manifest, deploy template, and the pinned Linux build is
    # rooted in the resulting package instead.
    target.mkdir(parents=True)
    ignored = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")
    for relative in ("backend", "tools", "protocol", "deployment/instance-supervisor",
                     "mirror-server/build-linux"):
        origin = source / relative
        if not origin.is_dir():
            parser.error("required runtime directory is absent: " + relative)
        shutil.copytree(origin, target / relative, ignore=ignored)
    for relative in ("mirror-server/build-linux-validation.json",):
        origin = source / relative
        if not origin.is_file():
            parser.error("required runtime file is absent: " + relative)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    server = target / "backend/server.py"
    state = target / "backend/state.py"
    service = target / "backend/service.py"
    housing = target / "backend/housing.py"
    replace_once(server,
        "from interaction_registry import InteractionRegistryPublisher\n",
        "from interaction_registry import InteractionRegistryPublisher\n"
        "from public_access import AccessAuthority, AccessDenied, actor_scope\n")
    replace_once(server,
        "                 core_test_profile=None, managed_instances=False, local_test_identities=False):",
        "                 core_test_profile=None, managed_instances=False, local_test_identities=False,\n"
        "                 public_access=False):")
    replace_once(server,
        "        self.local_test_identities = local_test_identities\n",
        "        self.local_test_identities = local_test_identities\n"
        "        if type(public_access) is not bool:\n"
        "            raise TypeError(\"public_access must be a Boolean\")\n"
        "        self.public_access = public_access\n"
        "        if self.public_access and self.local_test_identities:\n"
        "            raise ValueError(\"Public access and local test identities are mutually exclusive\")\n"
        "        if self.public_access and self.bind_address != \"127.0.0.1\":\n"
        "            raise ValueError(\"Public access HTTP must bind loopback behind the reviewed TLS proxy\")\n")
    replace_once(server,
        "        self.store = Store(state_dir / \"preservation.sqlite3\",\n"
        "                           local_test_identities=self.local_test_identities)\n",
        "        self.store = Store(state_dir / \"preservation.sqlite3\",\n"
        "                           local_test_identities=self.local_test_identities)\n"
        "        self.access = AccessAuthority(self.store.db) if self.public_access else None\n")
    replace_once(server,
        "                                      \"local_test_identities\": self.local_test_identities,\n",
        "                                      \"local_test_identities\": self.local_test_identities,\n"
        "                                      \"public_access\": self.public_access,\n")
    replace_once(server,
        "        try:\n"
        "            response = self.service.dispatch(command, plaintext)\n"
        "            self.publish_state()\n"
        "        except ProtocolError as exc:\n",
        "        try:\n"
        "            if self.access is None:\n"
        "                response = self.service.dispatch(command, plaintext)\n"
        "                self.publish_state()\n"
        "            else:\n"
        "                account = self.access.authenticate(request.headers.get(\"Authorization\"))\n"
        "                with actor_scope(account):\n"
        "                    response = self.service.dispatch(command, plaintext)\n"
        "                    self.publish_state()\n"
        "        except AccessDenied as exc:\n"
        "            self.record(command=command, request_sha256=digest, status=403,\n"
        "                        error_type=type(exc).__name__)\n"
        "            return web.Response(status=403, text=encrypt(\"ERROR\"), content_type=\"text/plain\")\n"
        "        except ProtocolError as exc:\n")
    replace_once(server,
        "    p.add_argument(\"--local-test-identities\", action=\"store_true\",\n"
        "                   help=\"Admit only the two fixed preservation test identities on concrete private endpoints\")\n",
        "    p.add_argument(\"--local-test-identities\", action=\"store_true\",\n"
        "                   help=\"Admit only the two fixed preservation test identities on concrete private endpoints\")\n"
        "    p.add_argument(\"--public-access\", action=\"store_true\",\n"
        "                   help=\"Require per-account credentials; bind loopback behind TLS\")\n")
    replace_once(server,
        "    if a.local_test_identities and not (private_concrete_ipv4(a.bind)\n"
        "                                        and private_concrete_ipv4(a.advertise_ip)):\n"
        "        p.error(\"--local-test-identities requires concrete loopback or RFC1918 bind and advertise addresses\")\n"
        "    return a\n",
        "    if a.local_test_identities and not (private_concrete_ipv4(a.bind)\n"
        "                                        and private_concrete_ipv4(a.advertise_ip)):\n"
        "        p.error(\"--local-test-identities requires concrete loopback or RFC1918 bind and advertise addresses\")\n"
        "    if a.public_access and a.local_test_identities:\n"
        "        p.error(\"--public-access cannot be combined with --local-test-identities\")\n"
        "    if a.public_access and a.bind != \"127.0.0.1\":\n"
        "        p.error(\"--public-access requires --bind 127.0.0.1 behind TLS\")\n"
        "    return a\n")
    replace_once(server,
        "                      core_test_profile=a.core_test_profile, managed_instances=a.managed_instances,\n"
        "                      local_test_identities=a.local_test_identities)\n",
        "                      core_test_profile=a.core_test_profile, managed_instances=a.managed_instances,\n"
        "                      local_test_identities=a.local_test_identities,\n"
        "                      public_access=a.public_access)\n")
    replace_once(state,
        "from test_identity import reserved_id, reserved_name, validate_identity, validate_lookup_username\n",
        "from test_identity import reserved_id, reserved_name, validate_identity, validate_lookup_username\n"
        "from public_access import require_actor\n")
    replace_once(state,
        "    def account(self, ps4_id, username=None, platform=\"StandaloneWindows\"):\n",
        "    def account(self, ps4_id, username=None, platform=\"StandaloneWindows\"):\n"
        "        require_actor(ps4_id)\n")
    replace_once(state,
        "    def bind_session(self, ps4_id, guid):\n",
        "    def bind_session(self, ps4_id, guid):\n"
        "        require_actor(ps4_id)\n")
    replace_once(state,
        "        profile = dict(row)\n"
        "        validate_identity(profile[\"ps4_id\"], profile[\"username\"], self.local_test_identities)\n"
        "        return profile\n",
        "        profile = dict(row)\n"
        "        if ps4_id is not None:\n"
        "            require_actor(profile[\"ps4_id\"])\n"
        "        validate_identity(profile[\"ps4_id\"], profile[\"username\"], self.local_test_identities)\n"
        "        return profile\n")
    replace_once(service,
        "from notifications import NotificationOutbox\n",
        "from notifications import NotificationOutbox\n"
        "from public_access import require_actor\n")
    replace_once(service,
        "        profile = self.store.session(f[0], f[ps4_index] if ps4_index is not None else None)\n"
        "        return f, profile\n",
        "        profile = self.store.session(f[0], f[ps4_index] if ps4_index is not None else None)\n"
        "        require_actor(profile[\"ps4_id\"])\n"
        "        return f, profile\n")
    replace_once(housing,
        "from wire import ProtocolError, json_field\n",
        "from wire import ProtocolError, json_field\n"
        "from public_access import require_actor\n")
    replace_once(housing,
        "        profile = self.store.session(guid)\n",
        "        profile = self.store.session(guid)\n"
        "        require_actor(profile[\"ps4_id\"])\n")
    shutil.copy2(stage / "backend/public_access.py", target / "backend/public_access.py")
    shutil.copy2(stage / "backend/public_access_admin.py", target / "backend/public_access_admin.py")
    economy_admin = target / "backend/economy_admin.py"
    shutil.copy2(economy_stage, economy_admin)
    replace_once(economy_admin,
        'ROOT = Path(__file__).resolve().parents[4] / "outputs" / "nebula-preservation"\n',
        'ROOT = Path(__file__).resolve().parents[1]\n')
    shutil.copy2(stage / "tools/backup_state.py", target / "tools/backup_state.py")
    shutil.copy2(stage / "tools/migrate_public_access.py", target / "tools/migrate_public_access.py")
    config = target / "deployment/instance-supervisor"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("nebula-managed-http.service", "nebula-instance-supervisor.service"):
        shutil.copy2(stage / "config" / name, config / name)
    for name in ("nebula-public.env.example", "nginx-nebula-preservation.conf",
                 "nebula-preservation-backup.service", "nebula-preservation-backup.timer",
                 "nebula-state.conf"):
        shutil.copy2(stage / "config" / name, config / name)
    client_target = target / "client-auth"
    client_target.mkdir(parents=True, exist_ok=False)
    for name in ("NebulaPublicAccess.cpp", "NebulaPublicAccess.h", "CMakeLists.txt",
                 "README.md", "unitywebrequest-get-calls.json"):
        shutil.copy2(stage / "client" / name, client_target / name)
    shutil.copy2(stage / "client/build-static/NebulaPublicAccess.dll",
                 client_target / "NebulaPublicAccess.dll")
    changed = {}
    for relative in ("backend/server.py", "backend/state.py", "backend/service.py",
                     "backend/housing.py", "backend/public_access.py",
                     "backend/public_access_admin.py", "backend/economy_admin.py",
                     "tools/backup_state.py",
                     "tools/migrate_public_access.py"):
        changed[relative] = sha256(target / relative)
    (target / "PUBLIC-ACCESS-MERGE-RECEIPT.json").write_text(json.dumps({
        "format_version": 1, "base_hashes": BASE_HASHES, "changed_hashes": changed,
        "steam_ticket_validation": False,
        "requires_client_authorization_header_and_https": True,
        "economy_admin_stage_sha256": ECONOMY_ADMIN_SHA256,
        "client_auth_manifest_sha256": sha256(client_target / "unitywebrequest-get-calls.json"),
        "client_auth_dll_sha256": sha256(client_target / "NebulaPublicAccess.dll"),
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
