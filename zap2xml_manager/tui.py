"""
Terminal User Interface for zap2xml-manager.

Provides an interactive TUI using textual.
"""

from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from .config import Config
from .core import EPGManager
from .server import EPGServer


class SettingsForm(Static):
    """Settings form widget."""

    def __init__(self, config: Config, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        yield Label("Zap2it Settings", classes="section-header")

        with Horizontal(classes="form-row"):
            yield Label("Lineup IDs:", classes="form-label")
            yield Input(
                value=", ".join(self.config.lineup_ids),
                placeholder="USA-DITV501-X, USA-OTA12345",
                id="lineup_ids",
                classes="form-input",
            )

        with Horizontal(classes="form-row"):
            yield Label("Country:", classes="form-label")
            yield Input(
                value=self.config.country,
                placeholder="USA",
                id="country",
                classes="form-input-small",
            )

        with Horizontal(classes="form-row"):
            yield Label("Postal Code:", classes="form-label")
            yield Input(
                value=self.config.postal_code,
                placeholder="77429",
                id="postal_code",
                classes="form-input-small",
            )

        with Horizontal(classes="form-row"):
            yield Label("Hours to Fetch:", classes="form-label")
            yield Input(
                value=str(self.config.timespan_hours),
                placeholder="72",
                id="timespan_hours",
                classes="form-input-small",
            )

        with Horizontal(classes="form-row"):
            yield Label("Delay (sec):", classes="form-label")
            yield Input(
                value=str(self.config.delay_seconds),
                placeholder="0",
                id="delay_seconds",
                classes="form-input-small",
            )

        yield Label("ESPN+ Settings", classes="section-header")

        with Horizontal(classes="form-row"):
            yield Label("Enable ESPN+:", classes="form-label")
            yield Switch(value=self.config.espn_plus_enabled, id="espn_plus_enabled")

        with Horizontal(classes="form-row"):
            yield Label("ESPN+ Channels:", classes="form-label")
            yield Input(
                value="auto" if self.config.espn_plus_channels == 0 else str(self.config.espn_plus_channels),
                placeholder="auto",
                id="espn_plus_channels",
                classes="form-input-small",
            )

        with Horizontal(classes="form-row"):
            yield Label("Channel Offset:", classes="form-label")
            yield Input(
                value=str(self.config.espn_plus_offset),
                placeholder="0",
                id="espn_plus_offset",
                classes="form-input-small",
            )

        yield Label("Output Settings", classes="section-header")

        with Horizontal(classes="form-row"):
            yield Label("Output Dir:", classes="form-label")
            yield Input(
                value=self.config.output_dir,
                placeholder="/path/to/epgs",
                id="output_dir",
                classes="form-input",
            )

        with Horizontal(classes="form-row"):
            yield Label("Filename:", classes="form-label")
            yield Input(
                value=self.config.output_filename,
                placeholder="zap2xml.xml",
                id="output_filename",
                classes="form-input",
            )

        with Horizontal(classes="form-row"):
            yield Label("Merge Lineups:", classes="form-label")
            yield Switch(value=self.config.merge_lineups, id="merge_lineups")

        yield Label("Server Settings", classes="section-header")

        with Horizontal(classes="form-row"):
            yield Label("Enable Server:", classes="form-label")
            yield Switch(value=self.config.server_enabled, id="server_enabled")

        with Horizontal(classes="form-row"):
            yield Label("Server Port:", classes="form-label")
            yield Input(
                value=str(self.config.server_port),
                placeholder="9195",
                id="server_port",
                classes="form-input-small",
            )

    def get_config_values(self) -> dict:
        """Get current form values."""
        values = {}

        lineup_input = self.query_one("#lineup_ids", Input)
        values["lineup_ids"] = [s.strip() for s in lineup_input.value.split(",") if s.strip()]

        values["country"] = self.query_one("#country", Input).value.strip() or "USA"
        values["postal_code"] = self.query_one("#postal_code", Input).value.strip()

        try:
            values["timespan_hours"] = int(self.query_one("#timespan_hours", Input).value)
        except ValueError:
            values["timespan_hours"] = 72

        try:
            values["delay_seconds"] = int(self.query_one("#delay_seconds", Input).value)
        except ValueError:
            values["delay_seconds"] = 0

        values["espn_plus_enabled"] = self.query_one("#espn_plus_enabled", Switch).value

        espn_channels_val = self.query_one("#espn_plus_channels", Input).value.strip().lower()
        if espn_channels_val == "auto" or espn_channels_val == "0" or espn_channels_val == "":
            values["espn_plus_channels"] = 0
        else:
            try:
                values["espn_plus_channels"] = int(espn_channels_val)
            except ValueError:
                values["espn_plus_channels"] = 0

        try:
            values["espn_plus_offset"] = int(self.query_one("#espn_plus_offset", Input).value)
        except ValueError:
            values["espn_plus_offset"] = 0

        values["output_dir"] = self.query_one("#output_dir", Input).value.strip()
        values["output_filename"] = self.query_one("#output_filename", Input).value.strip() or "zap2xml.xml"
        values["merge_lineups"] = self.query_one("#merge_lineups", Switch).value

        values["server_enabled"] = self.query_one("#server_enabled", Switch).value
        try:
            values["server_port"] = int(self.query_one("#server_port", Input).value)
        except ValueError:
            values["server_port"] = 9195

        return values


class Zap2XMLManagerApp(App):
    """Main TUI application."""

    CSS = """
    Screen {
        background: $surface;
    }

    .section-header {
        background: $primary;
        color: $text;
        padding: 0 1;
        margin: 1 0 0 0;
        text-style: bold;
    }

    .form-row {
        height: 3;
        margin: 0 1;
    }

    .form-label {
        width: 18;
        padding: 1 1 0 0;
    }

    .form-input {
        width: 1fr;
    }

    .form-input-small {
        width: 20;
    }

    #status-bar {
        height: 3;
        background: $panel;
        padding: 1;
        border-top: solid $primary;
    }

    #log-container {
        height: 1fr;
        border: solid $primary;
        margin: 1;
    }

    Log {
        height: 1fr;
    }

    #button-bar {
        height: 5;
        padding: 1;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    .success {
        color: $success;
    }

    .error {
        color: $error;
    }

    .warning {
        color: $warning;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "download", "Download EPG"),
        Binding("s", "save_settings", "Save Settings"),
        Binding("r", "refresh", "Refresh"),
    ]

    TITLE = "zap2xml-manager"

    def __init__(self):
        super().__init__()
        self.config = Config.load()
        self.is_downloading = False
        self.server: Optional[EPGServer] = None

    def compose(self) -> ComposeResult:
        yield Header()

        with TabbedContent():
            with TabPane("Settings", id="settings-tab"):
                with ScrollableContainer():
                    yield SettingsForm(self.config, id="settings-form")

                with Horizontal(id="button-bar"):
                    yield Button("Download EPG", variant="primary", id="btn-download")
                    yield Button("Save Settings", variant="default", id="btn-save")
                    yield Button("Start Server", variant="success", id="btn-server")

            with TabPane("Log", id="log-tab"):
                with Container(id="log-container"):
                    yield Log(id="log", highlight=True)

        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.log_message("zap2xml-manager started")
        self.log_message(f"Config loaded from: {self.config.output_path}")
        if self.config.last_refresh:
            self.log_message(f"Last refresh: {self.config.last_refresh}")

        # Auto-start server if enabled
        if self.config.server_enabled:
            self._start_server()

    def log_message(self, message: str, level: str = "info") -> None:
        """Log a message to the log widget."""
        log_widget = self.query_one("#log", Log)
        prefix = ""
        if level == "error":
            prefix = "[red]ERROR:[/red] "
        elif level == "warning":
            prefix = "[yellow]WARN:[/yellow] "
        elif level == "success":
            prefix = "[green]OK:[/green] "
        log_widget.write_line(f"{prefix}{message}")

    def update_status(self, message: str) -> None:
        """Update status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-download":
            self.action_download()
        elif event.button.id == "btn-save":
            self.action_save_settings()
        elif event.button.id == "btn-server":
            self._toggle_server()

    def action_save_settings(self) -> None:
        """Save current settings."""
        form = self.query_one("#settings-form", SettingsForm)
        values = form.get_config_values()

        self.config.lineup_ids = values["lineup_ids"]
        self.config.country = values["country"]
        self.config.postal_code = values["postal_code"]
        self.config.timespan_hours = values["timespan_hours"]
        self.config.delay_seconds = values["delay_seconds"]
        self.config.espn_plus_enabled = values["espn_plus_enabled"]
        self.config.espn_plus_channels = values["espn_plus_channels"]
        self.config.espn_plus_offset = values["espn_plus_offset"]
        self.config.output_dir = values["output_dir"]
        self.config.output_filename = values["output_filename"]
        self.config.merge_lineups = values["merge_lineups"]
        self.config.server_enabled = values["server_enabled"]
        self.config.server_port = values["server_port"]

        self.config.save()
        self.log_message("Settings saved", level="success")
        self.update_status("Settings saved")

    async def action_download(self) -> None:
        """Download EPG data."""
        if self.is_downloading:
            self.log_message("Download already in progress", level="warning")
            return

        # Save settings first
        self.action_save_settings()

        self.is_downloading = True
        self.update_status("Downloading...")

        # Switch to log tab
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "log-tab"

        self.log_message("Starting EPG download...")

        def log_callback(msg: str) -> None:
            self.call_from_thread(self.log_message, msg)

        manager = EPGManager(self.config, log_callback=log_callback)

        try:
            result = await self.run_worker(manager.download_epg)
            if result.success:
                self.log_message(result.message, level="success")
                self.update_status(f"Download complete: {result.file_path}")
            else:
                self.log_message(result.message, level="error")
                self.update_status(f"Download failed: {result.message}")
        except Exception as e:
            self.log_message(f"Download error: {e}", level="error")
            self.update_status(f"Error: {e}")
        finally:
            self.is_downloading = False

    def action_refresh(self) -> None:
        """Refresh the display."""
        self.refresh()

    def _start_server(self) -> None:
        """Start the EPG server."""
        if self.server and self.server.is_running:
            self.log_message("Server already running", level="warning")
            return

        import threading
        main_thread_id = threading.get_ident()

        def log_callback(msg: str) -> None:
            if threading.get_ident() == main_thread_id:
                self.log_message(msg)
            else:
                self.call_from_thread(self.log_message, msg)

        self.server = EPGServer(
            self.config,
            port=self.config.server_port,
            log_callback=log_callback,
        )

        if self.server.start():
            self._update_server_button(True)
            self.update_status(f"Server running on http://0.0.0.0:{self.config.server_port}/")
        else:
            self.log_message("Failed to start server", level="error")

    def _stop_server(self) -> None:
        """Stop the EPG server."""
        if self.server and self.server.is_running:
            self.server.stop()
            self._update_server_button(False)
            self.update_status("Server stopped")

    def _toggle_server(self) -> None:
        """Toggle the server on/off."""
        if self.server and self.server.is_running:
            self._stop_server()
        else:
            # Save settings first to get latest port
            self.action_save_settings()
            self._start_server()

    def _update_server_button(self, running: bool) -> None:
        """Update the server button text."""
        try:
            btn = self.query_one("#btn-server", Button)
            if running:
                btn.label = "Stop Server"
                btn.variant = "error"
            else:
                btn.label = "Start Server"
                btn.variant = "success"
        except Exception:
            pass


def run_tui() -> None:
    """Run the TUI application."""
    app = Zap2XMLManagerApp()
    app.run()
