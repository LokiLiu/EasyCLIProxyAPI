#!/usr/bin/env python3
"""Migrate the legacy Agent Gateway settings into EasyCLIProxyAPI on macOS.

The API key is read and written locally. It is never printed. Existing EasyCLIProxyAPI
configuration and provider records are backed up before they are replaced.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"migration failed: {message}")


def replace_toml_value(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    line = f"{key} = {value}"
    if pattern.search(content):
        return pattern.sub(line, content, count=1)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup(path: Path, suffix: str) -> None:
    if not path.exists():
        return
    destination = path.with_name(f"{path.name}.before-agent-gateway-{suffix}")
    shutil.copy2(path, destination)


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        fail(f"{label} does not exist: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3081)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        fail("port must be between 1 and 65535")

    home = Path.home()
    old_root = home / "Library/Application Support/Agent Gateway"
    easy_root = home / "Library/Application Support/com.cpa.gui"
    core_root = easy_root / "cpa-core"
    config_path = easy_root / "config.toml"
    auth_dir = easy_root / "oauth"
    bridge = require_file(
        core_root / "plugins/darwin/arm64/cli-proxy-tool-bridge", "tool bridge"
    )

    api_key_path = require_file(old_root / "api-key", "legacy API key")
    api_key = api_key_path.read_text(encoding="utf-8").strip()
    if not api_key:
        fail("legacy API key is empty")

    qoder_cli_candidates = [
        home / ".qodersec/bin/qodercli",
        Path("/Applications/Qoder.app/Contents/Resources/bin/qodercli"),
    ]
    qoder_cli = next((path for path in qoder_cli_candidates if path.is_file()), None)
    if qoder_cli is None:
        fail("personal Qoder CLI was not found")
    qoder_config = home / ".qoder"
    require_file(qoder_config / ".auth/user", "personal Qoder login")

    qoderwork_cli = require_file(
        Path("/Applications/QoderWork.app/Contents/Resources/bin/qodercli"),
        "QoderWork CLI",
    )
    qoderwork_config = old_root / "Qoder Profiles/qoderwork"
    require_file(qoderwork_config / ".auth/user", "QoderWork login")
    kiro_cli = require_file(home / ".local/bin/kiro-cli", "Kiro CLI")

    records = {
        "qoder": {
            "type": "qoder",
            "id": "qoder",
            "label": "Qoder",
            "prefix": "qoder",
            "cli_path": str(qoder_cli),
            "config_dir": str(qoder_config),
            "bridge_path": str(bridge),
        },
        "qoderwork": {
            "type": "qoder",
            "id": "qoderwork",
            "label": "QoderWork",
            "prefix": "qoderwork",
            "cli_path": str(qoderwork_cli),
            "config_dir": str(qoderwork_config),
            "bridge_path": str(bridge),
        },
        "kiro": {
            "type": "kiro",
            "id": "kiro",
            "label": "Kiro",
            "prefix": "kiro",
            "cli_path": str(kiro_cli),
            "bridge_path": str(bridge),
        },
    }

    if not config_path.is_file():
        fail(f"EasyCLIProxyAPI configuration does not exist: {config_path}")
    content = config_path.read_text(encoding="utf-8")
    api_keys = f'[{{ key = {json.dumps(api_key)}, remark = "Migrated from Agent Gateway" }}]'
    replacements = {
        "port": str(args.port),
        "allow-lan": "false",
        "host": '"127.0.0.1"',
        "start-core-on-launch": "true",
        "close-behavior": '"minimize-to-tray"',
        "plugins-enabled": "true",
        "api-keys": api_keys,
    }
    for key, value in replacements.items():
        content = replace_toml_value(content, key, value)

    if args.dry_run:
        print(
            f"ready: port={args.port}, providers={','.join(records)}, "
            "api-key=present (redacted)"
        )
        return 0

    suffix = time.strftime("%Y%m%d-%H%M%S")
    backup(config_path, suffix)
    atomic_write(config_path, content.encode("utf-8"))
    for provider_id, record in records.items():
        destination = auth_dir / f"{provider_id}.json"
        backup(destination, suffix)
        raw = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        atomic_write(destination, raw)

    # Ensure the GUI config wins over an older generated core config on next launch.
    now = time.time() + 1
    os.utime(config_path, (now, now))
    mode = stat.S_IMODE(config_path.stat().st_mode)
    print(
        f"migrated: port={args.port}, providers={','.join(records)}, "
        f"api-key=present (redacted), config-mode={mode:o}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        fail(str(error))
