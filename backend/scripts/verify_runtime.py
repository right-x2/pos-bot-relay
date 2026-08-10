"""Validate the known-good Windows/Python/Chroma runtime.

Run from the backend directory:
    python scripts/verify_runtime.py --chroma-smoke

The Chroma write test runs in a child process and uses a temporary directory,
so it never opens or modifies the production collection.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_PACKAGES = {
    "chromadb": "0.5.23",
    "chroma-hnswlib": "0.7.6",
    "monotonic": "1.6",
    "numpy": "1.26.4",
    "posthog": "3.7.4",
}


def _print_result(ok: bool, label: str, detail: str) -> None:
    marker = "OK" if ok else "FAIL"
    print(f"[{marker}] {label}: {detail}", flush=True)


def _check_runtime() -> bool:
    ok = True
    python_ok = sys.version_info[:2] == (3, 11)
    _print_result(python_ok, "Python", platform.python_version())
    ok &= python_ok

    bits = struct.calcsize("P") * 8
    bits_ok = bits == 64
    _print_result(bits_ok, "Architecture", f"{bits}-bit")
    ok &= bits_ok

    for package, expected in EXPECTED_PACKAGES.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "not installed"
        version_ok = actual == expected
        _print_result(version_ok, package, f"expected={expected}, actual={actual}")
        ok &= version_ok

    return ok


def _run_pip_check() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        text=True,
        capture_output=True,
    )
    output = (result.stdout or result.stderr).strip()
    _print_result(result.returncode == 0, "pip check", output)
    return result.returncode == 0


def _chroma_worker() -> int:
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ["CHROMA_TELEMETRY"] = "False"
    os.environ["CHROMADB_TELEMETRY"] = "False"

    import chromadb
    from chromadb.config import Settings as ChromaSettings

    with tempfile.TemporaryDirectory(prefix="pos-rag-chroma-smoke-") as temp_dir:
        client = chromadb.PersistentClient(
            path=temp_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection("runtime_smoke")
        print("[INFO] Chroma 3072-dimension upsert starting", flush=True)
        collection.upsert(
            ids=["runtime-smoke-1"],
            embeddings=[[0.0] * 3072],
            documents=["runtime smoke test"],
            metadatas=[{"source": "verify_runtime"}],
        )
        count = collection.count()
        if count != 1:
            print(f"[FAIL] Chroma count: expected=1, actual={count}", flush=True)
            return 1
        print(f"[OK] Chroma count: {count}", flush=True)
    return 0


def _run_chroma_smoke() -> bool:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--chroma-worker"],
        check=False,
    )
    if result.returncode == 0:
        _print_result(True, "Chroma smoke", "temporary 3072-dimension upsert succeeded")
        return True

    windows_code = result.returncode & 0xFFFFFFFF
    _print_result(
        False,
        "Chroma smoke",
        f"child process exit={result.returncode} (Windows=0x{windows_code:08X})",
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chroma-smoke",
        action="store_true",
        help="Run an isolated Chroma 3072-dimension write test.",
    )
    parser.add_argument("--chroma-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.chroma_worker:
        return _chroma_worker()

    ok = _check_runtime()
    ok &= _run_pip_check()
    if args.chroma_smoke:
        ok &= _run_chroma_smoke()

    print("Runtime verification passed." if ok else "Runtime verification failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
