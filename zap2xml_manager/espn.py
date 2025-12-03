"""
ESPN+ schedule module for zap2xml-manager.

Fetches ESPN+ live events schedule and generates XMLTV.
"""

import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from .config import get_data_dir

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None


ESPN_PLUS_SCHEDULE_URL = "https://www.espn.com/watch/schedule/_/type/live/channel/ESPN_PLUS"
ESPN_LOGO_BASE = "https://a.espncdn.com/i/teamlogos"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
]

# Team abbreviation mappings for major leagues
NHL_TEAMS = {
    "anaheim ducks": "ana", "arizona coyotes": "ari", "boston bruins": "bos",
    "buffalo sabres": "buf", "calgary flames": "cgy", "carolina hurricanes": "car",
    "chicago blackhawks": "chi", "colorado avalanche": "col", "columbus blue jackets": "cbj",
    "dallas stars": "dal", "detroit red wings": "det", "edmonton oilers": "edm",
    "florida panthers": "fla", "los angeles kings": "la", "minnesota wild": "min",
    "montreal canadiens": "mtl", "nashville predators": "nsh", "new jersey devils": "njd",
    "new york islanders": "nyi", "new york rangers": "nyr", "ottawa senators": "ott",
    "philadelphia flyers": "phi", "pittsburgh penguins": "pit", "san jose sharks": "sj",
    "seattle kraken": "sea", "st. louis blues": "stl", "tampa bay lightning": "tb",
    "toronto maple leafs": "tor", "utah hockey club": "uta", "vancouver canucks": "van",
    "vegas golden knights": "vgk", "washington capitals": "wsh", "winnipeg jets": "wpg",
}

NBA_TEAMS = {
    "atlanta hawks": "atl", "boston celtics": "bos", "brooklyn nets": "bkn",
    "charlotte hornets": "cha", "chicago bulls": "chi", "cleveland cavaliers": "cle",
    "dallas mavericks": "dal", "denver nuggets": "den", "detroit pistons": "det",
    "golden state warriors": "gs", "houston rockets": "hou", "indiana pacers": "ind",
    "los angeles clippers": "lac", "los angeles lakers": "lal", "la clippers": "lac",
    "la lakers": "lal", "memphis grizzlies": "mem", "miami heat": "mia",
    "milwaukee bucks": "mil", "minnesota timberwolves": "min", "new orleans pelicans": "no",
    "new york knicks": "ny", "oklahoma city thunder": "okc", "orlando magic": "orl",
    "philadelphia 76ers": "phi", "phoenix suns": "phx", "portland trail blazers": "por",
    "sacramento kings": "sac", "san antonio spurs": "sa", "toronto raptors": "tor",
    "utah jazz": "uta", "washington wizards": "wsh",
}

NFL_TEAMS = {
    "arizona cardinals": "ari", "atlanta falcons": "atl", "baltimore ravens": "bal",
    "buffalo bills": "buf", "carolina panthers": "car", "chicago bears": "chi",
    "cincinnati bengals": "cin", "cleveland browns": "cle", "dallas cowboys": "dal",
    "denver broncos": "den", "detroit lions": "det", "green bay packers": "gb",
    "houston texans": "hou", "indianapolis colts": "ind", "jacksonville jaguars": "jax",
    "kansas city chiefs": "kc", "las vegas raiders": "lv", "los angeles chargers": "lac",
    "los angeles rams": "lar", "miami dolphins": "mia", "minnesota vikings": "min",
    "new england patriots": "ne", "new orleans saints": "no", "new york giants": "nyg",
    "new york jets": "nyj", "philadelphia eagles": "phi", "pittsburgh steelers": "pit",
    "san francisco 49ers": "sf", "seattle seahawks": "sea", "tampa bay buccaneers": "tb",
    "tennessee titans": "ten", "washington commanders": "wsh",
}

MLB_TEAMS = {
    "arizona diamondbacks": "ari", "atlanta braves": "atl", "baltimore orioles": "bal",
    "boston red sox": "bos", "chicago cubs": "chc", "chicago white sox": "chw",
    "cincinnati reds": "cin", "cleveland guardians": "cle", "colorado rockies": "col",
    "detroit tigers": "det", "houston astros": "hou", "kansas city royals": "kc",
    "los angeles angels": "laa", "los angeles dodgers": "lad", "miami marlins": "mia",
    "milwaukee brewers": "mil", "minnesota twins": "min", "new york mets": "nym",
    "new york yankees": "nyy", "oakland athletics": "oak", "philadelphia phillies": "phi",
    "pittsburgh pirates": "pit", "san diego padres": "sd", "san francisco giants": "sf",
    "seattle mariners": "sea", "st. louis cardinals": "stl", "tampa bay rays": "tb",
    "texas rangers": "tex", "toronto blue jays": "tor", "washington nationals": "wsh",
}

MLS_TEAMS = {
    "atlanta united": "atl", "austin fc": "atx", "cf montreal": "mtl",
    "charlotte fc": "clt", "chicago fire": "chi", "colorado rapids": "col",
    "columbus crew": "clb", "dc united": "dc", "fc cincinnati": "cin",
    "fc dallas": "dal", "houston dynamo": "hou", "inter miami": "mia",
    "la galaxy": "la", "lafc": "lafc", "minnesota united": "min",
    "nashville sc": "nsh", "new england revolution": "ne", "new york city fc": "nyc",
    "new york red bulls": "nyrb", "orlando city": "orl", "philadelphia union": "phi",
    "portland timbers": "por", "real salt lake": "rsl", "san jose earthquakes": "sj",
    "seattle sounders": "sea", "sporting kansas city": "skc", "st. louis city sc": "stl",
    "toronto fc": "tor", "vancouver whitecaps": "van",
}


class FetchResult:
    """Result of a fetch operation."""

    def __init__(self, success: bool, message: str, file_path: Optional[str] = None):
        self.success = success
        self.message = message
        self.file_path = file_path


def _get_team_logo_url(team_name: str, league: str = "") -> Optional[str]:
    """Get ESPN CDN URL for a team's logo based on team name."""
    team_lower = team_name.lower().strip()
    for suffix in [" (home)", " (away)", " broadcast", " (national broadcast)"]:
        team_lower = team_lower.replace(suffix, "")

    league_lower = league.lower()

    if "nhl" in league_lower or "hockey" in league_lower or team_lower in NHL_TEAMS:
        abbr = NHL_TEAMS.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/nhl/500/{abbr}.png"

    if "nba" in league_lower or "basketball" in league_lower or team_lower in NBA_TEAMS:
        abbr = NBA_TEAMS.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/nba/500/{abbr}.png"

    if "nfl" in league_lower or "football" in league_lower or team_lower in NFL_TEAMS:
        abbr = NFL_TEAMS.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/nfl/500/{abbr}.png"

    if "mlb" in league_lower or "baseball" in league_lower or team_lower in MLB_TEAMS:
        abbr = MLB_TEAMS.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/mlb/500/{abbr}.png"

    if "mls" in league_lower or "soccer" in league_lower or team_lower in MLS_TEAMS:
        abbr = MLS_TEAMS.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/soccer/500/{abbr}.png"

    # Fallback: search all leagues
    for teams, sport in [(NHL_TEAMS, "nhl"), (NBA_TEAMS, "nba"), (NFL_TEAMS, "nfl"),
                         (MLB_TEAMS, "mlb"), (MLS_TEAMS, "soccer")]:
        abbr = teams.get(team_lower)
        if abbr:
            return f"{ESPN_LOGO_BASE}/{sport}/500/{abbr}.png"

    return None


def _extract_teams_from_title(title: str) -> tuple[Optional[str], Optional[str]]:
    """Extract team names from event title like 'Team A vs. Team B'."""
    clean_title = re.sub(r"\s*\([^)]*broadcast[^)]*\)", "", title, flags=re.I)
    patterns = [
        r"^(.+?)\s+vs\.?\s+(.+?)$",
        r"^(.+?)\s+@\s+(.+?)$",
        r"^(.+?)\s+at\s+(.+?)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, clean_title, re.I)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, None


def fetch_espn_plus_epg(
    num_channels: int = 0,  # 0 = auto (based on events found)
    channel_offset: int = 0,
    log_callback: Optional[Callable[[str], None]] = None,
) -> FetchResult:
    """Fetch ESPN+ schedule and generate XMLTV."""
    log = log_callback or (lambda msg: print(msg, file=sys.stderr, flush=True))

    if not HAS_BS4:
        return FetchResult(False, "beautifulsoup4 is required but not installed")

    log("  Fetching ESPN+ schedule...")

    try:
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        response = requests.get(ESPN_PLUS_SCHEDULE_URL, headers=headers, timeout=30)
        response.raise_for_status()
        html = response.text
    except requests.RequestException as e:
        return FetchResult(False, f"Network error: {e}")

    log(f"  Received {len(html)} bytes")

    events = _extract_events_from_html(html)
    log(f"  Parsed {len(events)} raw events")

    valid_events = [e for e in events if _is_valid_event(e)]
    log(f"  {len(valid_events)} valid events after filtering")

    if not valid_events:
        return FetchResult(False, "No valid events found")

    processed_events = _process_events(valid_events, channel_offset)

    # Auto-determine number of channels if set to 0
    if num_channels <= 0:
        num_channels = len(processed_events) + channel_offset
        log(f"  Auto channels: {num_channels}")

    temp_dir = get_data_dir() / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / "espn_plus.xml"

    _generate_xmltv(processed_events, num_channels, output_path)

    return FetchResult(True, f"Generated {len(processed_events)} events across {num_channels} channels", str(output_path))


def _extract_events_from_html(html: str) -> list[dict[str, Any]]:
    """Parse events from ESPN schedule HTML."""
    soup = BeautifulSoup(html, "html.parser")
    events = []

    # Strategy 1: Look for article tags
    for article in soup.find_all("article"):
        event = _parse_event_element(article)
        if event:
            events.append(event)

    # Strategy 2: Look for event card structures
    selectors = [
        {"class_": re.compile(r".*[Ee]vent.*", re.I)},
        {"class_": re.compile(r".*[Cc]ard.*", re.I)},
        {"class_": re.compile(r".*[Ss]chedule.*[Ii]tem.*", re.I)},
        {"class_": re.compile(r".*[Ww]atch.*[Cc]ard.*", re.I)},
    ]
    for selector in selectors:
        for elem in soup.find_all("div", **selector):
            event = _parse_event_element(elem)
            if event and event not in events:
                events.append(event)

    # Strategy 3: Look for watch links
    current_sport = "Sports"
    current_time = None
    for link in soup.find_all("a", href=re.compile(r"/watch/")):
        parent = link.parent
        for _ in range(5):
            if parent is None:
                break
            time_elem = parent.find(string=re.compile(r"\d{1,2}:\d{2}\s*(am|pm)", re.I))
            if time_elem:
                current_time = str(time_elem).strip()
            header = parent.find(["h1", "h2", "h3", "h4"], string=True)
            if header:
                current_sport = header.get_text(strip=True)
            parent = parent.parent

        link_text = link.get_text(strip=True)
        if link_text and len(link_text) > 3:
            event = {
                "title": link_text,
                "league": current_sport,
                "start_time": current_time,
                "url": link.get("href", ""),
                "image": None,
            }
            img = link.find("img")
            if img:
                event["image"] = img.get("src") or img.get("data-src")
            if event not in events:
                events.append(event)

    # Strategy 4: Parse sport sections
    events.extend(_parse_sport_sections(soup))

    return events


def _parse_sport_sections(soup) -> list[dict[str, Any]]:
    """Parse events organized by sport sections."""
    events = []
    sport_headers = soup.find_all(["h1", "h2", "h3"], string=re.compile(
        r"Basketball|Football|Hockey|Soccer|Baseball|Tennis|Golf|MMA|UFC|Boxing|Cricket|Rugby|"
        r"NCAA|NBA|NFL|NHL|MLB|MLS|Premier League|La Liga|Champions League",
        re.I
    ))

    for header in sport_headers:
        sport_name = header.get_text(strip=True)
        container = header.parent
        if container is None:
            continue

        links = container.find_all("a", href=re.compile(r"/watch/|/espnplus/"))
        for link in links:
            link_text = link.get_text(strip=True)
            if not link_text or len(link_text) < 5 or link_text.lower() == sport_name.lower():
                continue

            start_time = None
            parent = link.parent
            for _ in range(3):
                if parent is None:
                    break
                time_match = re.search(r"\d{1,2}:\d{2}\s*(am|pm)", parent.get_text(), re.I)
                if time_match:
                    start_time = time_match.group()
                    break
                parent = parent.parent

            events.append({
                "title": link_text,
                "league": sport_name,
                "start_time": start_time,
                "image": None,
                "url": link.get("href", ""),
            })

    return events


def _parse_event_element(elem) -> Optional[dict[str, Any]]:
    """Parse a single event element."""
    if elem is None:
        return None

    title = None
    for tag in ["h1", "h2", "h3", "h4", "span", "a"]:
        title_elem = elem.find(tag, class_=re.compile(r".*[Tt]itle.*", re.I))
        if title_elem:
            title = title_elem.get_text(strip=True)
            break

    if not title:
        text = elem.get_text(strip=True)
        if text and 5 < len(text) < 200:
            title = text

    if not title:
        return None

    league = "Sports"
    league_elem = elem.find(class_=re.compile(r".*[Ll]eague.*|.*[Ss]port.*", re.I))
    if league_elem:
        league = league_elem.get_text(strip=True)

    start_time = None
    time_elem = elem.find(class_=re.compile(r".*[Tt]ime.*|.*[Dd]ate.*", re.I))
    if time_elem:
        start_time = time_elem.get_text(strip=True)
    else:
        time_match = re.search(r"\d{1,2}:\d{2}\s*(am|pm)", elem.get_text(), re.I)
        if time_match:
            start_time = time_match.group()

    image = None
    img_elem = elem.find("img")
    if img_elem:
        image = img_elem.get("src") or img_elem.get("data-src")

    return {"title": title, "league": league, "start_time": start_time, "image": image}


def _is_valid_event(event: dict[str, Any]) -> bool:
    """Check if event is valid (not navigation/generic)."""
    skip_titles = {
        "watch", "schedule", "replays", "schedule & replays", "home", "espn+",
        "espn plus", "live", "upcoming", "featured", "browse", "sign in",
        "subscribe", "more", "see all", "view all",
    }
    title = event.get("title", "").lower().strip()
    league = event.get("league", "").lower()

    if title in skip_titles or len(title) <= 3 or title.startswith("sign "):
        return False

    is_event = (
        " vs " in title or " vs. " in title or " at " in title
        or any(kw in title for kw in [
            "game", "match", "fight", "bout", "race", "championship",
            "tournament", "cup", "league", "series", "open", "classic",
        ])
        or any(kw in league for kw in [
            "nba", "nfl", "nhl", "mlb", "mls", "ncaa", "ufc", "pga",
            "basketball", "football", "hockey", "soccer", "baseball",
            "tennis", "golf", "cricket", "rugby", "boxing", "mma",
        ])
    )
    return is_event


def _process_events(events: list[dict[str, Any]], channel_offset: int) -> list[dict[str, Any]]:
    """Process events and assign channel numbers."""
    reference_date = datetime.now(timezone.utc)
    processed = []

    for index, event in enumerate(events):
        channel_num = index + channel_offset
        channel_id = f"ESPN+{channel_num:02d}.rtv"

        start_dt = _parse_time_string(event.get("start_time"), reference_date)
        if start_dt is None:
            start_dt = reference_date + timedelta(minutes=index * 30)

        end_dt = start_dt + timedelta(hours=2)

        # Get image URL - try ESPN artwork first
        title = event.get("title", "Unknown Event")
        league = event.get("league", "ESPN+")
        image = None

        event_url = event.get("url", "")
        if event_url:
            stream_id_match = re.search(r"/id/([a-f0-9\-]{36})", event_url)
            if stream_id_match:
                stream_id = stream_id_match.group(1)
                image = f"https://s.secure.espncdn.com/stitcher/artwork/collections/airings/{stream_id}/16x9.jpg"

        # Fall back to team logo if no artwork
        if not image:
            team1, team2 = _extract_teams_from_title(title)
            if team1:
                logo_url = _get_team_logo_url(team1, league)
                if logo_url:
                    image = logo_url
            if not image and team2:
                logo_url = _get_team_logo_url(team2, league)
                if logo_url:
                    image = logo_url

        if not image:
            image = event.get("image")

        processed.append({
            "channel": channel_id,
            "channel_num": channel_num,
            "title": title,
            "league": league,
            "start_time": event.get("start_time", ""),
            "start_datetime": start_dt,
            "end_datetime": end_dt,
            "image": image,
            "url": event_url,
        })

    return processed


def _parse_time_string(time_str: str, reference_date: datetime) -> Optional[datetime]:
    """Parse ESPN time strings like '8:00 pm'."""
    if not time_str:
        return None

    time_str = time_str.strip().lower()
    patterns = [r"(\d{1,2}):(\d{2})\s*(am|pm)", r"(\d{1,2})\s*(am|pm)"]

    for pattern in patterns:
        match = re.match(pattern, time_str)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                hour, minute, ampm = int(groups[0]), int(groups[1]), groups[2]
            else:
                hour, ampm = int(groups[0]), groups[1]
                minute = 0

            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

            try:
                from zoneinfo import ZoneInfo
                eastern = ZoneInfo("America/New_York")
                local_dt = reference_date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=eastern)
                return local_dt.astimezone(timezone.utc)
            except ImportError:
                utc_hour = (hour + 5) % 24
                return reference_date.replace(hour=utc_hour, minute=minute, second=0, microsecond=0, tzinfo=timezone.utc)

    return None


def _generate_xmltv(events: list[dict[str, Any]], num_channels: int, output_path: Path) -> None:
    """Generate XMLTV format from events."""
    tv = ET.Element("tv", {"generator-info-name": "zap2xml-manager"})

    for i in range(num_channels):
        channel_id = f"ESPN+{i:02d}.rtv"
        ch_el = ET.SubElement(tv, "channel", {"id": channel_id})
        ET.SubElement(ch_el, "display-name").text = f"ESPN+ {i:02d}"
        ET.SubElement(ch_el, "display-name").text = f"ESPN+{i:02d}.rtv"
        ET.SubElement(ch_el, "display-name").text = "ESPN+"
        ET.SubElement(ch_el, "icon", {"src": "https://a.espncdn.com/combiner/i?img=/i/espnplus/espnplus-color.png"})

    channels_with_events = {e.get("channel_num", -1) for e in events}

    now = datetime.now(timezone.utc)
    placeholder_start = now.replace(minute=0, second=0, microsecond=0)
    placeholder_end = placeholder_start + timedelta(hours=6)

    for i in range(num_channels):
        if i not in channels_with_events:
            channel_id = f"ESPN+{i:02d}.rtv"
            prog_el = ET.SubElement(tv, "programme", {
                "start": placeholder_start.strftime("%Y%m%d%H%M%S %z").replace(":", ""),
                "stop": placeholder_end.strftime("%Y%m%d%H%M%S %z").replace(":", ""),
                "channel": channel_id,
            })
            ET.SubElement(prog_el, "title", {"lang": "en"}).text = "No Event Scheduled"
            ET.SubElement(prog_el, "desc", {"lang": "en"}).text = "This ESPN+ channel is currently idle."
            ET.SubElement(prog_el, "category", {"lang": "en"}).text = "Sports"

    for event in events:
        start_dt = event.get("start_datetime")
        end_dt = event.get("end_datetime")
        if not start_dt or not end_dt:
            continue

        prog_el = ET.SubElement(tv, "programme", {
            "start": start_dt.strftime("%Y%m%d%H%M%S %z").replace(":", ""),
            "stop": end_dt.strftime("%Y%m%d%H%M%S %z").replace(":", ""),
            "channel": event["channel"],
        })

        ET.SubElement(prog_el, "title", {"lang": "en"}).text = event["title"]

        if event.get("league"):
            ET.SubElement(prog_el, "sub-title", {"lang": "en"}).text = event["league"]

        desc_parts = []
        if event.get("league"):
            desc_parts.append(f"Sport: {event['league']}")
        if event.get("start_time"):
            desc_parts.append(f"Scheduled: {event['start_time']}")
        desc_parts.append("Available on ESPN+")
        ET.SubElement(prog_el, "desc", {"lang": "en"}).text = " | ".join(desc_parts)

        ET.SubElement(prog_el, "category", {"lang": "en"}).text = "Sports"
        if event.get("league") and event["league"].lower() != "sports":
            ET.SubElement(prog_el, "category", {"lang": "en"}).text = event["league"]

        if event.get("image"):
            ET.SubElement(prog_el, "icon", {"src": event["image"]})

        if start_dt:
            ET.SubElement(prog_el, "episode-num", {"system": "xmltv_ns"}).text = (
                f"{start_dt.year - 1}.{start_dt.month - 1}{start_dt.day - 1:02d}."
            )
            ET.SubElement(prog_el, "date").text = start_dt.strftime("%Y%m%d")

        ET.SubElement(prog_el, "live")

    tree = ET.ElementTree(tv)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass

    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)
