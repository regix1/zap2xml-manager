"""
Rich-based CLI for zap2xml-manager.

Provides an interactive menu-driven interface with copy/paste support.
"""

import sys
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.live import Live
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import Config, get_config_dir, get_data_dir
from .core import EPGManager
from .server import EPGServer, get_local_ip
from . import __version__


console = Console()


def clear_screen():
    """Clear the terminal screen."""
    console.clear()


def print_header():
    """Print application header."""
    console.print(Panel.fit(
        f"[bold cyan]zap2xml-manager[/] v{__version__}",
        border_style="cyan"
    ))
    console.print()


def show_status(config: Config, server: Optional[EPGServer] = None):
    """Display current status."""
    local_ip = get_local_ip()

    # Status table
    table = Table(title="Status", show_header=False, border_style="blue")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    # EPG File
    output_file = config.output_path
    if output_file.exists():
        stat = output_file.stat()
        size_kb = stat.st_size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row("EPG File", str(output_file))
        table.add_row("Size", size_str)
        table.add_row("Modified", mtime)
    else:
        table.add_row("EPG File", f"{output_file} [yellow](not found)[/]")

    # Last refresh
    if config.last_refresh:
        table.add_row("Last Refresh", config.last_refresh)
        try:
            last = datetime.fromisoformat(config.last_refresh.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - last
            hours_ago = age.total_seconds() / 3600
            table.add_row("Age", f"{hours_ago:.1f} hours ago")
        except (ValueError, TypeError):
            pass
    else:
        table.add_row("Last Refresh", "[yellow]Never[/]")

    # Server
    server_status = "[green]running[/]" if (server and server.is_running) else "[red]stopped[/]"
    table.add_row("Server", server_status)
    table.add_row("Server URL", f"http://{local_ip}:{config.server_port}/")
    table.add_row("EPG URL", f"http://{local_ip}:{config.server_port}/{config.output_filename}")

    console.print(table)
    console.print()


def show_config(config: Config):
    """Display current configuration."""
    table = Table(title="Configuration", show_header=False, border_style="green")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Lineups", ", ".join(config.lineup_ids) or "[yellow](none)[/]")
    table.add_row("Country", config.country)
    table.add_row("Postal Code", config.postal_code or "[yellow](none)[/]")
    table.add_row("Hours to Fetch", str(config.timespan_hours))
    table.add_row("Delay (sec)", str(config.delay_seconds))
    table.add_row("Output Dir", config.output_dir)
    table.add_row("Filename", config.output_filename)
    table.add_row("Merge Lineups", "[green]Yes[/]" if config.merge_lineups else "[red]No[/]")
    table.add_row("Friendly Names", "[green]Yes[/]" if config.prefer_affiliate_names else "[red]No[/]")
    table.add_row("ESPN+ Enabled", "[green]Yes[/]" if config.espn_plus_enabled else "[red]No[/]")
    table.add_row("ESPN+ Channels", "auto" if config.espn_plus_channels == 0 else str(config.espn_plus_channels))
    table.add_row("ESPN+ Offset", str(config.espn_plus_offset))
    table.add_row("Server Enabled", "[green]Yes[/]" if config.server_enabled else "[red]No[/]")
    table.add_row("Server Port", str(config.server_port))
    table.add_row("Auto-Refresh", "[green]Yes[/]" if config.auto_refresh_enabled else "[red]No[/]")
    table.add_row("Refresh Interval", f"{config.refresh_interval_hours} hours")

    console.print(table)
    console.print()
    console.print(f"[dim]Config file: {get_config_dir() / 'config.json'}[/]")
    console.print()


def edit_settings(config: Config) -> bool:
    """Edit configuration settings. Returns True if saved."""
    console.print("[bold]Edit Settings[/]")
    console.print("[dim]Press Enter to keep current value[/]")
    console.print()

    # Lineup IDs
    current = ", ".join(config.lineup_ids) or ""
    new_val = Prompt.ask("Lineup IDs (comma-separated)", default=current)
    config.lineup_ids = [s.strip() for s in new_val.split(",") if s.strip()]

    # Country
    config.country = Prompt.ask("Country", default=config.country) or "USA"

    # Postal code
    config.postal_code = Prompt.ask("Postal Code", default=config.postal_code or "")

    # Hours to fetch
    try:
        config.timespan_hours = int(Prompt.ask("Hours to Fetch", default=str(config.timespan_hours)))
    except ValueError:
        pass

    # Output dir
    config.output_dir = Prompt.ask("Output Directory", default=config.output_dir)

    # Filename
    config.output_filename = Prompt.ask("Output Filename", default=config.output_filename) or "zap2xml.xml"

    # ESPN+
    config.espn_plus_enabled = Confirm.ask("Enable ESPN+?", default=config.espn_plus_enabled)

    if config.espn_plus_enabled:
        espn_ch = Prompt.ask("ESPN+ Channels (0=auto)", default=str(config.espn_plus_channels))
        try:
            config.espn_plus_channels = int(espn_ch) if espn_ch.lower() != "auto" else 0
        except ValueError:
            config.espn_plus_channels = 0

    # Friendly names
    config.prefer_affiliate_names = Confirm.ask("Use Friendly Names?", default=config.prefer_affiliate_names)

    # Server
    config.server_enabled = Confirm.ask("Enable Server on startup?", default=config.server_enabled)

    try:
        config.server_port = int(Prompt.ask("Server Port", default=str(config.server_port)))
    except ValueError:
        pass

    # Auto-refresh
    config.auto_refresh_enabled = Confirm.ask("Enable Auto-Refresh?", default=config.auto_refresh_enabled)

    if config.auto_refresh_enabled:
        try:
            config.refresh_interval_hours = int(Prompt.ask("Refresh Interval (hours)", default=str(config.refresh_interval_hours)))
        except ValueError:
            pass

    console.print()

    if Confirm.ask("Save settings?", default=True):
        config.save()
        console.print("[green]Settings saved![/]")
        return True
    else:
        console.print("[yellow]Changes discarded.[/]")
        return False


def download_epg(config: Config):
    """Download EPG data with progress display."""
    console.print("[bold]Downloading EPG...[/]")
    console.print()

    log_lines = []

    def log_callback(msg: str):
        log_lines.append(msg)
        console.print(f"  {msg}")

    manager = EPGManager(config, log_callback=log_callback)

    try:
        result = manager.download_epg()
        console.print()

        if result.success:
            console.print(Panel(
                f"[green]{result.message}[/]\n\nFile: {result.file_path}",
                title="Success",
                border_style="green"
            ))
        else:
            console.print(Panel(
                f"[red]{result.message}[/]",
                title="Error",
                border_style="red"
            ))
    except Exception as e:
        console.print(Panel(
            f"[red]Error: {e}[/]",
            title="Error",
            border_style="red"
        ))


def run_server_interactive(config: Config) -> Optional[EPGServer]:
    """Start the server and return the instance."""
    local_ip = get_local_ip()

    def log_callback(msg: str):
        console.print(f"  [dim]{msg}[/]")

    server = EPGServer(
        config,
        host=config.server_host,
        port=config.server_port,
        log_callback=log_callback,
    )

    if server.start():
        console.print(Panel(
            f"Server running at:\n"
            f"  http://{local_ip}:{config.server_port}/\n"
            f"  EPG: http://{local_ip}:{config.server_port}/{config.output_filename}",
            title="[green]Server Started[/]",
            border_style="green"
        ))
        return server
    else:
        console.print("[red]Failed to start server[/]")
        return None


def main_menu():
    """Run the main interactive menu."""
    config = Config.load()
    server: Optional[EPGServer] = None

    # Auto-start server if configured
    if config.server_enabled:
        console.print("[dim]Auto-starting server...[/]")
        server = run_server_interactive(config)

    while True:
        clear_screen()
        print_header()
        show_status(config, server)

        # Menu options
        console.print("[bold]Menu:[/]")
        console.print("  [cyan]1[/] Download EPG")
        console.print("  [cyan]2[/] View Configuration")
        console.print("  [cyan]3[/] Edit Settings")
        if server and server.is_running:
            console.print("  [cyan]4[/] Stop Server")
        else:
            console.print("  [cyan]4[/] Start Server")
        console.print("  [cyan]5[/] Refresh Now (if server running)")
        console.print("  [cyan]q[/] Quit")
        console.print()

        choice = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5", "q"], default="1")

        if choice == "1":
            clear_screen()
            print_header()
            download_epg(config)
            Prompt.ask("\nPress Enter to continue")

        elif choice == "2":
            clear_screen()
            print_header()
            show_config(config)
            Prompt.ask("Press Enter to continue")

        elif choice == "3":
            clear_screen()
            print_header()
            if edit_settings(config):
                config = Config.load()  # Reload
            Prompt.ask("\nPress Enter to continue")

        elif choice == "4":
            if server and server.is_running:
                server.stop()
                server = None
                console.print("[yellow]Server stopped[/]")
            else:
                server = run_server_interactive(config)
            Prompt.ask("\nPress Enter to continue")

        elif choice == "5":
            if server and server.is_running and server.scheduler:
                console.print("[cyan]Triggering EPG refresh...[/]")
                server.scheduler.refresh_now()
                console.print("[green]Refresh triggered![/]")
            else:
                console.print("[yellow]Server not running or no scheduler active[/]")
            Prompt.ask("\nPress Enter to continue")

        elif choice == "q":
            if server and server.is_running:
                console.print("[dim]Stopping server...[/]")
                server.stop()
            console.print("[cyan]Goodbye![/]")
            break


def run_cli():
    """Entry point for the Rich CLI."""
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
        sys.exit(0)
