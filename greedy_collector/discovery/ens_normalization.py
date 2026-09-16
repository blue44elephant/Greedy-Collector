"""Local ENSIP-15 bridge. Never resolves ENS, accesses a DB, or starts at import.

The repository-local JS reference is authoritative. No Python Unicode transforms.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event, Lock, Thread
from time import monotonic

PACKAGE = "@adraffy/ens-normalize"
VERSION = "1.11.1"
UNICODE_VERSION = "17.0.0"
MAX_NAME_BYTES = 2048
MAX_STDOUT_BYTES = 16384
MAX_STDERR_BYTES = 4096
TIMEOUT_SECONDS = 4.0
_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _ROOT / "scripts" / "ens_normalize.mjs"
_NODE_FLAGS = ("--disable-proto=throw",)

_MESSAGES = {
    "normalizer_unavailable": "ENS normalization capability unavailable.",
    "invalid_ens_name": "The value is not a supported ENS name.",
    "normalizer_timeout": "ENS normalization timed out.",
    "normalizer_protocol_error": "ENS normalization could not be completed.",
}


class EnsNormalizationError(ValueError):
    """Fixed public category/message; never includes input, paths or stderr."""

    def __init__(self, error_type):
        self.error_type = error_type if isinstance(error_type, str) and error_type in _MESSAGES else "normalizer_protocol_error"
        super().__init__(_MESSAGES[self.error_type])


def _environment():
    # Absolute node.exe needs only Windows' OS location. No PATH, HOME, NODE_*,
    # provider keys, npm settings, preload options or user profile is inherited.
    if os.name == "nt":
        return {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    return {}


@lru_cache(maxsize=1)
def _node_executable():
    # Operator PATH is consulted only for discovery of a fixed executable name.
    # No relative/current-directory entries, PATHEXT commands or caller paths.
    name = "node.exe" if os.name == "nt" else "node"
    for directory in os.get_exec_path():
        if not directory or not Path(directory).is_absolute():
            continue
        candidate = Path(directory) / name
        try:
            if Path(directory).resolve() in (_ROOT, Path.cwd()):
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and shutil.which(str(resolved)):
                return str(resolved)
        except OSError:
            continue
    raise EnsNormalizationError("normalizer_unavailable")


def _run(payload):
    """Drain both pipes concurrently, retaining at most the explicit caps.

    communicate(capture_output) would buffer unbounded dependency output. A
    bounded writer thread also prevents a non-reading child from blocking stdin.
    """
    argv = [_node_executable(), *_NODE_FLAGS, str(_HELPER)]
    deadline = monotonic() + TIMEOUT_SECONDS
    try:
        process = subprocess.Popen(
            argv, shell=False, cwd=_ROOT, env=_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, ValueError):
        raise EnsNormalizationError("normalizer_unavailable") from None

    overflow, io_error = Event(), Event()
    stdout, stderr = bytearray(), bytearray()

    def stop():
        try:
            process.kill()
        except OSError:
            pass

    def read(pipe, target, cap):
        try:
            while chunk := pipe.read(1024):
                room = cap - len(target)
                target.extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()
                    stop()
                    break
        except (OSError, ValueError):
            io_error.set()
        finally:
            pipe.close()

    def write():
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (OSError, ValueError):
            io_error.set()
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                io_error.set()

    workers = [
        Thread(target=read, args=(process.stdout, stdout, MAX_STDOUT_BYTES), daemon=True),
        Thread(target=read, args=(process.stderr, stderr, MAX_STDERR_BYTES), daemon=True),
        Thread(target=write, daemon=True),
    ]
    timed_out = False
    try:
        for worker in workers:
            worker.start()
        try:
            process.wait(timeout=max(0, deadline - monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            stop()
    finally:
        if process.poll() is None:
            stop()
        try:
            process.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            raise EnsNormalizationError("normalizer_timeout") from None
        # Allow bounded pipe cleanup after termination, including on Windows.
        cleanup_deadline = monotonic() + 1
        for worker in workers:
            worker.join(timeout=max(0, cleanup_deadline - monotonic()))
    if timed_out:
        raise EnsNormalizationError("normalizer_timeout")
    if overflow.is_set() or io_error.is_set() or any(w.is_alive() for w in workers):
        raise EnsNormalizationError("normalizer_protocol_error")
    if process.returncode != 0 or stderr:
        raise EnsNormalizationError("normalizer_protocol_error")
    return bytes(stdout)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _request(request):
    payload = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(payload) > 16384:
        raise EnsNormalizationError("invalid_ens_name")
    raw = _run(payload)
    try:
        response = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise EnsNormalizationError("normalizer_protocol_error") from None
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        raise EnsNormalizationError("normalizer_protocol_error")
    if response["ok"] is False:
        if (set(response) != {"ok", "error_type"} or
                not isinstance(response.get("error_type"), str) or response["error_type"] not in _MESSAGES):
            raise EnsNormalizationError("normalizer_protocol_error")
        raise EnsNormalizationError(response["error_type"])
    return response


def normalize_ens_name(value: str) -> str:
    """Normalize one nonempty endpoint name; GC's UTF-8 limit is 2 KiB."""
    if not isinstance(value, str) or not value or len(value) > MAX_NAME_BYTES:
        raise EnsNormalizationError("invalid_ens_name")
    try:
        if len(value.encode("utf-8")) > MAX_NAME_BYTES:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise EnsNormalizationError("invalid_ens_name") from None
    response = _request({"name": value})
    normalized = response.get("normalized")
    try:
        if set(response) != {"ok", "normalized"} or not isinstance(normalized, str) or not normalized:
            raise ValueError()
        if len(normalized.encode("utf-8")) > MAX_NAME_BYTES:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise EnsNormalizationError("normalizer_protocol_error") from None
    return normalized


def normalize_ens_subject(value: str) -> dict:
    """Future-facing raw-name path: authoritative normalization before identity.

    This creates an in-memory identity only, never a stored subject or result.
    A future reverse executor must ALSO reject when the returned name changes.
    """
    from .domain import canonical_ens_subject
    return canonical_ens_subject("ethereum", normalize_ens_name(value))


@dataclass(frozen=True)
class NormalizerCapability:
    installed: bool
    usable: bool
    package: str = PACKAGE
    expected_version: str = VERSION
    unicode_version: str = UNICODE_VERSION
    version: str | None = None
    error_type: str | None = None


_probe_lock = Lock()


@lru_cache(maxsize=1)
def _probe():
    installed = (_ROOT / "node_modules" / "@adraffy" / "ens-normalize" / "package.json").is_file()
    try:
        response = _request({"probe": True})
        if response != {"ok": True, "package": PACKAGE, "version": VERSION, "unicode_version": UNICODE_VERSION}:
            raise EnsNormalizationError("normalizer_protocol_error")
        return NormalizerCapability(installed, True, version=VERSION)
    except EnsNormalizationError as error:
        return NormalizerCapability(installed, False, error_type=error.error_type)


def probe_ens_normalizer(*, refresh=False) -> NormalizerCapability:
    """Lazy, cached local self-test. Refresh after an operator install/PATH change."""
    with _probe_lock:
        if refresh:
            _probe.cache_clear()
            _node_executable.cache_clear()
        return _probe()
