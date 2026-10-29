"""Print a research plan by default; --execute runs only a curated source tool."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent


def main():
    names = [row['path'] for row in json.loads((HERE / 'INVENTORY.json').read_text())['copied']]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--script', choices=names)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.list:
        print('\n'.join(names))
        return
    if not args.script or not args.workspace:
        parser.error('--script and --workspace are required')
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error('--workspace must be an existing operator fixture directory')
    repository = HERE.parents[1]
    if workspace == repository:
        parser.error('Use a separate fixture workspace, not the primary repository root')
    game = args.game_dir.expanduser().resolve() if args.game_dir else None
    if game and (not game.is_dir() or workspace == game or game in workspace.parents):
        parser.error('Fixture workspace must be outside the supplied game installation')
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    print(json.dumps(dict(script=args.script, workspace=str(workspace), output=str(workspace/'results'),
                         game_input=str(game) if game else None, execute=args.execute), indent=2))
    if not args.execute:
        return
    os.environ['NEBULA_RESEARCH_WORKSPACE'] = str(workspace)
    if game:
        os.environ['NEBULA_GAME_DIR'] = str(game)
    (workspace/'results/protocol').mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(HERE), str(HERE.parent), str(repository/'backend')]
    sys.argv = [str(HERE/args.script), *arguments]
    os.chdir(workspace)
    runpy.run_path(str(HERE/args.script), run_name='__main__')


if __name__ == '__main__':
    main()
