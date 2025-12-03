"""
HTTP server for serving XMLTV EPG files.

Provides a simple HTTP server to serve generated EPG files,
with integrated scheduling for automatic EPG refreshes.
"""

import json
import os
import socket
import threading
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Callable, Optional

from .config import Config


def get_local_ip() -> str:
    """Get the local IP address that can reach external networks."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR enabled."""
    allow_reuse_address = True

    def server_bind(self):
        """Override to set additional socket options for Windows compatibility."""
        # Set SO_REUSEADDR before binding
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


class EPGRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler for serving EPG files."""

    config: Config = None
    log_callback: Optional[Callable[[str], None]] = None
    scheduler = None  # Will be set by EPGServer

    def __init__(self, *args, **kwargs):
        # Set the directory to serve files from
        self.directory = str(Path(self.config.output_dir)) if self.config else "."
        super().__init__(*args, directory=self.directory, **kwargs)

    def log_message(self, format: str, *args) -> None:
        """Override to use custom logging."""
        message = format % args
        if self.log_callback:
            self.log_callback(f"[HTTP] {self.address_string()} - {message}")

    def do_GET(self):
        """Handle GET requests."""
        try:
            # Clean up the path
            path = self.path.split("?")[0].split("#")[0]

            # Remove leading slash
            if path.startswith("/"):
                path = path[1:]

            # API endpoints
            if path == "api/status":
                self._send_json(self._get_status())
                return

            if path == "api/health" or path == "health":
                self._send_json({"status": "ok", "time": datetime.now().isoformat()})
                return

            if path == "api/refresh":
                self._trigger_refresh()
                return

            # Root path - return status JSON
            if not path or path == "/":
                self._send_json(self._get_status())
                return

            # Serve the requested file
            super().do_GET()
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"[HTTP] Error handling request: {e}")
            try:
                self.send_error(500, f"Internal Server Error: {e}")
            except Exception:
                pass

    def _send_json(self, data: dict) -> None:
        """Send JSON response."""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def _get_status(self) -> dict:
        """Get server and scheduler status."""
        status = {
            "server": "running",
            "time": datetime.now().isoformat(),
            "config": {
                "lineup_ids": self.config.lineup_ids if self.config else [],
                "espn_plus_enabled": self.config.espn_plus_enabled if self.config else False,
                "output_dir": self.config.output_dir if self.config else "",
            },
        }

        if self.scheduler:
            try:
                status["scheduler"] = self.scheduler.get_status()
            except Exception:
                status["scheduler"] = {"error": "Unable to get scheduler status"}

        # List EPG files
        output_dir = Path(self.config.output_dir) if self.config else Path(".")
        files = []
        try:
            if output_dir.exists():
                for f in output_dir.iterdir():
                    if f.suffix.lower() == ".xml":
                        try:
                            stat = f.stat()
                            files.append({
                                "name": f.name,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            })
                        except (OSError, IOError):
                            pass
        except (OSError, IOError):
            pass
        status["files"] = files

        return status

    def _trigger_refresh(self) -> None:
        """Trigger an immediate EPG refresh."""
        if self.scheduler:
            self.scheduler.refresh_now()
            self._send_json({"status": "refresh_started", "message": "EPG refresh triggered"})
        else:
            self._send_json({"status": "error", "message": "Scheduler not available"})

    def end_headers(self):
        """Add CORS headers for broader compatibility."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


class EPGServer:
    """HTTP server for serving EPG files with optional scheduling."""

    def __init__(
        self,
        config: Config,
        host: str = "0.0.0.0",
        port: int = 9195,
        log_callback: Optional[Callable[[str], None]] = None,
        enable_scheduler: bool = True,
    ):
        self.config = config
        self.host = host
        self.port = port
        self.log_callback = log_callback or print
        self.enable_scheduler = enable_scheduler
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.scheduler = None
        self._running = False

    def start(self) -> bool:
        """Start the HTTP server and scheduler in background threads."""
        if self._running:
            self.log_callback(f"Server already running on port {self.port}")
            return True

        # Ensure output directory exists
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Start scheduler if enabled
        if self.enable_scheduler:
            from .scheduler import EPGScheduler
            self.scheduler = EPGScheduler(
                self.config,
                log_callback=self.log_callback,
                on_refresh_complete=self._on_refresh_complete,
            )
            if self.config.auto_refresh_enabled:
                self.scheduler.start()

        # Configure the handler
        EPGRequestHandler.config = self.config
        EPGRequestHandler.log_callback = self.log_callback
        EPGRequestHandler.scheduler = self.scheduler

        # Determine the host to bind to
        bind_host = self.host
        local_ip = get_local_ip()

        # If host is 0.0.0.0, also try binding to specific IP on Windows
        hosts_to_try = [bind_host]
        if bind_host == "0.0.0.0" and local_ip != "127.0.0.1":
            # On Windows, sometimes binding to the specific IP works better
            hosts_to_try.append(local_ip)

        last_error = None
        for try_host in hosts_to_try:
            try:
                self.log_callback(f"Attempting to bind to {try_host}:{self.port}...")
                self.server = ReusableHTTPServer((try_host, self.port), EPGRequestHandler)
                self.log_callback(f"Server socket created, starting thread...")
                self.thread = threading.Thread(target=self._serve, daemon=True)
                self.thread.start()
                self._running = True
                self.host = try_host  # Update to actual bound host

                # Verify the server is actually listening
                if self._verify_port_open():
                    self.log_callback(f"EPG server started on http://{try_host}:{self.port}/")
                    self.log_callback(f"Access from other devices: http://{local_ip}:{self.port}/")
                    return True
                else:
                    self.log_callback(f"WARNING: Server started but port {self.port} not responding locally")
                    self.log_callback(f"EPG server started on http://{try_host}:{self.port}/ (unverified)")
                    self.log_callback(f"Access from other devices: http://{local_ip}:{self.port}/")
                    return True
            except OSError as e:
                last_error = e
                self.log_callback(f"Failed to bind to {try_host}:{self.port}: {e}")
                continue

        self.log_callback(f"Failed to start server on any address: {last_error}")
        return False

    def _serve(self) -> None:
        """Run the server (called in background thread)."""
        if self.server:
            try:
                self.server.serve_forever()
            except Exception as e:
                self.log_callback(f"Server error: {e}")
                self._running = False

    def _verify_port_open(self) -> bool:
        """Verify the server port is actually accessible."""
        import time
        time.sleep(0.5)  # Give server time to start
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.settimeout(2)
            result = test_sock.connect_ex(("127.0.0.1", self.port))
            test_sock.close()
            return result == 0
        except Exception:
            return False

    def _on_refresh_complete(self, success: bool, message: str) -> None:
        """Called when a scheduled refresh completes."""
        status = "completed" if success else "failed"
        self.log_callback(f"Scheduled refresh {status}: {message}")

    def stop(self) -> None:
        """Stop the HTTP server and scheduler."""
        if self.scheduler:
            self.scheduler.stop()

        if self.server and self._running:
            self.server.shutdown()
            self._running = False
            self.log_callback("EPG server stopped")

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        # Also verify the thread is actually alive
        if self._running and self.thread and not self.thread.is_alive():
            self._running = False
        return self._running

    @property
    def url(self) -> str:
        """Get the server URL."""
        return f"http://{self.host}:{self.port}/"
