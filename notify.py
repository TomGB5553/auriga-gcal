"""Fire a macOS notification. No-op on other platforms or if osascript is gone."""
from __future__ import annotations

import shutil
import subprocess
import sys


def notify(title: str, message: str, *, only_headless: bool = True) -> None:
    """Show a Notification Center banner.

    only_headless: when True (default), stay silent if we're attached to a
    terminal -- you don't need a banner for a command you ran yourself.
    """
    if only_headless and sys.stdin.isatty():
        return
    if not shutil.which("osascript"):
        return
    def clean(s: str, maxlen: int) -> str:
        return s.replace("\\", "").replace('"', "'").strip()[:maxlen]
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{clean(message, 500)}" with title "{clean(title, 80)}"'],
            check=False, timeout=10,
        )
    except Exception:
        pass
