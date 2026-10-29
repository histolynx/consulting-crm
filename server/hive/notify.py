"""Windows toast notifications via built-in WinRT APIs (no extra modules). Clicking opens a URL (e.g. a HIVE page)."""
from __future__ import annotations

import os
import subprocess
from xml.sax.saxutils import escape

# PowerShell's registered AppUserModelID: lets an unpackaged script raise toasts
_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def toast_xml(title: str, body: str, url: str | None = None) -> str:
    launch = f' activationType="protocol" launch="{escape(url, {chr(34): "&quot;"})}"' if url else ""
    return (f"<toast{launch}><visual><binding template=\"ToastGeneric\"><text>{escape(title)}</text>"
            f"<text>{escape(body)}</text></binding></visual></toast>")


def toast(title: str, body: str, url: str | None = None) -> bool:
    """Best effort: returns False (never raises) if notifications aren't available."""
    if os.name != "nt":
        return False
    xml = toast_xml(title, body, url).replace("'", "''")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        f"$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml('{xml}');"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_AUMID}').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
