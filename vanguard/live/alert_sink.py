"""
Alert sink — fires a macOS notification for a live trigger event and keeps a
recent-events buffer for the HUD panel. Best-effort only: a notification failure
(no `osascript`, headless box, permissions) must never take down the daemon loop.
"""
from __future__ import annotations

import subprocess
from collections import deque


def notify_macos(title: str, message: str) -> bool:
    """Fire a native notification via osascript. Returns False (never raises) on
    any failure — this is a nice-to-have, not a dependency of the live loop."""
    try:
        script = f'display notification {message!r} with title {title!r}'
        subprocess.run(["osascript", "-e", script], check=False,
                        capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _event_message(event: dict) -> tuple[str, str]:
    """Two producers feed this sink with different event shapes: trigger_engine
    (setup WAITING->TRIGGERED/INVALIDATED, no "type" key) and live_compute
    (REGIME_CROSS/WALL_RELOCATED/IV_EVENT, discriminated by "type"). Branch on
    that instead of forcing one shape — keeps M3's already-shipped event shape
    untouched rather than retrofitting a discriminator onto it."""
    if "type" in event:
        return _structure_event_message(event)
    verb = "TRIGGERED" if event["to"] == "TRIGGERED" else "INVALIDATED"
    title = f"{event['symbol']} — {event['setup_type']} {verb}"
    message = f"spot {event['spot']:.2f} vs level {event['level']:.2f}"
    return title, message


def _structure_event_message(event: dict) -> tuple[str, str]:
    sym, kind = event["symbol"], event["type"]
    if kind == "REGIME_CROSS":
        return (f"{sym} — REGIME CROSS",
                f"{event['from'].replace('_', ' ')} -> {event['to'].replace('_', ' ')}")
    if kind == "WALL_RELOCATED":
        return (f"{sym} — {event['side'].upper()} WALL RELOCATED",
                f"₹{event['from']:.2f} -> ₹{event['to']:.2f}")
    if kind == "IV_EVENT":
        return (f"{sym} — IV {event['direction'].upper()}",
                f"IV {event['iv']*100:.1f}% ({event['delta']*100:+.1f}pt vs session open)")
    return f"{sym} — {kind}", ""


class AlertSink:
    def __init__(self, log_max: int = 300):
        self.recent: deque[dict] = deque(maxlen=log_max)

    def fire(self, event: dict) -> None:
        title, message = _event_message(event)
        notify_macos(title, message)
        self.recent.appendleft(event)

    def fire_all(self, events: list[dict]) -> None:
        for e in events:
            self.fire(e)
