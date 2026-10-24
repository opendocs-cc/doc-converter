"""
DOCX → PDF with LibreOffice, kept running.

Starting LibreOffice takes longer than converting a typical document, and
two LibreOffice processes can't share a user profile, which is why the
service used to convert one document at a time. Each worker here is an
unoserver process (https://github.com/unoconv/unoserver) that drives its
own LibreOffice with its own profile, so conversions skip the startup and
run in parallel. A worker is restarted after a set number of conversions
(LibreOffice's memory grows over time) and after any failure or timeout.

The PDF is the same either way: unoserver runs the same export filter
(``writer_pdf_Export``, default options) as ``soffice --convert-to pdf``.

When no worker is running (unoserver isn't installed, e.g. outside the
Docker image, or every worker is restarting), a conversion starts
LibreOffice itself with a throwaway profile. Busy workers are waited for:
starting extra LibreOffices under load would only fight for the same CPUs
and memory. At most as many one-off conversions run as there are workers.
"""

from __future__ import annotations

import asyncio
import http.client
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
import xmlrpc.client
from typing import Optional

logger = logging.getLogger("converter.libreoffice")

# unoserver needs LibreOffice's Python bindings (python3-uno), which belong
# to the system Python rather than the app's; the Dockerfile installs it
# into this directory for /usr/bin/python3.
UNOSERVER_PATH = os.getenv("UNOSERVER_PATH", "/opt/unoserver")
SYSTEM_PYTHON = os.getenv("UNOSERVER_PYTHON", "/usr/bin/python3")
BASE_PORT = int(os.getenv("LIBREOFFICE_BASE_PORT", "2100"))
STARTUP_TIMEOUT = 90.0


class ConversionError(RuntimeError):
    pass


def unoserver_available() -> bool:
    return os.path.exists(SYSTEM_PYTHON) and os.path.isdir(os.path.join(UNOSERVER_PATH, "unoserver"))


# ---------------------------------------------------------------------------
# One-shot conversion (no worker)
# ---------------------------------------------------------------------------

def convert_oneshot(docx: bytes, timeout: float = 60.0) -> bytes:
    """Start LibreOffice for this one document, with its own profile."""
    work = tempfile.mkdtemp(prefix="opendocs_convert_")
    try:
        docx_path = os.path.join(work, "document.docx")
        pdf_path = os.path.join(work, "document.pdf")
        with open(docx_path, "wb") as f:
            f.write(docx)
        result = subprocess.run(
            ["soffice", "--headless", "--norestore",
             f"-env:UserInstallation=file://{os.path.join(work, 'profile')}",
             "--convert-to", "pdf", "--outdir", work, docx_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise ConversionError(
                f"LibreOffice conversion failed (exit {result.returncode}): {result.stderr.strip()}")
        if not os.path.exists(pdf_path):
            raise ConversionError(
                "LibreOffice ran but no PDF was produced. "
                f"stdout: {result.stdout.strip()}, stderr: {result.stderr.strip()}")
        with open(pdf_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = http.client.HTTPConnection(host, timeout=self._timeout)
        self._connection = host, conn
        return conn


class Worker:
    """One unoserver process and the LibreOffice it drives."""

    def __init__(self, index: int, *, conversion_timeout: float):
        self.index = index
        self.port = BASE_PORT + 2 * index
        self.uno_port = BASE_PORT + 2 * index + 1
        self.profile = os.path.join(tempfile.gettempdir(), f"opendocs-libreoffice-{index}")
        self.pid_file = os.path.join(tempfile.gettempdir(), f"opendocs-libreoffice-{index}.pid")
        self.conversion_timeout = conversion_timeout
        self.conversions = 0
        self._process: Optional[subprocess.Popen] = None

    def _proxy(self, timeout: float) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"http://127.0.0.1:{self.port}", allow_none=True,
                                         transport=_TimeoutTransport(timeout))

    def start(self) -> None:
        """Start LibreOffice (blocking) and wait until it takes requests."""
        self.stop()
        shutil.rmtree(self.profile, ignore_errors=True)
        self._process = subprocess.Popen(
            [SYSTEM_PYTHON, "-m", "unoserver.server",
             "--interface", "127.0.0.1", "--uno-interface", "127.0.0.1",
             "--port", str(self.port), "--uno-port", str(self.uno_port),
             "--user-installation", self.profile,
             "--libreoffice-pid-file", self.pid_file,
             # unoserver stops LibreOffice and exits if one conversion hangs.
             "--conversion-timeout", str(int(self.conversion_timeout)),
             "--quiet"],
            env={**os.environ, "PYTHONPATH": UNOSERVER_PATH},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise ConversionError(f"LibreOffice worker {self.index} exited during startup")
            try:
                self._proxy(5).info()
                self.conversions = 0
                return
            except (OSError, xmlrpc.client.Error):
                time.sleep(0.2)
        self.stop()
        raise ConversionError(f"LibreOffice worker {self.index} did not start in time")

    def convert(self, docx: bytes) -> bytes:
        result = self._proxy(self.conversion_timeout + 5).convert(
            None, xmlrpc.client.Binary(docx), None, "pdf", None, [], True, None, None)
        self.conversions += 1
        data = result.data if isinstance(result, xmlrpc.client.Binary) else result
        if not data or not data.startswith(b"%PDF"):
            raise ConversionError("LibreOffice returned no PDF")
        return data

    def stop(self) -> None:
        """Stop unoserver and the LibreOffice it started."""
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
        # LibreOffice can outlive unoserver (it detaches); kill it by pid.
        try:
            with open(self.pid_file) as f:
                os.kill(int(f.read().strip()), signal.SIGKILL)
        except (OSError, ValueError):
            pass
        try:
            os.unlink(self.pid_file)
        except OSError:
            pass


class LibreOfficePool:
    """Hands each conversion to an idle worker."""

    def __init__(self, size: int, *, restart_after: int = 200, conversion_timeout: float = 60.0):
        self.size = max(1, size)
        self.restart_after = max(1, restart_after)
        self.conversion_timeout = conversion_timeout
        self.workers = [Worker(i, conversion_timeout=conversion_timeout) for i in range(self.size)]
        self.enabled = unoserver_available()
        self._idle: asyncio.Queue[Worker] = asyncio.Queue()
        self._alive = 0  # workers running, busy or idle
        self._oneshots = asyncio.Semaphore(self.size)
        self._tasks: set[asyncio.Task] = set()

    @property
    def ready(self) -> int:
        return self._idle.qsize()

    async def start(self) -> None:
        if not self.enabled:
            logger.warning("unoserver not found; each conversion starts LibreOffice")
            return
        for worker in self.workers:
            self._spawn(self._bring_up(worker))

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*(asyncio.to_thread(w.stop) for w in self.workers))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _bring_up(self, worker: Worker) -> None:
        """(Re)start a worker in the background, then offer it for work."""
        for attempt in range(5):
            try:
                await asyncio.to_thread(worker.start)
                self._alive += 1
                self._idle.put_nowait(worker)
                return
            except Exception as exc:
                logger.error("LibreOffice worker %s failed to start: %s", worker.index, exc)
                await asyncio.sleep(min(30, 2 ** attempt))
        logger.error("LibreOffice worker %s gave up; conversions start LibreOffice instead", worker.index)

    async def _oneshot(self, docx: bytes) -> bytes:
        async with self._oneshots:
            return await asyncio.to_thread(convert_oneshot, docx, self.conversion_timeout)

    async def convert(self, docx: bytes) -> bytes:
        worker = None
        if self.enabled:
            # Wait for a busy worker (as long as a conversion may take), but
            # only briefly while every worker is (re)starting.
            wait = 2 * self.conversion_timeout if self._alive else 10.0
            try:
                worker = await asyncio.wait_for(self._idle.get(), timeout=wait)
            except asyncio.TimeoutError:
                worker = None
        if worker is None:
            return await self._oneshot(docx)
        try:
            pdf = await asyncio.to_thread(worker.convert, docx)
        except Exception as exc:
            logger.warning("LibreOffice worker %s failed (%s); restarting it", worker.index, exc)
            self._retire(worker)
            # Once more on a fresh LibreOffice, in case the worker was at fault.
            return await self._oneshot(docx)
        if worker.conversions >= self.restart_after:
            self._retire(worker)
        else:
            self._idle.put_nowait(worker)
        return pdf

    def _retire(self, worker: Worker) -> None:
        """Restart ``worker`` in the background; it rejoins when ready."""
        self._alive -= 1
        self._spawn(self._bring_up(worker))
