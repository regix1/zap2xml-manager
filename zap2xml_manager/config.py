"""
Configuration management for zap2xml-manager.

Stores settings in a JSON file in the user's config directory.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


def get_config_dir() -> Path:
    """Get the configuration directory for zap2xml-manager."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux/macOS
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = base / "zap2xml-manager"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_data_dir() -> Path:
    """Get the data directory for zap2xml-manager (EPG files, etc.)."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:  # Linux/macOS
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data_dir = base / "zap2xml-manager"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@dataclass
class Config:
    """Configuration settings for zap2xml-manager."""

    # Zap2it settings
    lineup_ids: list[str] = field(default_factory=list)
    postal_code: str = ""
    country: str = "USA"

    # Fetch settings
    timespan_hours: int = 72
    delay_seconds: int = 0
    merge_lineups: bool = True

    # ESPN+ settings
    espn_plus_enabled: bool = False
    espn_plus_channels: int = 0  # 0 = auto (pull as many as available)
    espn_plus_offset: int = 0

    # Output settings
    output_dir: str = ""
    output_filename: str = "zap2xml.xml"

    # Schedule settings
    auto_refresh_enabled: bool = False
    refresh_interval_hours: int = 24
    last_refresh: Optional[str] = None

    # HTTP settings
    user_agent: str = ""

    # Server settings
    server_enabled: bool = False
    server_host: str = "0.0.0.0"
    server_port: int = 9195

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = str(get_data_dir() / "epgs")

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from file."""
        if config_path is None:
            config_path = get_config_dir() / "config.json"

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if hasattr(cls, k) or k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Could not load config: {e}")

        return cls()

    def save(self, config_path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        if config_path is None:
            config_path = get_config_dir() / "config.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @property
    def output_path(self) -> Path:
        """Get the full output path for the XMLTV file."""
        return Path(self.output_dir) / self.output_filename

    def get_lineup_list(self) -> list[str]:
        """Get lineup IDs as a list."""
        return [lid.strip() for lid in self.lineup_ids if lid.strip()]
