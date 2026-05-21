#!/usr/bin/env python3

import io
import os
import sys
from pathlib import Path

APP_DIR = "/app"

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


class Tee(io.TextIOBase):
    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary

    def write(self, data):
        self.primary.write(data)
        self.secondary.write(data)
        self.primary.flush()
        self.secondary.flush()
        return len(data)

    def flush(self):
        self.primary.flush()
        self.secondary.flush()


def main() -> int:
    log_path = Path(os.environ.get("SYNC_LOG_FILE", "/config/sync.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = Tee(original_stdout, log_file)
    sys.stderr = Tee(original_stderr, log_file)

    try:
        import sync

        try:
            sync.main()
            return 0
        except SystemExit as exc:
            code = exc.code
            if isinstance(code, int):
                return code
            return 1 if code else 0
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())