import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
SYNCHRONIZE = 0x00100000
MOVE_RETRY_TIMEOUT = 30.0
POLL_INTERVAL = 0.2


@dataclass(frozen=True)
class UpdatePlan:
    parent_pid: int
    install_dir: Path
    staging_dir: Path
    backup_dir: Path
    executable: str
    ready_file: Path
    log_file: Path
    old_managed_entries: tuple[str, ...]
    new_managed_entries: tuple[str, ...]
    readiness_timeout: float
    headless: bool = False


def _require(data: dict[str, Any], name: str, expected: type[Any]) -> Any:
    value = data.get(name)
    if not isinstance(value, expected):
        raise TypeError(f"Invalid update plan field: {name}")
    return value


def _validate_entries(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Invalid update plan field: {name}")

    entries: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry or entry in {".", "..", "data", "logs"} or Path(entry).name != entry:
            raise ValueError(f"Unsafe managed entry: {entry!r}")
        entries.append(entry)
    return tuple(dict.fromkeys(entries))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def load_plan(path: Path) -> UpdatePlan:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported update plan schema")

    helper_dir = Path(sys.executable).resolve().parent
    install_dir = Path(_require(data, "install_dir", str)).resolve()
    updates_dir = install_dir / "data" / "updates"
    if helper_dir != updates_dir:
        raise ValueError(f"Update helper is outside the expected directory: {helper_dir}")

    staging_dir = Path(_require(data, "staging_dir", str)).resolve()
    backup_dir = Path(_require(data, "backup_dir", str)).resolve()
    ready_file = Path(_require(data, "ready_file", str)).resolve()
    log_file = Path(_require(data, "log_file", str)).resolve()
    for candidate in (staging_dir, backup_dir, ready_file, log_file, path.resolve()):
        if not _is_relative_to(candidate, updates_dir):
            raise ValueError(f"Update path is outside the update directory: {candidate}")

    parent_pid = _require(data, "parent_pid", int)
    readiness_timeout = data.get("readiness_timeout", 45.0)
    if parent_pid <= 0 or not isinstance(readiness_timeout, int | float) or readiness_timeout <= 0:
        raise ValueError("Invalid update process settings")

    headless = data.get("headless", False)
    if not isinstance(headless, bool):
        raise TypeError("Invalid update plan field: headless")

    executable = _require(data, "executable", str)
    old_entries = _validate_entries(data.get("old_managed_entries"), "old_managed_entries")
    new_entries = _validate_entries(data.get("new_managed_entries"), "new_managed_entries")
    if executable not in new_entries:
        raise ValueError("Executable is not managed by the new package")

    return UpdatePlan(
        parent_pid=parent_pid,
        install_dir=install_dir,
        staging_dir=staging_dir,
        backup_dir=backup_dir,
        executable=executable,
        ready_file=ready_file,
        log_file=log_file,
        old_managed_entries=old_entries,
        new_managed_entries=new_entries,
        readiness_timeout=float(readiness_timeout),
        headless=headless,
    )


def write_log(plan: UpdatePlan, message: str) -> None:
    plan.log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with plan.log_file.open("a", encoding="utf-8") as file:
        file.write(f"{timestamp} {message}\n")


def wait_for_process_exit(pid: int, timeout: float) -> None:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return
        try:
            result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            if result == WAIT_TIMEOUT:
                raise TimeoutError(f"Process {pid} did not exit in time")
            if result == WAIT_FAILED:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Process {pid} did not exit in time")


def retry_file_operation(action: Callable[[], object], *, timeout: float = MOVE_RETRY_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            action()
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(POLL_INTERVAL)
        else:
            return


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        retry_file_operation(lambda: shutil.rmtree(path))
    else:
        retry_file_operation(path.unlink)


def move_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    retry_file_operation(lambda: source.replace(destination))


def _validate_payload(plan: UpdatePlan) -> None:
    for entry in plan.new_managed_entries:
        source = plan.staging_dir / entry
        if not source.exists():
            raise FileNotFoundError(f"Staged package entry is missing: {source}")

    old_entry_set = set(plan.old_managed_entries)
    for entry in plan.new_managed_entries:
        destination = plan.install_dir / entry
        if destination.exists() and entry not in old_entry_set:
            raise FileExistsError(f"Unmanaged install entry would be overwritten: {destination}")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _wait_until_ready(process: subprocess.Popen[bytes], ready_file: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready_file.is_file():
            return
        if process.poll() is not None:
            raise RuntimeError(f"Updated application exited with code {process.returncode}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("Updated application did not report readiness")


def _restore_backup(plan: UpdatePlan, activated_entries: Iterable[str]) -> None:
    for entry in reversed(tuple(activated_entries)):
        remove_path(plan.install_dir / entry)

    for entry in plan.old_managed_entries:
        backup = plan.backup_dir / entry
        if backup.exists() or backup.is_symlink():
            move_path(backup, plan.install_dir / entry)


def _launch(executable: Path, *args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603
        [str(executable), *args],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def apply_update(plan: UpdatePlan) -> None:
    write_log(plan, f"Waiting for parent process {plan.parent_pid}")
    wait_for_process_exit(plan.parent_pid, timeout=60.0)
    _validate_payload(plan)

    remove_path(plan.backup_dir)
    plan.backup_dir.mkdir(parents=True)
    plan.ready_file.unlink(missing_ok=True)
    restart_args = ("--no-gui",) if plan.headless else ()

    activated: list[str] = []
    new_process: subprocess.Popen[bytes] | None = None
    try:
        for entry in plan.old_managed_entries:
            source = plan.install_dir / entry
            if source.exists() or source.is_symlink():
                move_path(source, plan.backup_dir / entry)

        for entry in plan.new_managed_entries:
            move_path(plan.staging_dir / entry, plan.install_dir / entry)
            activated.append(entry)

        executable = plan.install_dir / plan.executable
        write_log(plan, f"Launching updated application: {executable}")
        new_process = _launch(
            executable,
            *restart_args,
            "--update-ready-file",
            str(plan.ready_file),
        )
        _wait_until_ready(new_process, plan.ready_file, plan.readiness_timeout)
    except Exception:
        write_log(plan, "Update failed; restoring previous version")
        if new_process is not None:
            _terminate(new_process)
        _restore_backup(plan, activated)
        old_executable = plan.install_dir / plan.executable
        if old_executable.is_file():
            _launch(old_executable, *restart_args)
        raise

    write_log(plan, "Updated application reported readiness")
    remove_path(plan.backup_dir)
    plan.ready_file.unlink(missing_ok=True)
    remove_path(plan.staging_dir.parent.parent)


def main() -> int:
    if len(sys.argv) != 2:
        return 2

    plan_path = Path(sys.argv[1]).resolve()
    try:
        plan = load_plan(plan_path)
        apply_update(plan)
    except Exception as exc:
        try:
            data = json.loads(plan_path.read_text("utf-8"))
            log_file = Path(data.get("log_file", plan_path.with_suffix(".log")))
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as file:
                file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} helper failed: {exc!r}\n")
        except Exception as log_exc:
            sys.stderr.write(f"Cannot write updater failure log: {log_exc!r}\n")
        return 1
    finally:
        plan_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
