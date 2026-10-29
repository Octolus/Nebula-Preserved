"""Explicit operator fixtures; no original computer paths or implicit install."""
import os
from pathlib import Path


def workspace():
    value = os.environ.get('NEBULA_RESEARCH_WORKSPACE')
    if not value:
        raise RuntimeError('Set NEBULA_RESEARCH_WORKSPACE or use run_research.py with --workspace; no private fixtures are shipped')
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError('Research workspace must be an existing operator-supplied fixture directory')
    return path


def output_root():
    return workspace() / 'results'


def game_path(relative=''):
    value = os.environ.get('NEBULA_GAME_DIR')
    if not value:
        raise RuntimeError('This extractor requires an operator-supplied --game-dir / NEBULA_GAME_DIR')
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError('Game installation directory does not exist')
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise RuntimeError('Game input path escaped supplied installation')
    return path
