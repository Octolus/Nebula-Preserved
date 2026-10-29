"""Run the unchanged gateway CLI with only its Windows signal lifecycle shim."""
import asyncio
from pathlib import Path
import runpy
import signal
import sys

sys.dont_write_bytecode = True
gateway = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(gateway.parents[3] / 'backend'))
sys.path.insert(0, str(gateway.parent))
if sys.platform == 'win32':
    def add_signal_handler(self, signum, callback, *args):
        signal.signal(signum, lambda *_: self.call_soon_threadsafe(callback, *args))
    asyncio.BaseEventLoop.add_signal_handler = add_signal_handler
sys.argv = [str(gateway), *sys.argv[2:]]
runpy.run_path(str(gateway), run_name='__main__')
