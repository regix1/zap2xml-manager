"""
Scheduler for automatic EPG refreshes.

Runs EPG downloads on a configurable schedule.
"""

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

from .config import Config
from .core import EPGManager


class EPGScheduler:
    """Scheduler for automatic EPG refreshes."""

    def __init__(
        self,
        config: Config,
        log_callback: Optional[Callable[[str], None]] = None,
        on_refresh_complete: Optional[Callable[[bool, str], None]] = None,
    ):
        self.config = config
        self.log = log_callback or print
        self.on_refresh_complete = on_refresh_complete
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self) -> bool:
        """Start the scheduler in a background thread."""
        if self._running:
            self.log("Scheduler already running")
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._running = True
        self.log(f"Scheduler started (refresh every {self.config.refresh_interval_hours} hours)")
        return True

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._running:
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=5)
            self._running = False
            self.log("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            # Check if refresh is needed
            if self._should_refresh():
                self._do_refresh()

            # Sleep in small increments to allow for quick shutdown
            for _ in range(60):  # Check every minute
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _should_refresh(self) -> bool:
        """Check if EPG refresh is needed."""
        if not self.config.auto_refresh_enabled:
            return False

        if not self.config.last_refresh:
            return True

        try:
            last = datetime.fromisoformat(self.config.last_refresh.replace("Z", "+00:00"))
            next_refresh = last + timedelta(hours=self.config.refresh_interval_hours)
            now = datetime.now(timezone.utc)
            return now >= next_refresh
        except (ValueError, TypeError):
            return True

    def _do_refresh(self) -> None:
        """Perform EPG refresh."""
        self.log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting scheduled EPG refresh...")

        manager = EPGManager(self.config, log_callback=self.log)

        try:
            result = manager.download_epg()
            if result.success:
                self.log(f"Scheduled refresh complete: {result.message}")
                if self.on_refresh_complete:
                    self.on_refresh_complete(True, result.message)
            else:
                self.log(f"Scheduled refresh failed: {result.message}")
                if self.on_refresh_complete:
                    self.on_refresh_complete(False, result.message)
        except Exception as e:
            self.log(f"Scheduled refresh error: {e}")
            if self.on_refresh_complete:
                self.on_refresh_complete(False, str(e))

    def refresh_now(self) -> None:
        """Trigger an immediate refresh (runs in background thread)."""
        thread = threading.Thread(target=self._do_refresh, daemon=True)
        thread.start()

    def get_next_refresh_time(self) -> Optional[datetime]:
        """Get the next scheduled refresh time."""
        if not self.config.auto_refresh_enabled:
            return None

        if not self.config.last_refresh:
            return datetime.now(timezone.utc)

        try:
            last = datetime.fromisoformat(self.config.last_refresh.replace("Z", "+00:00"))
            return last + timedelta(hours=self.config.refresh_interval_hours)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    def get_status(self) -> dict:
        """Get scheduler status information."""
        next_refresh = self.get_next_refresh_time()
        return {
            "running": self._running,
            "enabled": self.config.auto_refresh_enabled,
            "interval_hours": self.config.refresh_interval_hours,
            "last_refresh": self.config.last_refresh,
            "next_refresh": next_refresh.isoformat() if next_refresh else None,
        }
