# Worker Thread & Clean Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-action thread spawning with a single shared worker queue, and add clean shutdown via StreamController's AppQuit signal.

**Architecture:** A single daemon worker thread owned by `LgMonitorControls` drains a `queue.Queue` of callables. All actions submit work via `plugin_base.enqueue()` instead of spawning threads. On shutdown, the AppQuit signal handler sets a stop event, kills any in-flight ddcutil subprocess, clears the queue, and joins the worker thread.

**Tech Stack:** Python threading, queue.Queue, subprocess.Popen, StreamController signals

---

### Task 1: Add subprocess tracking and shutdown to ddcutil.py

**Files:**
- Modify: `ddcutil.py:84-95` (`_run` function)
- Test: `tests/test_ddcutil.py`

- [ ] **Step 1: Write failing tests for shutdown behavior**

In `tests/test_ddcutil.py`, add:

```python
from ddcutil import shutdown, _shutting_down, _current_process


class TestShutdown:
    def setup_method(self):
        """Reset shutdown state between tests."""
        import ddcutil
        ddcutil._shutting_down = False
        ddcutil._current_process = None

    def test_shutdown_sets_flag(self):
        shutdown()
        assert _shutting_down is True

    def test_run_returns_failure_after_shutdown(self):
        shutdown()
        assert getvcp(1, VCP_BRIGHTNESS) is None
        assert setvcp(1, VCP_BRIGHTNESS, 50) is False

    def test_shutdown_kills_current_process(self):
        """Verify shutdown kills a tracked subprocess."""
        import ddcutil
        from unittest.mock import MagicMock

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        ddcutil._current_process = mock_proc
        shutdown()
        mock_proc.kill.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ddcutil.py::TestShutdown -v`
Expected: FAIL — `shutdown` not importable

- [ ] **Step 3: Implement subprocess tracking and shutdown in ddcutil.py**

Replace `_run` and add shutdown support. Changes to `ddcutil.py`:

Add module-level state after `_lock` (line 26):

```python
_shutting_down: bool = False
_current_process: subprocess.Popen[str] | None = None
```

Replace `_run` function (lines 84-95) with:

```python
def _run(args: list[str], timeout: float = 3.0) -> subprocess.CompletedProcess[str]:
    """Run a host command with the I2C lock held."""
    global _current_process
    if _shutting_down:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
    with _lock:
        if _shutting_down:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        proc = subprocess.Popen(
            _HOST_PREFIX + args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            cwd=_HOME_DIR,
        )
        _current_process = proc
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(
                args=proc.args, returncode=proc.returncode, stdout=stdout, stderr=stderr
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        finally:
            _current_process = None
```

Add shutdown function at the end of the module:

```python
def shutdown() -> None:
    """Signal all ddcutil operations to stop. Kills in-flight subprocess."""
    global _shutting_down
    _shutting_down = True
    proc = _current_process
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ddcutil.py -v`
Expected: All tests PASS (including new TestShutdown)

- [ ] **Step 5: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add ddcutil.py tests/test_ddcutil.py
git commit -m "feat: add subprocess tracking and shutdown to ddcutil"
```

---

### Task 2: Add worker queue and thread to the plugin

**Files:**
- Modify: `main.py:1-7` (imports), `main.py:53-63` (`__init__`), `main.py:164-175` (`refresh_all`)

- [ ] **Step 1: Add queue imports and worker thread to LgMonitorControls.__init__**

Add `import queue` to the imports in `main.py` (line 6, after `threading`).

In `LgMonitorControls.__init__`, after `self._refresh_lock = threading.Lock()` (line 63), add:

```python
self._work_queue: queue.Queue = queue.Queue()
self._stop = threading.Event()
self._worker = threading.Thread(target=self._worker_loop, daemon=True)
self._worker.start()
```

- [ ] **Step 2: Add the worker loop method**

Add after `set_last_input` method (after line 148):

```python
def _worker_loop(self) -> None:
    """Single worker thread that drains the work queue."""
    while not self._stop.is_set():
        try:
            fn, args = self._work_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if self._stop.is_set():
            break
        try:
            fn(*args)
        except Exception:
            log.debug("Worker task failed: %s", fn.__name__, exc_info=True)
```

- [ ] **Step 3: Add enqueue method**

Add after `_worker_loop`:

```python
def enqueue(self, fn, *args) -> None:
    """Submit work to the shared worker thread."""
    if not self._stop.is_set():
        self._work_queue.put((fn, args))
```

- [ ] **Step 4: Change refresh_all to enqueue instead of spawning a thread**

Replace `refresh_all` and `_do_refresh_all` (lines 164-175) with:

```python
def refresh_all(self) -> None:
    """Enqueue a refresh of all active actions."""
    self.enqueue(self._do_refresh_all)

def _do_refresh_all(self) -> None:
    with self._refresh_lock:
        actions = list(self._active_actions)
    for action in actions:
        try:
            action._poll_display()
        except Exception:
            log.debug("Refresh failed for %s", type(action).__name__, exc_info=True)
```

- [ ] **Step 5: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All checks passed

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: add shared worker queue to plugin"
```

---

### Task 3: Wire actions to use the worker queue

**Files:**
- Modify: `action_base.py:59-60` (`_run_threaded`)

- [ ] **Step 1: Change _run_threaded to enqueue**

Replace `_run_threaded` in `action_base.py` (lines 59-60):

```python
def _run_threaded(self, target: Callable[..., Any], *args: Any) -> None:
    self.plugin_base.enqueue(target, *args)  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All checks passed

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add action_base.py
git commit -m "feat: wire actions to shared worker queue"
```

---

### Task 4: Add AppQuit shutdown handler

**Files:**
- Modify: `main.py` (imports and `__init__`)

- [ ] **Step 1: Add AppQuit signal import**

Add to imports in `main.py` (after the `from src.backend` imports):

```python
from src.Signals.Signals import Signals
import GtkHelper.GLib as gl
```

Note: The exact import path for `gl.signal_manager` needs verification. StreamController uses `gl.signal_manager.connect_signal(signal=Signals.AppQuit, callback=...)`. Check the available import path. If `GtkHelper.GLib` doesn't exist, try:

```python
import globals as gl
```

This import is Flatpak-only and will fail in tests/local dev. Wrap in try/except:

```python
try:
    from src.Signals.Signals import Signals
    import globals as gl
    _HAS_SIGNALS = True
except ImportError:
    _HAS_SIGNALS = False
```

- [ ] **Step 2: Register AppQuit handler in __init__**

At the end of `__init__`, after `self.register(...)` (line 142), add:

```python
if _HAS_SIGNALS:
    try:
        gl.signal_manager.connect_signal(
            signal=Signals.AppQuit,
            callback=self._on_app_quit,
        )
    except Exception:
        log.debug("Could not register AppQuit handler", exc_info=True)
```

- [ ] **Step 3: Add _on_app_quit method**

Add after `enqueue`:

```python
def _on_app_quit(self, *args) -> None:
    """Clean shutdown: stop worker, kill in-flight subprocess."""
    from . import ddcutil
    self._stop.set()
    ddcutil.shutdown()
    # Drain remaining items
    while not self._work_queue.empty():
        try:
            self._work_queue.get_nowait()
        except queue.Empty:
            break
    self._worker.join(timeout=2.0)
```

- [ ] **Step 4: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All checks passed

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS (AppQuit import is guarded by try/except)

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: add AppQuit shutdown handler for clean exit"
```

---

### Task 5: Remove unused threading import from action_base.py

**Files:**
- Modify: `action_base.py:1-8` (imports)

- [ ] **Step 1: Remove threading import**

`action_base.py` no longer spawns threads directly. Remove `import threading` (line 6) and the `threading.Lock` usage in `_init_polling` (line 23).

Wait — `_poll_lock` still uses `threading.Lock`. Keep the import. Skip this task.

Actually, `_poll_lock` is still needed for `_should_poll` and `_poll_done` synchronization. The `threading` import stays. **Delete this task.**

---

### Task 5 (revised): Manual integration test

- [ ] **Step 1: Restart StreamController with the updated plugin**

Clear caches and restart:

```bash
find ~/.var/app/com.core447.StreamController/data/plugins/me_tysmith_LgMonitorControls -type d -name __pycache__ -exec rm -rf {} +
# Restart StreamController via the app
```

- [ ] **Step 2: Verify buttons work**

- Press each button type (InputSwitch, PBP, Brightness, etc.)
- Confirm actions execute and UI updates correctly
- Check that only one ddcutil process runs at a time (no parallel calls)

- [ ] **Step 3: Verify clean shutdown**

- Close StreamController
- Confirm it exits within 2-3 seconds (no 5+ second hang)
- No "not responding" dialog

- [ ] **Step 4: Commit all changes together if needed**

```bash
git add -A
git commit -m "feat: single worker thread with clean AppQuit shutdown"
```
