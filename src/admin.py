"""Admin: the kill switch. A file on disk rather than a database flag, so
automation can be halted (`touch storage/HALT`) even if the API process
itself is unresponsive, and resumed the same way.
"""
from __future__ import annotations
import os


def _halt_path(storage_dir: str) -> str:
    return os.path.join(storage_dir, "HALT")


def is_halted(storage_dir: str = "./storage") -> bool:
    return os.path.exists(_halt_path(storage_dir))


def halt(storage_dir: str = "./storage") -> None:
    os.makedirs(storage_dir, exist_ok=True)
    with open(_halt_path(storage_dir), "w") as f:
        f.write("halted by operator\n")


def resume(storage_dir: str = "./storage") -> None:
    path = _halt_path(storage_dir)
    if os.path.exists(path):
        os.remove(path)
