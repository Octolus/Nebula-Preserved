"""Offline first-start state admission; existing unmigrated databases require review."""
from pathlib import Path
import sys

sys.path.insert(0, '/opt/nebula/backend')
from public_access import AccessAuthority, migrate
from state import Store

root = Path('/var/lib/nebula')
database = root / 'preservation.sqlite3'
fresh = not database.exists()
store = Store(database)
try:
    if fresh:
        migrate(store.db)
    authority = AccessAuthority(store.db)
    key = Path('/operator/account-operator.key').read_bytes()
    if not store.db.execute('SELECT 1 FROM public_access_operator').fetchone():
        if not fresh:
            raise RuntimeError('Existing state needs explicit operator-key initialization')
        authority.initialize_operator(key)
    else:
        authority.verify_operator(key)
    if store.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise RuntimeError('State integrity check failed')
finally:
    store.close()
print('Public-access state and operator authority verified')
