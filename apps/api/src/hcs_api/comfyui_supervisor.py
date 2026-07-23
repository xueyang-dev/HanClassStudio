"""Minimal process-group supervisor for one managed ComfyUI child."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 64
    request_path = Path(sys.argv[1])
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        request_path.unlink()
        argv = payload["argv"]
        cwd = payload["cwd"]
        environment = payload["environment"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(value, str) and value for value in argv)
            or not isinstance(cwd, str)
            or not isinstance(environment, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items())
        ):
            return 65
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return 65

    child = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        close_fds=True,
        start_new_session=False,
        shell=False,
    )

    def terminate_child(signum: int, _frame: object) -> None:
        try:
            child.send_signal(signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, terminate_child)
    signal.signal(signal.SIGINT, terminate_child)
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
