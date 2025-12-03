"""
Zap2it/Gracenote API module for zap2xml-manager.

Fetches TV listings from the Gracenote grid API.
"""

import datetime as _dt
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from .config import get_data_dir


BASE_URL = "https://tvlistings.gracenote.com/api/grid"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/127.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
]

COUNTRY_3 = {"US": "USA", "CA": "CAN"}

# Streaming lineups that require postal codes
STREAMING_LINEUPS = {"HULUTV", "YTTV", "FUBOTV", "SLING", "DIRECTVSTR", "VIDGO", "FRNDLYTV", "PHILO"}

# Map full network names to common abbreviations
NETWORK_ABBREVIATIONS = {
    # Major broadcast networks
    "AMERICAN BROADCASTING COMPANY": "ABC",
    "NATIONAL BROADCASTING COMPANY": "NBC",
    "CBS TELEVISION NETWORK": "CBS",
    "FOX ENTERTAINMENT": "FOX",
    "FOX BROADCASTING COMPANY": "FOX",
    "THE CW TELEVISION NETWORK": "CW",
    "PUBLIC BROADCASTING SERVICE": "PBS",

    # Cable networks
    "TRINITY BROADCASTING NETWORK": "TBN",
    "HOME SHOPPING NETWORK": "HSN",
    "ENTERTAINMENT AND SPORTS PROGRAMMING NETWORK": "ESPN",
    "CARTOON NETWORK": "CN",
    "DISCOVERY CHANNEL": "DISC",
    "HISTORY CHANNEL": "HIST",
    "CABLE NEWS NETWORK": "CNN",
    "MUSIC TELEVISION": "MTV",
    "NICKELODEON": "NICK",
    "DISNEY CHANNEL": "DISNEY",
    "ANIMAL PLANET": "ANPL",
    "FOOD NETWORK": "FOOD",
    "HGTV": "HGTV",
    "LIFETIME TELEVISION": "LIFE",
    "SYFY": "SYFY",
    "SPIKE TV": "SPIKE",
    "BRAVO": "BRAVO",
    "USA NETWORK": "USA",
    "TNT": "TNT",
    "TBS": "TBS",
    "COMEDY CENTRAL": "COMEDY",
    "FX NETWORKS": "FX",
    "AMC": "AMC",
    "A&E NETWORK": "A&E",
    "WEATHER CHANNEL": "TWC",

    # Spanish language
    "TELEMUNDO": "TELE",
    "UNIVISION": "UNIV",

    # Subchannels / Digital networks
    "START TV NETWORK": "START",
    "DABL NETWORK": "DABL",
    "ME TV NETWORK": "METV",
    "HEROES & ICONS NETWORK": "H&I",
    "ANTENNA TV": "ANTENNA",
    "ION: INDEPENDENT TELEVISION": "ION",
    "BOUNCE TV": "BOUNCE",
    "COURT TV": "COURT",
    "COZI TV": "COZI",
    "GRIT": "GRIT",
    "LAFF": "LAFF",
    "COMET": "COMET",
    "CHARGE!": "CHARGE",
    "DEFY TV": "DEFY",
    "REWIND TV": "REWIND",
    "QUEST": "QUEST",
    "ION PLUS": "ION+",
    "ION MYSTERY HD": "IONM",
    "TRUE CRIME NETWORK": "TCN",
    "GAME SHOW CENTRAL": "GSC",
    "RETRO TELEVISION NETWORK": "RTV",
    "HEARTLAND NETWORK": "HEARTLAND",

    # Religious
    "DAYSTAR TELEVISION NETWORK": "DAYSTAR",
    "SONLIFE BROADCASTING NETWORK": "SONLIFE",
    "TBN INSPIRE": "TBNI",

    # International
    "NEW TANG DYNASTY TELEVISION": "NTD",
    "NHK WORLD TV": "NHK",
    "KBS WORLD": "KBS",
    "FIRST NATIONS EXPERIENCE": "FNX",
    "AMERICAN CLASSIC ENTERTAINMENT": "ACE",

    # Shopping
    "JEWELRY TV": "JTV",
    "SHOP LC": "SHOPLC",

    # News
    "SALEM NEWS CHANNEL": "SNC",
    "FOX WEATHER": "FOXW",
    "SPORTS NEWS HIGHLIGHTS": "SNH",

    # Other
    "BINGE-OTA": "BINGE",
    "THE NEST": "NEST",
    "PBS KIDS HD": "PBSKIDS",
    "CATCHY COMEDY": "CATCHY",
    "METV TOONS": "METVTOONS",
    "LATV NETWORKS": "LATV",
    "MOVIESPHERE GOLD": "MOVIESPHERE",
}


def _get_network_abbrev(full_name: str) -> str:
    """Get abbreviated network name from full name."""
    if not full_name:
        return ""
    upper = full_name.upper().strip()
    return NETWORK_ABBREVIATIONS.get(upper, "")


class FetchResult:
    """Result of a fetch operation."""

    def __init__(self, success: bool, message: str, file_path: Optional[str] = None):
        self.success = success
        self.message = message
        self.file_path = file_path


def _get_ua(user_agent: str = "") -> str:
    """Get a user agent string."""
    return user_agent or random.choice(USER_AGENTS)


def _is_ota(lineup_id: str) -> bool:
    """Check if lineup is OTA/LocalBroadcast."""
    s = (lineup_id or "").upper()
    return "OTA" in s or "LOCALBROADCAST" in s


def _is_streaming(lineup_id: str) -> bool:
    """Check if lineup is a streaming service."""
    s = (lineup_id or "").upper()
    m = re.match(r"^[A-Z]{3}-([^-]+)-", s)
    return m.group(1) in STREAMING_LINEUPS if m else False


def _needs_postal(lineup_id: str) -> bool:
    """Check if lineup needs a postal code."""
    return _is_ota(lineup_id) or _is_streaming(lineup_id)


def _get_headend(lineup_id: str) -> str:
    """Extract headend from lineup ID."""
    if _is_ota(lineup_id):
        return "lineupId"
    m = re.match(r"^[A-Z]{3}-([^-]+)-", lineup_id or "")
    return m.group(1) if m else "lineup"


def _get_device(lineup_id: str) -> str:
    """Get device parameter for lineup."""
    s = (lineup_id or "").upper().strip()
    if _is_ota(s) or _is_streaming(s) or s.endswith("-DEFAULT"):
        return "-"
    m = re.search(r"-([A-Z])$", s)
    return m.group(1) if m else "-"


def _build_url(lineup_id: str, headend_id: str, country: str, postal: str, time_sec: int, chunk_hours: int) -> str:
    """Build the API URL."""
    device = _get_device(lineup_id)
    is_streaming = _is_streaming(lineup_id)
    user_id = os.environ.get("ZAP2XML_USER_ID") or ("%08x" % random.getrandbits(32))

    params = [
        ("lineupId", lineup_id),
        ("timespan", str(chunk_hours)),
        ("headendId", headend_id),
        ("country", country),
        ("device", device),
    ]

    if not is_streaming:
        params.append(("isOverride", "true"))

    params.append(("postalCode", postal if postal else "-"))
    params.append(("time", str(time_sec)))

    if not is_streaming:
        params.append(("pref", "16,128"))

    params.extend([("userId", user_id), ("aid", "chi"), ("languagecode", "en-us")])

    qs = "&".join(f"{requests.utils.quote(k)}={requests.utils.quote(v)}" for k, v in params if v not in (None, ""))
    return f"{BASE_URL}?{qs}"


def _is_valid_value(val: Any) -> bool:
    """Check if a value is valid (not null, empty, or placeholder)."""
    if val is None:
        return False
    if isinstance(val, str):
        v = val.strip().lower()
        return v not in ("", "null", "none", "n/a", "independent", "ind")
    return bool(val)


def _normalize_channel(ch: dict[str, Any]) -> dict[str, Any]:
    """Normalize channel data from API response."""
    call_sign = ch.get("callSign") or ""

    # Get affiliate/network from all possible API fields
    # Check each field and use the first valid one
    affiliate = ""
    for field in ["affiliateName", "affiliateCallSign", "affiliate", "networkAffiliation", "network"]:
        val = ch.get(field)
        if _is_valid_value(val):
            affiliate = val
            break

    # Get the station name (full name like "WABC-TV New York" or "Cartoon Network")
    station_name = ""
    for field in ["name", "stationName", "displayName"]:
        val = ch.get(field)
        if _is_valid_value(val):
            station_name = val
            break

    # Get preferred/enhanced call sign if available
    preferred_call_sign = ""
    for field in ["preferredCallSign", "enhancedCallSign"]:
        val = ch.get(field)
        if _is_valid_value(val):
            preferred_call_sign = val
            break

    # Get channel number
    channel_no = ch.get("channelNo") or ch.get("channel") or ""

    # Build friendly display name (e.g., "ABC 7.1", "CBS 2.1")
    network_abbrev = _get_network_abbrev(affiliate)
    if network_abbrev and channel_no:
        # Extract just the major channel number for display (e.g., "7" from "7.1")
        major_ch = str(channel_no).split(".")[0]
        friendly_name = f"{network_abbrev} {major_ch}"
    elif network_abbrev:
        friendly_name = network_abbrev
    elif affiliate:
        # Use affiliate name if no abbreviation exists
        friendly_name = affiliate
    else:
        friendly_name = call_sign

    return {
        "stationId": ch.get("stationId") or ch.get("channelId"),
        "channelId": ch.get("channelId"),
        "callSign": call_sign,
        "preferredCallSign": preferred_call_sign,
        "channelNo": channel_no,
        "affiliateName": affiliate,
        "networkAbbrev": network_abbrev,
        "friendlyName": friendly_name,
        "stationName": station_name,
        "thumbnail": ch.get("thumbnail"),
        "events": [],
    }


def _merge_filter_tags(ev: dict[str, Any]) -> None:
    """Merge filter tags into genres."""
    program = ev.get("program") or {}
    genres = set()
    for g in program.get("genres") or []:
        if isinstance(g, dict) and g.get("name"):
            genres.add(str(g["name"]).lower())
        elif isinstance(g, str):
            genres.add(g.lower())
    for tag in ev.get("filter") or []:
        genres.add(re.sub(r"^filter-", "", str(tag), flags=re.I).strip().lower())
    if genres:
        program["genres"] = sorted(list(genres))


def fetch_zap2it_epg(
    lineup_id: str,
    country: str,
    postal_code: str = "",
    timespan_hours: int = 72,
    delay_seconds: int = 0,
    user_agent: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
    prefer_affiliate_names: bool = False,
) -> FetchResult:
    """Fetch EPG data from Zap2it/Gracenote."""
    log = log_callback or (lambda msg: print(msg, file=sys.stderr, flush=True))

    c3 = COUNTRY_3.get(country.upper(), country.upper())

    if not lineup_id:
        return FetchResult(False, "Lineup ID is required")

    if _needs_postal(lineup_id) and not postal_code:
        lineup_type = "OTA/LocalBroadcast" if _is_ota(lineup_id) else "streaming service"
        return FetchResult(False, f"Postal code required for {lineup_type} lineups")

    # Determine API lineup and headend
    if _is_ota(lineup_id):
        api_lineup = f"{c3}-lineupId-DEFAULT"
        headend = "lineupId"
    else:
        api_lineup = lineup_id
        headend = _get_headend(lineup_id)

    # Setup session
    sess = requests.Session()
    try:
        sess.get("https://tvlistings.gracenote.com/", headers={"User-Agent": _get_ua(user_agent)}, timeout=20)
    except Exception:
        pass

    headers_base = {
        "User-Agent": _get_ua(user_agent),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://tvlistings.gracenote.com/",
        "Origin": "https://tvlistings.gracenote.com",
        "Cache-Control": "no-cache",
    }

    channels_map: dict[str, dict[str, Any]] = {}
    base_time = int(time.time())
    chunk_hours = 6
    offsets = list(range(0, timespan_hours, chunk_hours))
    max_retries = 3

    for idx, offset in enumerate(offsets):
        t = base_time + offset * 3600
        url = _build_url(api_lineup, headend, c3, postal_code, t, chunk_hours)

        attempt = 0
        while True:
            attempt += 1
            headers = dict(headers_base)
            headers["User-Agent"] = _get_ua(user_agent)

            log(f"  GET chunk {idx + 1}/{len(offsets)} attempt {attempt}/{max_retries}")

            try:
                r = sess.get(url, headers=headers, timeout=30)
            except requests.RequestException as e:
                if attempt <= max_retries:
                    sleep_s = min(30, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                return FetchResult(False, f"Network error: {e}")

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    return FetchResult(False, f"Invalid JSON response for chunk {idx + 1}")

                for ch in data.get("channels", []) or []:
                    cid = str(ch.get("channelId"))
                    if cid not in channels_map:
                        # Log raw API values for first few channels
                        if len(channels_map) < 5:
                            log(f"    Raw: callSign={ch.get('callSign')!r}, "
                                f"affiliateName={ch.get('affiliateName')!r}, "
                                f"affiliateCallSign={ch.get('affiliateCallSign')!r}, "
                                f"stationGenres={ch.get('stationGenres')!r}")
                        normalized = _normalize_channel(ch)
                        channels_map[cid] = normalized
                        # Log channel info with friendly name
                        friendly = normalized.get('friendlyName') or normalized.get('callSign')
                        ch_no = normalized.get('channelNo') or ''
                        affiliate_display = normalized.get('networkAbbrev') or normalized.get('affiliateName') or '(none)'
                        log(f"    [{ch_no}] {friendly} ({normalized.get('callSign')}) | {affiliate_display}")
                    for ev in ch.get("events", []) or []:
                        _merge_filter_tags(ev)
                        channels_map[cid]["events"].append(ev)
                break

            elif r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt <= max_retries:
                    sleep_s = min(60, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                break
            else:
                break

        if delay_seconds > 0 and idx < len(offsets) - 1:
            time.sleep(delay_seconds)

    if not channels_map:
        return FetchResult(False, "No channels found in response")

    # Sort channels: by affiliate name first (to group similar channels), then by call sign
    channels = sorted(
        channels_map.values(),
        key=lambda c: (
            str(c.get("affiliateName") or c.get("stationName") or "zzz").casefold(),
            str(c.get("callSign") or "").casefold(),
            str(c.get("channelNo") or "")
        )
    )

    # Write XMLTV
    temp_dir = get_data_dir() / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^\w\-]", "_", lineup_id)
    output_path = temp_dir / f"zap2it_{safe_id}.xml"

    _write_xmltv(channels, output_path, prefer_affiliate_names=prefer_affiliate_names)

    return FetchResult(True, "OK", str(output_path))


def _write_xmltv(channels: list[dict[str, Any]], out_path: Path, prefer_affiliate_names: bool = False) -> None:
    """Write XMLTV format to file."""
    tv = ET.Element("tv")

    # Write channels
    for ch in channels:
        cid = str(ch.get("stationId") or ch.get("channelId") or "")
        ch_el = ET.SubElement(tv, "channel", {"id": cid})

        call_sign = ch.get("callSign") or ""
        preferred_call_sign = ch.get("preferredCallSign") or ""
        affiliate = ch.get("affiliateName") or ""
        network_abbrev = ch.get("networkAbbrev") or ""
        friendly_name = ch.get("friendlyName") or ""
        station_name = ch.get("stationName") or ""
        channel_no = ch.get("channelNo") or ""

        # Use preferred call sign if available (more readable)
        display_call_sign = preferred_call_sign or call_sign

        # Build display names - friendly name first (e.g., "ABC 7"), then alternatives
        if prefer_affiliate_names or network_abbrev:
            # Put friendly name first (e.g., "ABC 7", "CBS 2")
            if friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(friendly_name)
            # Add network abbreviation if different from friendly name
            if network_abbrev and network_abbrev != friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(network_abbrev)
            # Add call sign
            if display_call_sign and display_call_sign != friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(display_call_sign)
            # Add channel number
            if channel_no:
                ET.SubElement(ch_el, "display-name").text = str(channel_no)
            # Add full affiliate name if different
            if affiliate and affiliate != friendly_name and affiliate != network_abbrev:
                ET.SubElement(ch_el, "display-name").text = str(affiliate)
        else:
            # Fallback for channels without network abbreviation
            if friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(friendly_name)
            if display_call_sign and display_call_sign != friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(display_call_sign)
            if channel_no:
                ET.SubElement(ch_el, "display-name").text = str(channel_no)
            if affiliate and affiliate != friendly_name:
                ET.SubElement(ch_el, "display-name").text = str(affiliate)

        thumb = ch.get("thumbnail")
        if thumb:
            ET.SubElement(ch_el, "icon", {"src": _ensure_asset_url(str(thumb))})

    # Write programmes
    for ch in channels:
        events = sorted(ch.get("events", []), key=lambda e: e.get("startTime") or "")
        for ev in events:
            program = ev.get("program") or {}
            start_dt = _parse_time(ev.get("startTime") or ev.get("start"))
            end_dt = _parse_time(ev.get("endTime") or ev.get("end"))

            if not start_dt or not end_dt:
                continue

            prog_el = ET.SubElement(tv, "programme", {
                "start": _xmltv_time(start_dt),
                "stop": _xmltv_time(end_dt),
                "channel": str(ch.get("stationId") or ch.get("channelId") or ""),
            })

            # Title
            title = _first(program.get("title")) or _first(ev.get("title"))
            if title:
                ET.SubElement(prog_el, "title").text = str(title)

            # Sub-title (episode title)
            if program.get("episodeTitle"):
                ET.SubElement(prog_el, "sub-title").text = str(program["episodeTitle"])

            # Description
            desc = (program.get("shortDesc") or program.get("longDescription") or
                    program.get("shortDescription") or ev.get("description"))
            if desc:
                ET.SubElement(prog_el, "desc").text = str(desc)

            # Date
            if program.get("releaseYear"):
                ET.SubElement(prog_el, "date").text = str(program["releaseYear"])
            elif start_dt:
                ET.SubElement(prog_el, "date").text = start_dt.strftime("%Y%m%d")

            # Categories
            genres = program.get("genres") or []
            wrote_category = False
            for g in sorted(genres, key=lambda x: str(x)):
                name = g if isinstance(g, str) else (g.get("name") or str(g))
                if name:
                    wrote_category = True
                    ET.SubElement(prog_el, "category", {"lang": "en"}).text = name.capitalize()

            # Default "Series" category if no genres and not movie/sports
            if not wrote_category and not _is_movie_or_sports(ev, program):
                ET.SubElement(prog_el, "category", {"lang": "en"}).text = "Series"

            # Length/duration
            dur = ev.get("duration") or program.get("duration")
            if dur:
                try:
                    dur_int = int(dur)
                    ET.SubElement(prog_el, "length", {"units": "minutes"}).text = str(dur_int)
                except (ValueError, TypeError):
                    pass

            # Icon
            icon_url = _get_icon(program, ev)
            if icon_url:
                ET.SubElement(prog_el, "icon", {"src": icon_url})

            # URL and episode numbering
            tms_id = program.get("tmsId") or ev.get("tmsId")
            series_id = (
                program.get("seriesId") or program.get("rootId") or
                (tms_id[:-4] if tms_id and len(str(tms_id)) > 4 and str(tms_id)[-4:].isdigit() else None)
            )

            # URL
            if series_id and tms_id:
                ET.SubElement(prog_el, "url").text = (
                    f"https://tvlistings.gracenote.com//overview.html?"
                    f"programSeriesId={series_id}&tmsId={tms_id}"
                )

            # dd_progid episode number
            if series_id and tms_id and str(tms_id)[-4:].isdigit():
                dd_val = f"{series_id}.{str(tms_id)[-4:]}"
                ET.SubElement(prog_el, "episode-num", {"system": "dd_progid"}).text = dd_val
            elif tms_id:
                s = str(tms_id)
                if len(s) >= 6 and s[-4:].isdigit():
                    ET.SubElement(prog_el, "episode-num", {"system": "dd_progid"}).text = f"{s[:-4]}.{s[-4:]}"
                else:
                    ET.SubElement(prog_el, "episode-num", {"system": "dd_progid"}).text = s

            # Season/episode numbering
            season = _get_int(program, "season", "seasonNumber", "seasonNum", "seasonNo")
            episode = _get_int(program, "episode", "episodeNumber", "episodeNum", "epNum", "number")

            xmltv_ns_val = None
            onscreen_val = None
            common_val = None

            if season is not None or episode is not None:
                if season is not None:
                    s_ns = season - 1
                else:
                    s_ns = (start_dt.year - 1) if start_dt else -1
                e_ns = (episode - 1) if episode is not None else -1
                xmltv_ns_val = f"{s_ns}.{e_ns}."
                if season is not None and episode is not None:
                    onscreen_val = f"S{season:02}E{episode:02}"
                    common_val = f"S{season:02}E{episode:02}"
            else:
                # Fallback to date-based encoding
                xmltv_ns_val = _xmltv_ns_from_date(start_dt)

            if xmltv_ns_val:
                ET.SubElement(prog_el, "episode-num", {"system": "xmltv_ns"}).text = xmltv_ns_val
            if onscreen_val:
                ET.SubElement(prog_el, "episode-num", {"system": "onscreen"}).text = onscreen_val
            if common_val:
                ET.SubElement(prog_el, "episode-num", {"system": "common"}).text = common_val

            # Flags: live, new, previously-shown
            flags_raw = ev.get("flag") or ev.get("flags") or []
            flags = {str(f).strip().lower() for f in flags_raw}
            is_live = ("live" in flags) or bool(program.get("live"))
            is_new = ("new" in flags) or any("premiere" in f for f in flags) or bool(program.get("new"))

            if is_live:
                ET.SubElement(prog_el, "live")
            if is_new:
                ET.SubElement(prog_el, "new")

            if not is_new and not is_live:
                ps = ET.SubElement(prog_el, "previously-shown")
                air_date = program.get("originalAirDate") or program.get("airDate")
                if air_date:
                    try:
                        d = _parse_time(air_date) or _parse_time(str(air_date) + "T00:00:00Z")
                        if d:
                            ps.set("start", d.strftime("%Y%m%d") + "000000")
                    except Exception:
                        pass

            # Audio and subtitles
            ET.SubElement(prog_el, "audio", {"type": "stereo"})
            ET.SubElement(prog_el, "subtitles", {"type": "teletext"})

            # Rating
            ratings = program.get("ratings") or ev.get("ratings") or []
            if isinstance(ratings, list) and ratings:
                r0 = ratings[0]
                code = r0.get("code") or r0.get("rating")
                sysname = r0.get("system") or "MPAA"
                if code:
                    r_el = ET.SubElement(prog_el, "rating", {"system": str(sysname)})
                    ET.SubElement(r_el, "value").text = str(code)
            elif program.get("rating"):
                r_el = ET.SubElement(prog_el, "rating", {"system": "MPAA"})
                ET.SubElement(r_el, "value").text = str(program["rating"])

    tree = ET.ElementTree(tv)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)


def _first(x: Any) -> Any:
    """Get first element if list."""
    return x[0] if isinstance(x, (list, tuple)) and x else x


def _parse_time(s: Any) -> Optional[_dt.datetime]:
    """Parse time string to datetime."""
    if not s:
        return None
    try:
        st = str(s)
        if st.endswith("Z"):
            return _dt.datetime.fromisoformat(st[:-1]).replace(tzinfo=_dt.timezone.utc)
        if re.fullmatch(r"\d{10}", st):
            return _dt.datetime.fromtimestamp(int(st), tz=_dt.timezone.utc)
        return _dt.datetime.fromisoformat(st.replace("Z", ""))
    except Exception:
        return None


def _xmltv_time(dtobj: _dt.datetime) -> str:
    """Format datetime for XMLTV."""
    if dtobj.tzinfo is None:
        dtobj = dtobj.replace(tzinfo=_dt.timezone.utc)
    return dtobj.strftime("%Y%m%d%H%M%S %z")


def _xmltv_ns_from_date(dtobj: Optional[_dt.datetime]) -> Optional[str]:
    """Fallback encoding: YYYY-1.MMDD-1. Example: 2025-09-12 -> 2024.0911."""
    if not dtobj:
        return None
    year_minus = dtobj.year - 1
    month_str = dtobj.strftime("%m")
    day_minus = dtobj.day - 1
    return f"{year_minus}.{month_str}{day_minus:02d}."


def _is_movie_or_sports(ev: dict[str, Any], program: dict[str, Any]) -> bool:
    """Check if program is movie or sports."""
    genres = program.get("genres") or []
    genres = [g.lower() if isinstance(g, str) else str(g).lower() for g in genres]
    etype = (program.get("entityType") or program.get("type") or "").lower()
    return ("movie" in genres or etype == "movie" or "sports" in genres or etype == "sports")


def _ensure_asset_url(s: str) -> str:
    """Ensure full asset URL."""
    if not s:
        return s
    s0 = str(s).split("?", 1)[0]
    if s0.startswith("//"):
        s0 = "https:" + s0
    if not s0.startswith("http"):
        s0 = "https://zap2it.tmsimg.com/assets/" + s0.lstrip("/")
    if "." not in s0.rsplit("/", 1)[-1]:
        s0 += ".jpg"
    return s0


def _get_icon(program: dict[str, Any], ev: dict[str, Any]) -> Optional[str]:
    """Get program icon URL."""
    pref = program.get("preferredImage") or {}
    icon = pref.get("uri") if isinstance(pref, dict) else None
    icon = icon or program.get("image") or ev.get("thumbnail")
    return _ensure_asset_url(str(icon)) if icon else None


def _get_int(d: dict[str, Any], *keys: str) -> Optional[int]:
    """Get integer value from dict."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            try:
                return int(v)
            except (ValueError, TypeError):
                pass
    return None
