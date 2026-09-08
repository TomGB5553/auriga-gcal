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
    clean = lambda s: s.replace("\\", "").replace('"', "'").strip()[:230]
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{clean(message)}" with title "{clean(title)}"'],
            check=False, timeout=10,
        )
    except Exception:
        pass
