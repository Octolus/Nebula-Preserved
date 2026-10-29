"""Offline local companion/locomotion catalog, grants and listing."""
import argparse
import json
from pathlib import Path

from resources import KINDS,ResourceCatalog,ResourceEntitlements
from state import Store
from wire import ProtocolError


ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path,default=Path('work/server-state'))
    parser.add_argument('--protocol-dir',type=Path,default=ROOT/'protocol')
    commands=parser.add_subparsers(dest='operation',required=True)
    catalog=commands.add_parser('catalog')
    catalog.add_argument('--kind',choices=KINDS)
    grant=commands.add_parser('grant')
    grant.add_argument('account_id')
    grant.add_argument('kind',choices=KINDS)
    grant.add_argument('item_id')
    grant.add_argument('--name',help='Explicit local label; original shop names are unknown')
    listing=commands.add_parser('list')
    listing.add_argument('account_id')
    listing.add_argument('--kind',choices=KINDS)
    args=parser.parse_args()
    store=None
    try:
        source=ResourceCatalog(args.protocol_dir)
        if args.operation=='catalog':
            result=source.list(args.kind)
        else:
            store=Store(args.state_dir/'preservation.sqlite3')
            resources=ResourceEntitlements(store,source)
            if args.operation=='grant':
                result=resources.grant(args.account_id,args.kind,args.item_id,args.name)
            else:result=resources.list(args.account_id,args.kind)
        print(json.dumps(result,ensure_ascii=True,indent=2))
    except (ProtocolError,OSError,ValueError) as exc:
        parser.exit(1,str(exc)+'\n')
    finally:
        if store is not None:store.close()


if __name__=='__main__':main()
