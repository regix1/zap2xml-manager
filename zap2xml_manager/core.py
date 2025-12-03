"""
Core orchestration logic for zap2xml-manager.

Handles downloading EPG data from multiple sources and merging them.
"""

import os
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .config import Config, get_data_dir


# Default User-Agent
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class DownloadResult:
    """Result of a download operation."""

    def __init__(self, success: bool, message: str, file_path: Optional[str] = None):
        self.success = success
        self.message = message
        self.file_path = file_path


class EPGManager:
    """Manages EPG downloads and merging."""

    def __init__(self, config: Config, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log = log_callback or (lambda msg: print(msg, file=sys.stderr, flush=True))

    def download_epg(self) -> DownloadResult:
        """Download EPG data from all configured sources."""
        from .zap2it import fetch_zap2it_epg
        from .espn import fetch_espn_plus_epg

        lineup_ids = self.config.get_lineup_list()
        if not lineup_ids and not self.config.espn_plus_enabled:
            return DownloadResult(False, "No lineup IDs configured and ESPN+ is disabled")

        produced_files: list[tuple[str, str]] = []  # (source_name, file_path)
        user_agent = self.config.user_agent or DEFAULT_UA

        # Fetch Zap2it lineups
        for lineup_id in lineup_ids:
            self.log(f"Fetching Zap2it lineup: {lineup_id}")
            try:
                result = fetch_zap2it_epg(
                    lineup_id=lineup_id,
                    country=self.config.country,
                    postal_code=self.config.postal_code,
                    timespan_hours=self.config.timespan_hours,
                    delay_seconds=self.config.delay_seconds,
                    user_agent=user_agent,
                    log_callback=self.log,
                )
                if result.success and result.file_path:
                    produced_files.append((lineup_id, result.file_path))
                    self.log(f"  -> Success: {result.file_path}")
                else:
                    self.log(f"  -> Failed: {result.message}")
                    return DownloadResult(False, f"Failed to fetch lineup {lineup_id}: {result.message}")
            except Exception as e:
                self.log(f"  -> Error: {e}")
                return DownloadResult(False, f"Error fetching lineup {lineup_id}: {e}")

        # Fetch ESPN+ if enabled
        if self.config.espn_plus_enabled:
            self.log("Fetching ESPN+ schedule...")
            try:
                result = fetch_espn_plus_epg(
                    num_channels=self.config.espn_plus_channels,
                    channel_offset=self.config.espn_plus_offset,
                    log_callback=self.log,
                )
                if result.success and result.file_path:
                    produced_files.append(("ESPN+", result.file_path))
                    self.log(f"  -> Success: {result.file_path}")
                else:
                    self.log(f"  -> ESPN+ fetch failed (non-fatal): {result.message}")
            except Exception as e:
                self.log(f"  -> ESPN+ error (non-fatal): {e}")

        if not produced_files:
            return DownloadResult(False, "No EPG data was produced")

        # Ensure output directory exists
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.config.output_path

        # Merge or copy files
        if self.config.merge_lineups and len(produced_files) > 1:
            self.log(f"Merging {len(produced_files)} EPG files...")
            try:
                self._merge_xmltv([p for _, p in produced_files], str(output_path))
                self.log(f"  -> Merged to: {output_path}")
            except Exception as e:
                return DownloadResult(False, f"Failed to merge XMLTV files: {e}")
        elif produced_files:
            # Single file or no merge - just copy the first one (or merged if only one)
            src_path = produced_files[0][1]
            try:
                shutil.copyfile(src_path, output_path)
                self.log(f"  -> Copied to: {output_path}")
            except Exception as e:
                return DownloadResult(False, f"Failed to copy EPG file: {e}")

        # Cleanup temp files
        self._cleanup_temp_files(produced_files)

        # Update last refresh time
        self.config.last_refresh = datetime.now(timezone.utc).isoformat()
        self.config.save()

        return DownloadResult(True, f"EPG saved to {output_path}", str(output_path))

    def _merge_xmltv(self, paths: list[str], out_path: str) -> None:
        """Merge multiple XMLTV files into one."""
        if not paths:
            raise ValueError("No XML paths to merge")

        chan_map: dict[str, ET.Element] = {}
        prog_map: dict[str, list[ET.Element]] = {}

        def _chan_name(ch: ET.Element) -> str:
            names = [dn.text or "" for dn in ch.findall("./display-name") if dn is not None and dn.text]
            return (names[0] if names else ch.get("id") or "").casefold()

        for p in paths:
            tree = ET.parse(p)
            root = tree.getroot()
            if root.tag != "tv":
                continue

            for ch in root.findall("./channel"):
                cid = ch.get("id")
                if not cid:
                    continue
                if cid not in chan_map:
                    chan_map[cid] = ch
                prog_map.setdefault(cid, [])

            for pr in root.findall("./programme"):
                cid = pr.get("channel")
                if cid:
                    prog_map.setdefault(cid, []).append(pr)

        tv_root = ET.Element("tv")
        chan_items = sorted(chan_map.items(), key=lambda kv: _chan_name(kv[1]))

        for cid, ch in chan_items:
            tv_root.append(ch)

        for cid, _ in chan_items:
            progs = sorted(prog_map.get(cid, []), key=lambda p: p.get("start") or "")
            for pr in progs:
                tv_root.append(pr)

        tree = ET.ElementTree(tv_root)
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(out_path, encoding="utf-8", xml_declaration=True)

    def _cleanup_temp_files(self, produced_files: list[tuple[str, str]]) -> None:
        """Clean up temporary files."""
        temp_dir = get_data_dir() / "temp"
        for _, path in produced_files:
            try:
                if temp_dir.as_posix() in path:
                    os.remove(path)
            except Exception:
                pass
        try:
            if temp_dir.exists():
                for f in temp_dir.iterdir():
                    if f.suffix == ".xml":
                        f.unlink()
        except Exception:
            pass
