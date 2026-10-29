"""No web application or listener starts: exercise the local refresh lifecycle."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Backend


def drive(coroutine):
    """Run an await chain whose fake boundaries never schedule OS I/O."""
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError('Unexpected real scheduler wait')


class StateRefreshTests(unittest.TestCase):
    def test_startup_exports_and_cleanup_cancels_without_running_listener(self):
        class Task:
            was_cancelled = False
            def cancel(self): self.was_cancelled = True
            def __await__(self):
                if not self.was_cancelled: raise AssertionError('Task not cancelled')
                raise asyncio.CancelledError()
                yield
        task = Task()
        def capture(coroutine):
            coroutine.close()
            return task
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                backend = Backend(root)
                try:
                    with patch('server.asyncio.create_task', capture):
                        await backend.start_maintenance(None)
                    snapshot = json.loads((root/'instance-accounts.json').read_text(encoding='utf-8'))
                    self.assertEqual(snapshot['format_version'], 1)
                    self.assertEqual(snapshot['accounts'], [])
                    self.assertIs(backend.maintenance_task, task)
                finally:
                    await backend.close(None)
                self.assertTrue(task.was_cancelled)
                self.assertIsNone(backend.maintenance_task)
        drive(check())

    def test_transient_refresh_failure_does_not_stop_future_refreshes(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                backend = Backend(Path(directory))
                ticks = 0
                async def tick(_delay):
                    nonlocal ticks
                    ticks += 1
                    if ticks == 3:
                        raise asyncio.CancelledError()
                try:
                    with patch('server.asyncio.sleep', tick), patch.object(backend, 'publish_state', side_effect=[OSError('transient'), None]) as publish:
                        with self.assertRaises(asyncio.CancelledError):
                            await backend.maintain_state()
                        self.assertEqual(publish.call_count, 2)
                    log = [json.loads(line) for line in (Path(directory)/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
                    self.assertEqual([row['error'] for row in log], ['state_refresh_failed'])
                    self.assertEqual(log[0]['error_type'], 'OSError')
                finally:
                    await backend.close(None)
        drive(check())


if __name__ == '__main__': unittest.main()

