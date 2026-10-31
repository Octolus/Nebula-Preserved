"""Explicit local companion/locomotion grants and recovered collection DTOs.

Importing this module starts no listener, game process or connection. Resource
availability is sourced from shipped canonical prefabs, not shop policy.
"""
import json
from pathlib import Path
import time

from wire import ProtocolError
from diagnostic_logging import missing_data


KINDS=('companions','locomotions')


def checked_kind(kind):
    if kind not in KINDS:raise ProtocolError('Unsupported resource kind')
    return kind


def checked_text(value,label,allow_hash=False):
    if not isinstance(value,str) or not value or len(value)>1024 or '\x00' in value:
        raise ProtocolError('Invalid '+label)
    if not allow_hash and '#' in value:raise ProtocolError('Delimiter in '+label)
    return value


class ResourceCatalog:
    def __init__(self,protocol_dir:Path):
        self.path=Path(protocol_dir)/'resource-entitlements.json'
        document=json.loads(self.path.read_text(encoding='utf-8'))
        if document.get('format_version')!=1:raise ProtocolError('Unsupported resource catalog',501)
        self.items={}
        self.conflicts=set()
        groups={}
        for row in document['items']:
            key=(row['kind'],row['item_id'])
            groups.setdefault(key,[]).append(row)
        id_kinds={}
        for kind,item_id in groups:id_kinds.setdefault(item_id,set()).add(kind)
        for key,rows in groups.items():
            row=rows[0]
            kind,item_id=key
            expected_table={'companions':'COMPANIONS','locomotions':'LOCOMOTIONS'}.get(kind)
            expected_prefix={'companions':'02','locomotions':'03'}.get(kind)
            expected_resource='Wardrobe_EAB/'+str(expected_table)+'/'+item_id+'/'+item_id
            valid=(kind in KINDS and len(rows)==1 and len(id_kinds[item_id])==1
                and row.get('grantable') is True and not row.get('conflicts')
                and row.get('table')==expected_table
                and row.get('bundle')==expected_prefix+'/'+item_id.lower()
                and row.get('requested_resource_path')==expected_resource)
            if valid:
                checked_text(item_id,'resource identifier')
                self.items[key]=row
            else:self.conflicts.add(key)

    def resolve(self,kind,item_id):
        checked_kind(kind)
        checked_text(item_id,'resource identifier')
        key=(kind,item_id)
        if key not in self.items:
            missing_data('resource_item_unknown',kind=kind,item_id=item_id)
            raise ProtocolError('Unknown or conflicting shipped resource',404)
        return self.items[key]

    def list(self,kind=None):
        if kind is not None:checked_kind(kind)
        return [self.items[key] for key in sorted(self.items) if kind is None or key[0]==kind]


def collection_response(guid,item_ids):
    """Plain list DTO: no JSON, count, names or nonempty trailing field."""
    checked_text(guid,'session identifier')
    ids=[]
    for item_id in item_ids:
        checked_text(item_id,'resource identifier')
        if item_id not in ids:ids.append(item_id)
    return '#'.join(['true',guid,*ids])


class ResourceEntitlements:
    def __init__(self,store,catalog=None):
        self.store=store
        self.catalog=catalog
        # New table only; shared profile/session and wardrobe schemas remain
        # owned by Store. Module use is explicit and follows Store's transaction.
        with store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS resource_entitlements (
                ps4_id TEXT NOT NULL REFERENCES profiles(ps4_id),
                kind TEXT NOT NULL CHECK(kind IN ('companions','locomotions')),
                item_id TEXT NOT NULL, bundle TEXT NOT NULL,
                asset_path TEXT NOT NULL, display_name TEXT NOT NULL,
                granted_at REAL NOT NULL, PRIMARY KEY(ps4_id,kind,item_id))''')

    def grant(self,ps4_id,kind,item_id,display_name=None):
        checked_kind(kind)
        if self.catalog is None:raise ProtocolError('Resource catalog is required to validate a grant',501)
        row=self.catalog.resolve(kind,item_id)
        label=item_id if display_name is None else checked_text(display_name,'local resource label',allow_hash=True)
        self.store.account(ps4_id)
        with self.store.db:
            self.store.db.execute('''INSERT INTO resource_entitlements
                (ps4_id,kind,item_id,bundle,asset_path,display_name,granted_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(ps4_id,kind,item_id) DO UPDATE SET
                bundle=excluded.bundle,asset_path=excluded.asset_path,
                display_name=CASE WHEN ? THEN excluded.display_name ELSE resource_entitlements.display_name END''',
                (ps4_id,kind,item_id,row['bundle'],row['asset_path'],label,time.time(),display_name is not None))
        return next(row for row in self.list(ps4_id,kind) if row['item_id']==item_id)

    def list(self,ps4_id,kind=None):
        if kind is not None:checked_kind(kind)
        sql='SELECT * FROM resource_entitlements WHERE ps4_id=?'
        params=[ps4_id]
        if kind is not None:
            sql+=' AND kind=?'
            params.append(kind)
        sql+=' ORDER BY kind,item_id'
        rows=[dict(row) for row in self.store.db.execute(sql,params)]
        # When a catalog is supplied, a stale/injected grant cannot bypass its
        # current ambiguity checks. Service can also construct with a catalog.
        if self.catalog is not None:
            for row in rows:self.catalog.resolve(row['kind'],row['item_id'])
        return rows

    def response(self,ps4_id,guid,kind):
        checked_kind(kind)
        self.store.session(guid,ps4_id)
        return collection_response(guid,[row['item_id'] for row in self.list(ps4_id,kind)])

    def purchase_fields(self,ps4_id):
        """Merge these four fields into GetPurchases' existing PurchasesData."""
        fields={kind:[] for kind in KINDS}
        fields.update({kind+'Name':[] for kind in KINDS})
        for row in self.list(ps4_id):
            fields[row['kind']].append(row['item_id'])
            fields[row['kind']+'Name'].append(row['display_name'])
        return fields
