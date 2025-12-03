"""
Main entry point for zap2xml-manager.

Run with: python -m zap2xml_manager
Or: zap2xml-manager (if installed)
"""

import argparse
import signal
import sys
import time

from . import __version__
from .config import Config, get_config_dir, get_data_dir
from .core import EPGManager


def run_cli(args: argparse.Namespace) -> int:
    """Run in CLI mode (non-interactive)."""
    config = Config.load()

    # Override config with CLI arguments if provided
    if args.lineup:
        config.lineup_ids = [s.strip() for s in args.lineup.split(",") if s.strip()]
    if args.country:
        config.country = args.country
    if args.postal:
        config.postal_code = args.postal
    if args.timespan:
        config.timespan_hours = args.timespan
    if args.output:
        from pathlib import Path
        p = Path(args.output)
        config.output_dir = str(p.parent)
        config.output_filename = p.name
    if args.espn:
        config.espn_plus_enabled = True
    if args.espn_channels:
        config.espn_plus_channels = args.espn_channels

    def log(msg: str) -> None:
        print(msg, flush=True)

    manager = EPGManager(config, log_callback=log)

    print(f"zap2xml-manager v{__version__}")
    print(f"Output: {config.output_path}")
    print()

    result = manager.download_epg()

    if result.success:
        print()
        print(f"Success: {result.message}")
        return 0
    else:
        print()
        print(f"Error: {result.message}", file=sys.stderr)
        return 1


def show_config_info() -> None:
    """Show configuration file locations."""
    config = Config.load()
    print(f"Config directory: {get_config_dir()}")
    print(f"Data directory: {get_data_dir()}")
    print(f"Config file: {get_config_dir() / 'config.json'}")
    print(f"EPG output dir: {config.output_dir}")
    print(f"Server port: {config.server_port}")
    print()
    print("Current settings:")
    print(f"  Lineup IDs: {', '.join(config.lineup_ids) or '(none)'}")
    print(f"  Country: {config.country}")
    print(f"  Postal code: {config.postal_code or '(none)'}")
    print(f"  ESPN+ enabled: {config.espn_plus_enabled}")
    print(f"  Friendly names: {config.prefer_affiliate_names}")
    print(f"  Auto-refresh: {config.auto_refresh_enabled} (every {config.refresh_interval_hours}h)")
    print(f"  Last refresh: {config.last_refresh or 'Never'}")


def get_local_ip() -> str:
    """Get the local IP address."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def show_status() -> None:
    """Show current status including EPG files."""
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    config = Config.load()
    local_ip = get_local_ip()

    print(f"zap2xml-manager v{__version__}")
    print("=" * 50)
    print()

    # EPG File Status
    print("EPG Files:")
    output_dir = Path(config.output_dir)
    output_file = config.output_path

    if output_file.exists():
        stat = output_file.stat()
        size_kb = stat.st_size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {output_file}")
        print(f"  Size: {size_str} | Modified: {mtime}")
    else:
        print(f"  {output_file}")
        print("  (not found - run 'zap2xml-manager download' first)")

    print()

    # List all XML files in output dir
    if output_dir.exists():
        xml_files = list(output_dir.glob("*.xml"))
        if len(xml_files) > 1:
            print("All XML files in output directory:")
            for f in sorted(xml_files, key=lambda x: x.stat().st_mtime, reverse=True):
                stat = f.stat()
                size_kb = stat.st_size / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                print(f"  {f.name} ({size_str})")
            print()

    # Refresh Status
    print("Refresh Status:")
    if config.last_refresh:
        print(f"  Last refresh: {config.last_refresh}")
        try:
            last = datetime.fromisoformat(config.last_refresh.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - last
            hours_ago = age.total_seconds() / 3600
            print(f"  Age: {hours_ago:.1f} hours ago")

            if config.auto_refresh_enabled:
                next_refresh = last + timedelta(hours=config.refresh_interval_hours)
                time_until = next_refresh - datetime.now(timezone.utc)
                if time_until.total_seconds() > 0:
                    hours_until = time_until.total_seconds() / 3600
                    print(f"  Next refresh: in {hours_until:.1f} hours")
                else:
                    print("  Next refresh: due now")
        except (ValueError, TypeError):
            pass
    else:
        print("  Last refresh: Never")

    print()

    # Server Info
    print("Server:")
    print(f"  URL: http://{local_ip}:{config.server_port}/")
    print(f"  EPG URL: http://{local_ip}:{config.server_port}/{config.output_filename}")
    print(f"  Auto-refresh: {'enabled' if config.auto_refresh_enabled else 'disabled'}", end="")
    if config.auto_refresh_enabled:
        print(f" (every {config.refresh_interval_hours}h)")
    else:
        print()

    print()

    # Configuration Summary
    print("Configuration:")
    print(f"  Lineups: {', '.join(config.lineup_ids) or '(none)'}")
    print(f"  Country: {config.country}")
    print(f"  Postal: {config.postal_code or '(none)'}")
    print(f"  ESPN+: {'enabled' if config.espn_plus_enabled else 'disabled'}")


def run_server(args: argparse.Namespace) -> int:
    """Run the HTTP server to serve EPG files."""
    from .server import EPGServer, get_local_ip

    config = Config.load()

    # Override with CLI args
    if args.port:
        config.server_port = args.port
    if args.host:
        config.server_host = args.host
    if args.refresh_interval:
        config.refresh_interval_hours = args.refresh_interval
        config.auto_refresh_enabled = True
    if args.no_refresh:
        config.auto_refresh_enabled = False
    if args.refresh_now:
        config.auto_refresh_enabled = True

    local_ip = get_local_ip()
    print(f"zap2xml-manager v{__version__}")
    print(f"Serving EPG files from: {config.output_dir}")
    print(f"Binding to: {config.server_host}:{config.server_port}")
    print(f"Access URL: http://{local_ip}:{config.server_port}/")
    if config.auto_refresh_enabled:
        print(f"Auto-refresh: every {config.refresh_interval_hours} hours")
    else:
        print("Auto-refresh: disabled")
    print()
    print("Press Ctrl+C to stop")
    print()

    server = EPGServer(config, host=config.server_host, port=config.server_port, log_callback=print)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if server.start():
        # Trigger immediate refresh if requested
        if args.refresh_now and server.scheduler:
            print("Triggering initial EPG refresh...")
            server.scheduler.refresh_now()

        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
        return 0
    else:
        return 1


def set_config(args: argparse.Namespace) -> int:
    """Set configuration values."""
    config = Config.load()

    if args.lineup:
        config.lineup_ids = [s.strip() for s in args.lineup.split(",") if s.strip()]
        print(f"Set lineup_ids: {config.lineup_ids}")

    if args.country:
        config.country = args.country
        print(f"Set country: {config.country}")

    if args.postal:
        config.postal_code = args.postal
        print(f"Set postal_code: {config.postal_code}")

    if args.espn is not None:
        config.espn_plus_enabled = args.espn
        print(f"Set espn_plus_enabled: {config.espn_plus_enabled}")

    if args.auto_refresh is not None:
        config.auto_refresh_enabled = args.auto_refresh
        print(f"Set auto_refresh_enabled: {config.auto_refresh_enabled}")

    if args.refresh_interval:
        config.refresh_interval_hours = args.refresh_interval
        print(f"Set refresh_interval_hours: {config.refresh_interval_hours}")

    if args.port:
        config.server_port = args.port
        print(f"Set server_port: {config.server_port}")

    if args.output_dir:
        config.output_dir = args.output_dir
        print(f"Set output_dir: {config.output_dir}")

    if args.friendly_names is not None:
        config.prefer_affiliate_names = args.friendly_names
        print(f"Set prefer_affiliate_names: {config.prefer_affiliate_names}")

    config.save()
    print("\nConfiguration saved.")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="zap2xml-manager",
        description="XMLTV EPG Manager - Fetch TV listings from Zap2it and ESPN+",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # CLI command (default)
    cli_parser = subparsers.add_parser("cli", help="Launch interactive CLI (default)")

    # TUI command (legacy)
    tui_parser = subparsers.add_parser("tui", help="Launch Textual TUI (requires textual)")

    # Download command (CLI mode)
    dl_parser = subparsers.add_parser("download", help="Download EPG data (non-interactive)")
    dl_parser.add_argument("-l", "--lineup", help="Lineup IDs (comma-separated)")
    dl_parser.add_argument("-c", "--country", help="Country code (e.g., USA)")
    dl_parser.add_argument("-z", "--postal", help="Postal/ZIP code")
    dl_parser.add_argument("-t", "--timespan", type=int, help="Hours to fetch")
    dl_parser.add_argument("-o", "--output", help="Output file path")
    dl_parser.add_argument("--espn", action="store_true", help="Include ESPN+")
    dl_parser.add_argument("--espn-channels", type=int, help="Number of ESPN+ channels (0=auto)")

    # Serve command (daemon mode)
    serve_parser = subparsers.add_parser("serve", help="Start server with auto-refresh scheduling")
    serve_parser.add_argument("-H", "--host", help="Host/IP to bind to (default: 0.0.0.0)")
    serve_parser.add_argument("-p", "--port", type=int, help="Server port (default: 9195)")
    serve_parser.add_argument("-i", "--refresh-interval", type=int, metavar="HOURS",
                              help="Auto-refresh interval in hours (enables auto-refresh)")
    serve_parser.add_argument("--no-refresh", action="store_true",
                              help="Disable auto-refresh (only serve files)")
    serve_parser.add_argument("--refresh-now", action="store_true",
                              help="Trigger an immediate EPG refresh on startup")

    # Config command
    cfg_parser = subparsers.add_parser("config", help="Show or set configuration")
    cfg_parser.add_argument("--show", action="store_true", help="Show current configuration")
    cfg_parser.add_argument("-l", "--lineup", help="Set lineup IDs (comma-separated)")
    cfg_parser.add_argument("-c", "--country", help="Set country code")
    cfg_parser.add_argument("-z", "--postal", help="Set postal/ZIP code")
    cfg_parser.add_argument("--espn", type=lambda x: x.lower() == "true", metavar="true|false",
                            help="Enable/disable ESPN+")
    cfg_parser.add_argument("--auto-refresh", type=lambda x: x.lower() == "true", metavar="true|false",
                            help="Enable/disable auto-refresh")
    cfg_parser.add_argument("-i", "--refresh-interval", type=int, metavar="HOURS",
                            help="Set refresh interval in hours")
    cfg_parser.add_argument("-p", "--port", type=int, help="Set server port")
    cfg_parser.add_argument("-o", "--output-dir", help="Set output directory")
    cfg_parser.add_argument("--friendly-names", type=lambda x: x.lower() == "true", metavar="true|false",
                            help="Use friendly channel names (ABC instead of W25DWD6)")

    # Status command
    status_parser = subparsers.add_parser("status", help="Show current status and EPG file info")

    args = parser.parse_args()

    # Default to CLI if no command specified
    if args.command is None or args.command == "cli":
        try:
            from .cli import run_cli
            run_cli()
            return 0
        except ImportError as e:
            print(f"CLI dependencies not installed: {e}", file=sys.stderr)
            print("Install with: pip install rich", file=sys.stderr)
            return 1

    elif args.command == "tui":
        try:
            from .tui import run_tui
            run_tui()
            return 0
        except ImportError as e:
            print(f"TUI dependencies not installed: {e}", file=sys.stderr)
            print("Install with: pip install textual", file=sys.stderr)
            print()
            print("Or use the default Rich CLI: zap2xml-manager cli")
            return 1

    elif args.command == "download":
        return run_cli(args)

    elif args.command == "config":
        # If any setter args provided, set them
        if any([args.lineup, args.country, args.postal, args.espn is not None,
                args.auto_refresh is not None, args.refresh_interval, args.port, args.output_dir,
                args.friendly_names is not None]):
            return set_config(args)
        else:
            show_config_info()
            return 0

    elif args.command == "serve":
        return run_server(args)

    elif args.command == "status":
        show_status()
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
