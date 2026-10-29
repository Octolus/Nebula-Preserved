"""Local scene IPC -> single SQLite authority; no public endpoint or account creation."""
import hashlib
import json
import math
from pathlib import Path
import re
import time
from wire import ProtocolError

KINDS = ('companions', 'locomotions')
HEX = re.compile(r'^[0-9a-f]{32}$')
INSTANCE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
ITEM = re.compile(r'^[A-Za-z0-9]{1,128}$')
MAX_REVISION = 2**53 - 2


class SelectionAuthority:
    def __init__(self, store, resources):
        self.store, self.resources = store, resources
        # Only additive migration. No wallet, profile or entitlement initialization.
        with store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS resource_selections (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                kind TEXT NOT NULL CHECK(kind IN ('companions','locomotions')),
                item_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
                updated_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind))''')
            store.db.execute('''CREATE TABLE IF NOT EXISTS resource_selection_receipts (
                request_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                response_json TEXT NOT NULL, processed_at REAL NOT NULL)''')

    def owned(self, actor, kind, item):
        if item == '':
            return True
        try:
            self.resources.catalog.resolve(kind, item)
        except ProtocolError as error:
            if error.status not in (400, 404, 409):
                raise
            return False
        return self.store.db.execute('SELECT 1 FROM resource_entitlements WHERE ps4_id=? AND kind=? AND item_id=?',
                                     (actor, kind, item)).fetchone() is not None

    def selected(self, actor, kind):
        row = self.store.db.execute('SELECT item_id,revision FROM resource_selections WHERE ps4_id=? AND kind=?',
                                    (actor, kind)).fetchone()
        return (row[0], row[1]) if row else ('', 0)

    def snapshot(self, actor):
        """Revocation/catalog invalidation clears selection, never restores on regrant."""
        result = {}
        with self.store.atomic():
            for kind, stem in (('companions', 'companion'), ('locomotions', 'locomotion')):
                item, revision = self.selected(actor, kind)
                if item and not self.owned(actor, kind, item):
                    if revision >= MAX_REVISION:
                        raise ValueError('resource_selection_revision_exhausted')
                    revision += 1
                    item = ''
                    self.store.db.execute('UPDATE resource_selections SET item_id=?,revision=?,updated_at=? WHERE ps4_id=? AND kind=?',
                                          ('', revision, time.time(), actor, kind))
                result['selected_' + stem] = item
                result[stem + '_revision'] = revision
        return result

    @staticmethod
    def validate(value, instance):
        fields = {'format_version', 'request_id', 'guid', 'instance_id', 'instance_owner', 'kind', 'item_id', 'expected_revision', 'created_at', 'expires_at'}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError('resource_selection_schema')
        if (type(value['format_version']) is not int or value['format_version'] != 1
                or not isinstance(value['request_id'], str) or not HEX.fullmatch(value['request_id'])
                or not isinstance(value['guid'], str) or not HEX.fullmatch(value['guid'])
                or not isinstance(value['instance_owner'], str) or not HEX.fullmatch(value['instance_owner'])
                or not isinstance(instance, str) or not INSTANCE.fullmatch(instance)
                or value['instance_id'] != instance or value['kind'] not in KINDS
                or not isinstance(value['item_id'], str)
                or (value['item_id'] and not ITEM.fullmatch(value['item_id']))
                or type(value['expected_revision']) is not int
                or not 0 <= value['expected_revision'] < MAX_REVISION):
            raise ValueError('resource_selection_fields')
        for key in ('created_at', 'expires_at'):
            number = value[key]
            if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                raise ValueError('resource_selection_clock')
        if not 0 < value['expires_at'] - value['created_at'] <= 15:
            raise ValueError('resource_selection_lifetime')

    def current_lease(self, value, now, scene):
        path = self.store.state_dir / 'instances' / value['instance_id'] / 'instance-status.json'
        try:
            if any(p.is_symlink() for p in (path, path.parent, path.parent.parent, self.store.state_dir)) or not 0 < path.stat().st_size <= 65536:
                return False
            status = json.loads(path.read_text(encoding='utf-8-sig'))
            heartbeat = status['heartbeat']
            return (status['instance_id'] == value['instance_id'] and status['owner'] == value['instance_owner']
                    and status['psidglobal'] == scene
                    and status['listening'] is True and status['listener_bound'] is True
                    and type(heartbeat) in (int, float) and math.isfinite(heartbeat)
                    and 0 <= now - heartbeat <= 15)
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def process(self, value, instance, now=None):
        self.validate(value, instance)
        now = time.time() if now is None else now
        payload = json.dumps(value, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.store.atomic():
            old = self.store.db.execute('SELECT digest,response_json FROM resource_selection_receipts WHERE request_id=?',
                                        (value['request_id'],)).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError('resource_selection_replay_conflict')
                return json.loads(old[1])
            response = {'format_version': 1, 'request_id': value['request_id'], 'guid': value['guid'],
                        'instance_id': instance, 'instance_owner': value['instance_owner'], 'kind': value['kind'], 'item_id': value['item_id'],
                        'expected_revision': value['expected_revision'], 'revision': value['expected_revision'],
                        'status': 'rejected', 'reason': 'session_or_allocation_stale'}
            actor_row = self.store.db.execute('''SELECT s.ps4_id,a.psidglobal FROM sessions s JOIN allocations a USING(guid)
                WHERE s.guid=? AND a.instance_id=? AND NOT EXISTS
                (SELECT 1 FROM sessions n WHERE n.ps4_id=s.ps4_id AND
                 (n.created_at>s.created_at OR (n.created_at=s.created_at AND n.guid>s.guid)))''',
                (value['guid'], instance)).fetchone()
            if not value['created_at'] <= now < value['expires_at']:
                response['reason'] = 'request_expired_or_future'
            elif actor_row and not self.current_lease(value, now, actor_row[1]):
                response['reason'] = 'instance_lease_not_current'
            elif actor_row:
                actor = actor_row[0]
                _, revision = self.selected(actor, value['kind'])
                response['revision'] = revision
                if revision != value['expected_revision']:
                    response['reason'] = 'revision_conflict'
                elif not self.owned(actor, value['kind'], value['item_id']):
                    response['reason'] = 'resource_not_owned'
                else:
                    revision += 1
                    self.store.db.execute('''INSERT INTO resource_selections VALUES(?,?,?,?,?)
                        ON CONFLICT(ps4_id,kind) DO UPDATE SET item_id=excluded.item_id,
                        revision=excluded.revision,updated_at=excluded.updated_at''',
                        (actor, value['kind'], value['item_id'], revision, now))
                    response.update(status='committed', reason='', revision=revision)
            self.store.db.execute('INSERT INTO resource_selection_receipts VALUES(?,?,?,?)',
                                  (value['request_id'], digest, json.dumps(response, sort_keys=True), now))
        return response  # caller publishes only after outer commit completes

    def pump(self, root):
        root = Path(root)
        count = 0
        if root.is_symlink() or (root / 'instances').is_symlink():
            raise ValueError('linked_resource_selection_root')
        for folder in sorted((root / 'instances').glob('*/resource-selections')):
            instance = folder.parent.name
            if not INSTANCE.fullmatch(instance) or folder.is_symlink() or folder.parent.is_symlink():
                continue
            for path in sorted(folder.glob('*.request.json'))[:128]:
                if count >= 512:
                    return count
                count += 1
                try:
                    if path.is_symlink() or not 0 < path.stat().st_size <= 4096:
                        continue
                    value = json.loads(path.read_text(encoding='utf-8-sig'))
                    self.validate(value, instance)
                    if path.name != value['request_id'] + '.request.json':
                        continue
                    ack = folder / (value['request_id'] + '.ack.json')
                    if ack.is_symlink():
                        continue
                    response = self.process(value, instance)
                    self.store._publish_snapshot(ack, json.dumps(response, sort_keys=True))
                    # Disconnected senders cannot collect their files. Receipt
                    # remains in SQLite so an immutable replay never reapplies.
                    if time.time() > value['expires_at'] + 30:
                        path.unlink(missing_ok=True)
                        ack.unlink(missing_ok=True)
                except (OSError, ValueError, TypeError, KeyError):
                    continue  # no fabricated success; sender bounded timeout
        return count
