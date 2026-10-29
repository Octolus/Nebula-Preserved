"""Generate an isolated complete source overlay; never edits the input tree."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Nonunique/missing source anchor: ' + old[:90])
    return text.replace(old, new)


def main():
    out = HERE / 'generated'
    out.mkdir(exist_ok=False)
    sources = ['backend/state.py', 'backend/server.py',
               'mirror-server/UnityProject/Assets/Preservation/NebulaInstanceAccounts.cs',
               'mirror-server/UnityProject/Assets/Preservation/NebulaInstanceServer.cs']
    pins = {}
    expected = json.loads((HERE / 'base-pins.json').read_text())
    for path in sources:
        original = (SOURCE / path).read_bytes()
        pins[path] = hashlib.sha256(original).hexdigest()
        if pins[path] != expected[path]:
            raise RuntimeError('Input source pin mismatch: ' + path)
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
    p = out / sources[0]
    t = p.read_text()
    t = replace(t, '        self.import_friend_events()\n        rows =',
                '        self.import_friend_events()\n        selection_authority = getattr(self, "resource_selection_authority", None)\n        rows =')
    t = replace(t, '            granted = resources.list(account["ps4_id"])',
                '            if selection_authority is not None:\n                account["resource_selection_schema"] = 1\n                account.update(selection_authority.snapshot(account["ps4_id"]))\n            granted = resources.list(account["ps4_id"])')
    p.write_text(t)
    p = out / sources[1]
    t = p.read_text()
    t = replace(t, 'from service import Service', 'from service import Service\nfrom resource_selection import SelectionAuthority')
    t = replace(t, '        self.service.instances.advertised_ip =',
                '        self.resource_selections = SelectionAuthority(self.store, self.service.resources)\n        self.store.resource_selection_authority = self.resource_selections\n        self.service.instances.advertised_ip =')
    t = replace(t, '        self.store.export_instance_accounts(self.state_dir)',
                '        self.resource_selections.pump(self.state_dir)\n        self.store.export_instance_accounts(self.state_dir)')
    p.write_text(t)
    p = out / sources[2]
    t = p.read_text()
    t = replace(t, '            public string[] companion_ids;',
                '            public int resource_selection_schema;\n            public string selected_companion, selected_locomotion;\n            public long companion_revision, locomotion_revision;\n            public string[] companion_ids;')
    t = replace(t, '                account.companion_ids = ValidateResources(account.companion_ids);',
                '                account.companion_ids = ValidateResources(account.companion_ids);')
    t = replace(t, '                account.locomotion_ids = ValidateResources(account.locomotion_ids);',
                '''                account.locomotion_ids = ValidateResources(account.locomotion_ids);
                account.selected_companion = account.selected_companion ?? "";
                account.selected_locomotion = account.selected_locomotion ?? "";
                if (account.resource_selection_schema != 1 || account.companion_revision < 0 || account.locomotion_revision < 0 ||
                    account.companion_revision > 9007199254740990L || account.locomotion_revision > 9007199254740990L ||
                    (account.selected_companion != "" && !Array.Exists(account.companion_ids, x => x == account.selected_companion)) ||
                    (account.selected_locomotion != "" && !Array.Exists(account.locomotion_ids, x => x == account.selected_locomotion)))
                    throw new InvalidDataException("invalid_resource_selection_snapshot");''')
    p.write_text(t)
    p = out / sources[3]
    t = p.read_text()
    t = replace(t, '            public string companion = "";',
                '            public string companion = "";\n            public long companionRevision, locomotionRevision;\n            public NebulaResourceSelections.Request resourcePending;')
    t = replace(t, '        private string stateDirectory;',
                '        private NebulaResourceSelections resourceSelections;\n        private string stateDirectory;')
    t = replace(t, '                accounts = new NebulaInstanceAccounts(stateDirectory);',
                '                accounts = new NebulaInstanceAccounts(stateDirectory);\n                resourceSelections = new NebulaResourceSelections(stateDirectory, instanceId, statusOwner);')
    t = replace(t, '            ProcessReseeds();', '            ProcessReseeds();\n            PumpResourceSelections();')
    t = replace(t, '            peer.announced = true;\n            if (!interactionRegistry',
                '            peer.announced = true;\n            Send(peer, Join(17, peer.account.guid, peer.companion));\n            Send(peer, Join(15, peer.account.guid, peer.locomotion));\n            if (!interactionRegistry')
    t = replace(t, 'var entity = new Peer {account = account, netId = nextNetId++, spawned = true, announced = true, inWardrobe = true};',
                'var entity = new Peer {account = account, netId = nextNetId++, spawned = true, announced = true, inWardrobe = true, companion = account.selected_companion, locomotion = account.selected_locomotion, companionRevision = account.companion_revision, locomotionRevision = account.locomotion_revision};')
    t = replace(t, '                    peer.locomotion = f[1]; Broadcast(Join(15, f), peer); return;',
                '                    BeginResourceSelection(peer, "locomotions", f[1]); return;')
    t = replace(t, '                    RequireResource(f[1], peer.account.locomotion_ids);\n                    BeginResourceSelection',
                '                    BeginResourceSelection')
    t = replace(t, '                    peer.companion = f[1]; Broadcast(Join(17, f), peer); return;',
                '                    BeginResourceSelection(peer, "companions", f[1]); return;')
    t = replace(t, '                    RequireResource(f[1], peer.account.companion_ids);\n                    BeginResourceSelection',
                '                    BeginResourceSelection')
    t = replace(t, '                RestorePose(peer);\n                SeedRemotes(peer);',
                '''                peer.companion = account.selected_companion;
                peer.locomotion = account.selected_locomotion;
                peer.companionRevision = account.companion_revision;
                peer.locomotionRevision = account.locomotion_revision;
                RestorePose(peer);
                SeedRemotes(peer);''')
    methods = (HERE / 'server-methods.inc').read_text()
    t = replace(t, '        private void Bound(Peer peer)', methods + '\n        private void Bound(Peer peer)')
    p.write_text(t)
    shutil.copy2(HERE / 'backend/resource_selection.py', out / 'backend/resource_selection.py')
    shutil.copy2(HERE / 'mirror-server/NebulaResourceSelections.cs', out / 'mirror-server/UnityProject/Assets/Preservation/NebulaResourceSelections.cs')
    (out / 'input-pins.json').write_text(json.dumps(pins, sort_keys=True, indent=2) + '\n')
    print(str(out))


if __name__ == '__main__':
    main()
