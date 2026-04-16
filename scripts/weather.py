#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import termios
import textwrap
import time
import tty
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from wcwidth import wcswidth
except Exception:
    wcswidth = None

# ==============================================================================
# PATHS
# ==============================================================================

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "waybar-weather"
CACHE_FILE = CACHE_DIR / "data.json"
LIVECHECK_FILE = CACHE_DIR / "livecheck.json"
LOCATION_FILE = SCRIPT_DIR / "weather-location.json"

# ==============================================================================
# USER CONFIG
# ==============================================================================

LOCATION_MODE = "manual_coords"   # manual_coords | manual_city | auto_ip | auto
MANUAL_LAT = 43.3510
MANUAL_LON = 12.5770
MANUAL_LABEL = "Gubbio"
CITY_NAME = "Gubbio"
CITY_COUNTRY_CODE = "IT"

TIMEZONE = "auto"
TEMP_UNIT = "celsius"
WIND_UNIT = "kmh"
ACTIVE_TEMP_UNIT = TEMP_UNIT
ACTIVE_WIND_UNIT = WIND_UNIT
ACTIVE_TIME_FORMAT = "24h"
DISPLAY_UNITS = "metric"

DEFAULT_CACHE_TTL_SECONDS = 600
DEFAULT_LIVECHECK_TTL_SECONDS = 3600
FORECAST_DAYS = 7
HOURLY_HOURS = 12
DEFAULT_DRIFT_THRESHOLD_KM = 200.0
DEFAULT_IP_DRIFT_THRESHOLD_KM = 300.0
DEFAULT_COMFORT_COLOR = "#7ee787"
DEFAULT_DANGER_COLOR = "#ff6b6b"
DEFAULT_TUI_WIDTH = 88
MIN_TUI_WIDTH = 48
MAX_TUI_WIDTH = 120
WARNING_SYMBOL = "󰀪"
UNKNOWN_SYMBOL = "?"
HOURS_COLUMNS_HELP = "time, icon, temp, feels, rain_prob, rain_mm, uv, aqi, wind, humidity, comfort, desc"

# ==============================================================================
# ICON SETS
# ==============================================================================

ICON_MAP = {
    "emoji": {
        "clear_day": "☀",
        "clear_night": "🌙",
        "partly_day": "⛅",
        "partly_night": "☁",
        "cloudy": "☁",
        "fog": "🌫",
        "drizzle": "🌦",
        "rain": "🌧",
        "freezing": "🌧",
        "snow": "❄",
        "storm": "⛈",
        "unknown": "?",
        "temp": "🌡",
        "feels": "🤔",
        "humidity": "💧",
        "wind": "🌬",
        "pressure": "📊",
        "rain_info": "🌧",
        "aqi": "🫧",
        "uv": "🔆",
        "comfort": "🙂",
        "sunrise": "🌅",
        "sunset": "🌇",
        "alert": "⚠",
    },
    "ascii": {
        "clear_day": "*",
        "clear_night": "o",
        "partly_day": "~",
        "partly_night": "~",
        "cloudy": "=",
        "fog": "-",
        "drizzle": ",",
        "rain": "|",
        "freezing": "!",
        "snow": "#",
        "storm": "^",
        "unknown": "?",
        "temp": "T",
        "feels": "F",
        "humidity": "H",
        "wind": "W",
        "pressure": "P",
        "rain_info": "R",
        "aqi": "A",
        "uv": "U",
        "comfort": "C",
        "sunrise": "^",
        "sunset": "v",
        "alert": "!",
    },
    "nerd": {
        "clear_day": "󰖙",
        "clear_night": "󰖔",
        "partly_day": "󰖕",
        "partly_night": "󰼱",
        "cloudy": "󰖐",
        "fog": "󰖑",
        "drizzle": "󰼳",
        "rain": "󰖗",
        "freezing": "󰙿",
        "snow": "󰖘",
        "storm": "󰙾",
        "unknown": "󰨹",
        "temp": "󰔏",
        "feels": "󰸃",
        "humidity": "󰖎",
        "wind": "󰖐",
        "pressure": "󰘬",
        "rain_info": "󰖗",
        "aqi": "🜁",
        "uv": "☀",
        "comfort": "󰄬",
        "sunrise": "󰖜",
        "sunset": "󰖛",
        "alert": "󰀦",
    },
}

WMO_GROUP = {
    0: "clear", 1: "clear", 2: "partly", 3: "cloudy", 45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "freezing", 57: "freezing",
    61: "rain", 63: "rain", 65: "rain", 66: "freezing", 67: "freezing",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 80: "rain", 81: "rain",
    82: "storm", 85: "snow", 86: "snow", 95: "storm", 96: "storm", 99: "storm",
}
WMO_DESC = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog",
    48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle", 61: "Slight rain",
    63: "Moderate rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
}
WIND_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class Location:
    lat: float
    lon: float
    label: str
    source: str = "unknown"

# ==============================================================================
# LOW-LEVEL HELPERS
# ==============================================================================


def fetch_json(url: str, timeout: int = 12) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "waybar-weather/3.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dirs()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def visible_len(s: str) -> int:
    plain = strip_ansi(s)
    if wcswidth is not None:
        n = wcswidth(plain)
        return n if n >= 0 else len(plain)
    total = 0
    for ch in plain:
        total += 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
    return total


def char_width(ch: str) -> int:
    if wcswidth is not None:
        n = wcswidth(ch)
        return max(0, n)
    return 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1


def clip_visible(s: str, width: int) -> str:
    if width <= 0:
        return ""
    out: List[str] = []
    visible = 0
    i = 0
    while i < len(s):
        if s[i] == "\033":
            m = ANSI_RE.match(s, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
        ch = s[i]
        w = char_width(ch)
        if visible + w > width:
            break
        out.append(ch)
        visible += w
        i += 1
    if visible < width:
        out.append(" " * (width - visible))
    return "".join(out)


def fit_cell(s: str, width: int) -> str:
    return clip_visible(s, width)


def deg_to_compass(deg: float) -> str:
    return WIND_DIRS[round(deg / 45.0) % 8]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def term_size(default_cols: int = 100, default_rows: int = 24) -> Tuple[int, int]:
    try:
        size = shutil.get_terminal_size((default_cols, default_rows))
        return size.columns, size.lines
    except Exception:
        return default_cols, default_rows


def hr(char: str = "─", width: int = 80) -> str:
    return char * max(0, width)


def format_ampm(dt: datetime) -> str:
    return dt.strftime("%I:%M").lstrip("0") + (" a.m." if dt.hour < 12 else " p.m.")


def dt_hour_label(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        if ACTIVE_TIME_FORMAT == "12h":
            return format_ampm(dt)
        return dt.strftime("%H:%M")
    except Exception:
        return ts[-5:]


def dt_alert_label(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return f"{dt.strftime('%a %d %b')} {fmt_clock(ts)}"
    except Exception:
        return ts


def day_label(date_str: str, idx: int) -> str:
    if idx == 0:
        return "Today"
    if idx == 1:
        return "Tomorrow"
    if idx == 2:
        return "Day after"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
    except Exception:
        return date_str


def metric_to_display_temp(celsius_value: Any) -> float:
    v = safe_float(celsius_value)
    return (v * 9.0 / 5.0) + 32.0 if DISPLAY_UNITS == "imperial" else v


def metric_to_display_wind(kmh_value: Any) -> float:
    v = safe_float(kmh_value)
    return v * 0.621371 if DISPLAY_UNITS == "imperial" else v


def fmt_temp(x: Any) -> str:
    return f"{round(metric_to_display_temp(x))}°"


def fmt_percent(x: Any) -> str:
    return f"{round(safe_float(x))}%"


def fmt_wind(x: Any) -> str:
    return f"{round(metric_to_display_wind(x))} {ACTIVE_WIND_UNIT}"


def fmt_hpa(x: Any) -> str:
    return f"{round(safe_float(x))} hPa"


def fmt_uv(x: Any) -> str:
    v = safe_float(x, default=-1.0)
    return "--" if v < 0 else f"{v:.1f}".rstrip("0").rstrip(".")


def fmt_aqi(x: Any) -> str:
    v = safe_float(x, default=-1.0)
    return "--" if v < 0 else str(round(v))


def fmt_comfort(x: Any) -> str:
    return f"{clamp_int(int(round(safe_float(x))), 0, 100)}/100"


def fmt_clock(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return format_ampm(dt) if ACTIVE_TIME_FORMAT == "12h" else dt.strftime("%H:%M")
    except Exception:
        return ts[-5:] if len(ts) >= 5 else ts


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def current_local_hour_iso() -> str:
    return datetime.now().replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def normalize_hex(hex_color: str) -> str:
    s = hex_color.strip()
    if not s.startswith("#"):
        s = "#" + s
    if len(s) != 7:
        raise ValueError(f"Invalid hex color: {hex_color}")
    int(s[1:], 16)
    return s.lower()


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    s = normalize_hex(hex_color)
    return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)


def interp_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def weather_icon_and_class(code: int, is_day: bool, icon_mode: str) -> Tuple[str, str, str]:
    group = WMO_GROUP.get(code, "unknown")
    desc = WMO_DESC.get(code, "Unknown")
    icons = ICON_MAP[icon_mode]
    if group == "clear":
        return desc, icons["clear_day"] if is_day else icons["clear_night"], "clear"
    if group == "partly":
        return desc, icons["partly_day"] if is_day else icons["partly_night"], "cloudy"
    if group == "cloudy":
        return desc, icons["cloudy"], "cloudy"
    if group == "fog":
        return desc, icons["fog"], "fog"
    if group == "drizzle":
        return desc, icons["drizzle"], "drizzle"
    if group == "rain":
        return desc, icons["rain"], "rain"
    if group == "freezing":
        return desc, icons["freezing"], "freezing"
    if group == "snow":
        return desc, icons["snow"], "snow"
    if group == "storm":
        return desc, icons["storm"], "storm"
    return desc, icons["unknown"], "unknown"

# ==============================================================================
# CACHE / THEME
# ==============================================================================


def current_saved_location_key() -> Optional[str]:
    saved = load_saved_location()
    if saved is None:
        return None
    return f"{safe_float(saved.get('lat')):.4f},{safe_float(saved.get('lon')):.4f}:{str(saved.get('label', ''))}"


def payload_location_key(payload: Dict[str, Any]) -> Optional[str]:
    try:
        loc = payload["location"]
        return f"{safe_float(loc.get('lat')):.4f},{safe_float(loc.get('lon')):.4f}:{str(loc.get('label', ''))}"
    except Exception:
        return None


def load_cache(ttl_seconds: int) -> Optional[Dict[str, Any]]:
    try:
        if not CACHE_FILE.exists():
            return None
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age > ttl_seconds:
            return None
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if current_saved_location_key() and payload_location_key(payload):
            if current_saved_location_key() != payload_location_key(payload):
                return None
        return payload
    except Exception:
        return None


def save_cache(data: Dict[str, Any]) -> None:
    write_json(CACHE_FILE, data)


def invalidate_cache() -> None:
    for path in (CACHE_FILE, LIVECHECK_FILE):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


class Theme:
    def __init__(self, enabled: bool = False, comfort_hex: str = DEFAULT_COMFORT_COLOR, danger_hex: str = DEFAULT_DANGER_COLOR):
        self.enabled = enabled and sys.stdout.isatty()
        self.comfort_rgb = hex_to_rgb(comfort_hex)
        self.danger_rgb = hex_to_rgb(danger_hex)

    def c(self, s: str, code: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def truecolor(self, s: str, rgb: Tuple[int, int, int], bold: bool = False) -> str:
        if not self.enabled:
            return s
        prefix = "1;" if bold else ""
        return f"\033[{prefix}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{s}\033[0m"

    def gradient(self, s: str, t: float, bold: bool = False) -> str:
        return self.truecolor(s, interp_color(self.comfort_rgb, self.danger_rgb, t), bold=bold)

    def title(self, s: str) -> str:
        return self.c(s, "1")

    def line(self, s: str) -> str:
        return self.c(s, "2")

    def dim(self, s: str) -> str:
        return self.c(s, "2")

    def section_main(self, s: str) -> str:
        return self.c(s, "1")

    def section_side(self, s: str) -> str:
        return self.c(s, "2")

    def ok(self, s: str) -> str:
        return self.truecolor(s, self.comfort_rgb, bold=True)

    def warn(self, s: str) -> str:
        return self.truecolor(s, self.danger_rgb, bold=True)

    def blue(self, s: str) -> str:
        return self.truecolor(s, (45, 130, 200))

    def bold(self, s: str) -> str:
        return self.c(s, "1")

    def bold_if_enabled(self, s: str) -> str:
        return self.bold(s) if self.enabled else s

    def value_temp(self, x: Any) -> str:
        v = safe_float(x)
        t = 0.0 if 17 <= v <= 25 else min(1.0, abs(v - (17 if v < 17 else 25)) / (20.0 if v < 17 else 12.0))
        return self.gradient(fmt_temp(v), t)

    def value_apparent_temp(self, x: Any) -> str:
        v = safe_float(x)
        t = 0.0 if 17 <= v <= 25 else min(1.0, abs(v - (17 if v < 17 else 25)) / (20.0 if v < 17 else 12.0))
        return self.gradient(fmt_temp(v), t)

    def value_humidity(self, x: Any) -> str:
        v = safe_float(x)
        if 40 <= v <= 60:
            t = 0.0
        elif v < 40:
            t = min(1.0, (40 - v) / 40.0)
        else:
            t = min(1.0, (v - 60) / 40.0)
        return self.gradient(fmt_percent(v), t)

    def value_rain_prob(self, x: Any) -> str:
        return self.gradient(fmt_percent(x), min(1.0, safe_float(x) / 100.0))

    def value_wind(self, x: Any) -> str:
        return self.gradient(fmt_wind(x), min(1.0, max(0.0, (safe_float(x) - 8.0) / 32.0)))

    def value_pressure(self, x: Any) -> str:
        return self.blue(fmt_hpa(x))

    def value_rain_mm(self, x: Any) -> str:
        v = safe_float(x)
        return self.gradient(f"{v:.1f} mm", min(1.0, v / 8.0))

    def value_aqi(self, x: Any) -> str:
        v = safe_float(x, default=-1.0)
        if v < 0:
            return "--"
        return self.gradient(fmt_aqi(v), min(1.0, v / 150.0))

    def value_uv(self, x: Any) -> str:
        v = safe_float(x, default=-1.0)
        if v < 0:
            return "--"
        return self.gradient(fmt_uv(v), min(1.0, v / 11.0))

    def value_comfort(self, x: Any) -> str:
        v = clamp_int(int(round(safe_float(x))), 0, 100)
        return self.gradient(fmt_comfort(v), 1.0 - (v / 100.0))

# ==============================================================================
# LOCATION
# ==============================================================================


def load_saved_location() -> Optional[Dict[str, Any]]:
    return read_json(LOCATION_FILE)


def save_location_file(location: Location) -> None:
    write_json(LOCATION_FILE, {
        "lat": location.lat,
        "lon": location.lon,
        "label": location.label,
        "source": location.source,
        "saved_at": time.time(),
    })
    invalidate_cache()


def location_from_file(data: Dict[str, Any]) -> Location:
    return Location(safe_float(data["lat"]), safe_float(data["lon"]), str(data.get("label", "Saved location")), str(data.get("source", "saved")))


def resolve_manual_coords() -> Location:
    return Location(MANUAL_LAT, MANUAL_LON, MANUAL_LABEL, "manual_coords")


def resolve_manual_city(city_name: str, country_code: str = "") -> Location:
    query = {"name": city_name, "count": 1, "language": "en", "format": "json"}
    if country_code:
        query["countryCode"] = country_code
    data = fetch_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(query))
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"Could not geocode city: {city_name}")
    r = results[0]
    label = ", ".join([x for x in [r.get("name"), r.get("country")] if x])
    return Location(safe_float(r["latitude"]), safe_float(r["longitude"]), label or city_name, "geocode")


def resolve_auto_ip() -> Optional[Location]:
    providers = [
        ("https://ipwho.is/", lambda d: (bool(d.get("success", True)), safe_float(d.get("latitude")),
         safe_float(d.get("longitude")), ", ".join([x for x in [d.get("city"), d.get("country")] if x]), "ipwhois")),
        ("http://ip-api.com/json/", lambda d: (d.get("status") == "success", safe_float(d.get("lat")),
         safe_float(d.get("lon")), ", ".join([x for x in [d.get("city"), d.get("country")] if x]), "ip-api")),
    ]
    for url, parser in providers:
        try:
            data = fetch_json(url, timeout=6)
            ok, lat, lon, label, source = parser(data)
            if ok and not (lat == 0.0 and lon == 0.0):
                return Location(lat, lon, label or "Unknown city", source)
        except Exception:
            continue
    return None


def resolve_geoclue(timeout_seconds: int = 2) -> Optional[Location]:
    try:
        out = subprocess.check_output([
            "gdbus", "call", "--system", "--timeout", str(timeout_seconds), "--dest", "org.freedesktop.GeoClue2",
            "--object-path", "/org/freedesktop/GeoClue2/Manager", "--method", "org.freedesktop.GeoClue2.Manager.GetClient",
        ], stderr=subprocess.DEVNULL, text=True, timeout=timeout_seconds + 1).strip()
        client_path = out.strip("()', ")
        if not client_path.startswith("/"):
            return None
        subprocess.run([
            "gdbus", "call", "--system", "--timeout", str(timeout_seconds), "--dest", "org.freedesktop.GeoClue2",
            "--object-path", client_path, "--method", "org.freedesktop.DBus.Properties.Set",
            "org.freedesktop.GeoClue2.Client", "DesktopId", "<'weather-waybar'>",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds + 1, text=True)
        subprocess.run([
            "gdbus", "call", "--system", "--timeout", str(timeout_seconds), "--dest", "org.freedesktop.GeoClue2",
            "--object-path", client_path, "--method", "org.freedesktop.DBus.Properties.Set",
            "org.freedesktop.GeoClue2.Client", "RequestedAccuracyLevel", "<uint32 4>",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds + 1, text=True)
        subprocess.run([
            "gdbus", "call", "--system", "--timeout", str(timeout_seconds), "--dest", "org.freedesktop.GeoClue2",
            "--object-path", client_path, "--method", "org.freedesktop.GeoClue2.Client.Start",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds + 1, text=True)
        loc_out = subprocess.check_output([
            "gdbus", "get-property", "--system", "--dest", "org.freedesktop.GeoClue2", "--object-path", client_path,
            "--interface", "org.freedesktop.GeoClue2.Client", "Location",
        ], stderr=subprocess.DEVNULL, text=True, timeout=timeout_seconds + 1).strip()
        parts = loc_out.split("'")
        loc_path = parts[1] if len(parts) >= 2 else ""
        if not loc_path.startswith("/"):
            return None
        lat_raw = subprocess.check_output([
            "gdbus", "get-property", "--system", "--dest", "org.freedesktop.GeoClue2", "--object-path", loc_path,
            "--interface", "org.freedesktop.GeoClue2.Location", "Latitude",
        ], stderr=subprocess.DEVNULL, text=True, timeout=timeout_seconds + 1).strip()
        lon_raw = subprocess.check_output([
            "gdbus", "get-property", "--system", "--dest", "org.freedesktop.GeoClue2", "--object-path", loc_path,
            "--interface", "org.freedesktop.GeoClue2.Location", "Longitude",
        ], stderr=subprocess.DEVNULL, text=True, timeout=timeout_seconds + 1).strip()
        return Location(float(lat_raw), float(lon_raw), "GeoClue location", "geoclue")
    except Exception:
        return None


def resolve_location() -> Location:
    saved = load_saved_location()
    if saved is not None:
        return location_from_file(saved)
    if LOCATION_MODE == "manual_coords":
        return resolve_manual_coords()
    if LOCATION_MODE == "manual_city":
        return resolve_manual_city(CITY_NAME, CITY_COUNTRY_CODE)
    if LOCATION_MODE == "auto_ip":
        return resolve_auto_ip() or resolve_manual_coords()
    if LOCATION_MODE == "auto":
        return resolve_geoclue() or resolve_auto_ip() or resolve_manual_coords()
    return resolve_manual_coords()

# ==============================================================================
# FETCH / LIVECHECK
# ==============================================================================


def build_weather_url(lat: float, lon: float) -> str:
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "relative_humidity_2m", "weather_code",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "surface_pressure",
            "precipitation", "is_day",
        ]),
        "hourly": ",".join([
            "temperature_2m", "weather_code", "precipitation_probability", "precipitation",
            "apparent_temperature", "relative_humidity_2m", "surface_pressure", "wind_speed_10m",
            "wind_direction_10m", "wind_gusts_10m", "uv_index",
        ]),
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
            "apparent_temperature_min", "sunrise", "sunset", "precipitation_sum",
            "precipitation_probability_max", "wind_speed_10m_max", "wind_direction_10m_dominant",
            "wind_gusts_10m_max", "uv_index_max",
        ]),
        "forecast_days": str(FORECAST_DAYS),
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "timezone": TIMEZONE,
    }
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)


def build_air_quality_url(lat: float, lon: float) -> str:
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "hourly": "european_aqi",
        "forecast_days": str(FORECAST_DAYS),
        "timezone": TIMEZONE,
    }
    return "https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode(params)


def fetch_weather(force_refresh: bool, ttl_seconds: int) -> Dict[str, Any]:
    if not force_refresh:
        cached = load_cache(ttl_seconds)
        if cached is not None:
            return cached
    location = resolve_location()
    try:
        raw = fetch_json(build_weather_url(location.lat, location.lon))
        air = fetch_json(build_air_quality_url(location.lat, location.lon))
    except urllib.error.URLError:
        stale = read_json(CACHE_FILE)
        if stale is not None:
            return stale
        raise
    payload = {"location": {"lat": location.lat, "lon": location.lon, "label": location.label,
                            "source": location.source}, "raw": raw, "air": air, "fetched_at": time.time()}
    save_cache(payload)
    return payload


def load_livecheck(ttl_seconds: int) -> Optional[Dict[str, Any]]:
    try:
        if not LIVECHECK_FILE.exists():
            return None
        if time.time() - LIVECHECK_FILE.stat().st_mtime > ttl_seconds:
            return None
        return json.loads(LIVECHECK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_livecheck(data: Dict[str, Any]) -> None:
    write_json(LIVECHECK_FILE, data)


def livecheck_cache_key(reference_location: Location) -> str:
    return f"{reference_location.lat:.4f},{reference_location.lon:.4f}:{reference_location.label}"


def compute_livecheck(reference_location: Location, force: bool, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    if not force:
        cached = load_livecheck(ttl_seconds)
        if cached is not None and cached.get("reference_key") == livecheck_cache_key(reference_location):
            return cached
    geoclue_loc = resolve_geoclue()
    ip_loc = resolve_auto_ip()
    guess = geoclue_loc if geoclue_loc is not None else ip_loc
    if guess is None:
        data = {"status": "no_guess", "reference_label": reference_location.label,
                "reference_key": livecheck_cache_key(reference_location), "checked_at": time.time()}
        save_livecheck(data)
        return data
    dist = haversine_km(reference_location.lat, reference_location.lon, guess.lat, guess.lon)
    threshold = DEFAULT_DRIFT_THRESHOLD_KM if guess.source == "geoclue" else DEFAULT_IP_DRIFT_THRESHOLD_KM
    data = {
        "status": "ok",
        "reference_label": reference_location.label,
        "reference_key": livecheck_cache_key(reference_location),
        "guess": {"label": guess.label, "lat": guess.lat, "lon": guess.lon, "source": guess.source},
        "distance_km": dist,
        "threshold_km": threshold,
        "warning": dist >= threshold,
        "checked_at": time.time(),
    }
    save_livecheck(data)
    return data


def livecheck_prefix(livecheck: Optional[Dict[str, Any]]) -> str:
    if not livecheck:
        return ""
    if livecheck.get("status") == "ok" and livecheck.get("warning"):
        return f"{WARNING_SYMBOL} "
    if livecheck.get("status") == "no_guess":
        return f"{UNKNOWN_SYMBOL} "
    return ""


def livecheck_tooltip_lines(livecheck: Optional[Dict[str, Any]]) -> List[str]:
    if not livecheck or livecheck.get("status") != "ok" or not livecheck.get("warning"):
        return []
    ref_label = livecheck.get("reference_label", "Configured location")
    guess = livecheck.get("guess", {})
    return [
        "",
        f"{WARNING_SYMBOL} Location mismatch",
        f"Stored: {ref_label}",
        f"Detected: {guess.get('label', 'Unknown')} ({guess.get('source', 'unknown')})",
        f"Distance: {safe_float(livecheck.get(
            'distance_km')):.1f} km / threshold {safe_float(livecheck.get('threshold_km')):.1f} km",  # pylint: disable=E203
    ]

# ==============================================================================
# MODEL / ALERTS
# ==============================================================================


def choose_hourly_start_index(hourly_times: List[str], fallback_hours: int) -> int:
    if not hourly_times:
        return 0
    now_hour = current_local_hour_iso()
    for i, ts in enumerate(hourly_times):
        if ts >= now_hour:
            return i
    return max(0, len(hourly_times) - fallback_hours)


def score_band(value: float, best_low: float, best_high: float, span: float) -> float:
    if best_low <= value <= best_high:
        return 1.0
    if value < best_low:
        return max(0.0, 1.0 - (best_low - value) / span)
    return max(0.0, 1.0 - (value - best_high) / span)


def comfort_score(apparent_temp: Optional[float], humidity: Optional[float], wind_speed: Optional[float], rain_prob: Optional[float], rain_amount: Optional[float], aqi: Optional[float], uv: Optional[float]) -> int:
    weighted_sum = 0.0
    total_weight = 0.0

    def add(score: float, weight: float) -> None:
        nonlocal weighted_sum, total_weight
        weighted_sum += max(0.0, min(1.0, score)) * weight
        total_weight += weight
    if apparent_temp is not None:
        add(score_band(safe_float(apparent_temp), 18.0, 24.0, 16.0), 1.3)
    if humidity is not None:
        add(score_band(safe_float(humidity), 35.0, 60.0, 35.0), 0.8)
    if wind_speed is not None:
        wind = safe_float(wind_speed)
        add(1.0 if wind <= 22.0 else max(0.0, 1.0 - (wind - 22.0) / 35.0), 0.7)
    if rain_prob is not None:
        add(max(0.0, 1.0 - safe_float(rain_prob) / 100.0), 0.8)
    if rain_amount is not None:
        add(max(0.0, 1.0 - safe_float(rain_amount) / 8.0), 0.6)
    if aqi is not None:
        add(max(0.0, 1.0 - safe_float(aqi) / 120.0), 1.0)
    if uv is not None:
        uv_val = safe_float(uv)
        add(1.0 if uv_val <= 3 else 0.85 if uv_val <= 6 else 0.65 if uv_val <= 8 else 0.4 if uv_val <= 10 else 0.2, 0.8)
    if total_weight <= 0:
        return 50
    return clamp_int(round((weighted_sum / total_weight) * 100), 0, 100)


def alert_level_name(level: str) -> str:
    names = {
        "moderate": "moderate risk",
        "high": "high risk",
        "danger": "dangerous risk",
    }
    return names[level]


def aqi_alert_level(aqi: Optional[float]) -> Optional[str]:
    v = safe_float(aqi, default=-1.0)
    if v < 0:
        return None
    if v >= 200:
        return "danger"
    if v >= 100:
        return "high"
    if v >= 67:
        return "moderate"
    return None


def uv_alert_level(uv: Optional[float]) -> Optional[str]:
    v = safe_float(uv, default=-1.0)
    if v < 0:
        return None
    if v >= 8:
        return "danger"
    if v >= 7:
        return "high"
    if v >= 5:
        return "moderate"
    return None


def rain_alert_level(rain_prob: Optional[float], rain_amount: Optional[float]) -> Optional[str]:
    p = safe_float(rain_prob, default=0.0)
    mm = safe_float(rain_amount, default=0.0)
    if p >= 95 or mm >= 20.0:
        return "danger"
    if p >= 80 or mm >= 15.0:
        return "high"
    if p >= 60 or mm >= 6.0:
        return "moderate"
    return None


def temp_alert_level(temp: Optional[float]) -> Optional[str]:
    v = safe_float(temp, default=999.0)
    if v == 999.0:
        return None
    if v >= 35 or v <= -5:
        return "danger"
    if v >= 30 or v <= 2:
        return "high"
    if v >= 27 or v <= 7:
        return "moderate"
    return None


def is_storm_code(code: Optional[int]) -> bool:
    c = safe_int(code, default=-1)
    return c in {82, 95, 96, 99}


def find_precipitation_events(hourly_rows: List[Dict[str, Any]], min_event_mm: float = 0.2) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    current_event: Optional[Dict[str, Any]] = None

    def finalize(event: Optional[Dict[str, Any]]) -> None:
        if not event:
            return
        event["duration_hours"] = len(event["hours"])
        event["start_label"] = event["hours"][0]["label"]
        event["end_label"] = event["hours"][-1]["label"]
        peak_hour = max(event["hours"], key=lambda h: safe_float(h.get("rain_mm")))
        event["peak_label"] = peak_hour["label"]
        event["peak_mm"] = safe_float(peak_hour.get("rain_mm"))
        event["total_mm"] = sum(safe_float(h.get("rain_mm")) for h in event["hours"])
        event["storm"] = any(is_storm_code(h.get("weather_code")) for h in event["hours"])
        events.append(event)

    for hour in hourly_rows:
        mm = safe_float(hour.get("rain_mm"))
        has_precip = mm >= min_event_mm or is_storm_code(hour.get("weather_code"))
        if has_precip:
            if current_event is None:
                current_event = {"hours": []}
            current_event["hours"].append(hour)
        else:
            finalize(current_event)
            current_event = None
    finalize(current_event)
    return events


def classify_precipitation_event(event: Dict[str, Any]) -> Dict[str, bool]:
    peak_mm = safe_float(event.get("peak_mm"))
    total_mm = safe_float(event.get("total_mm"))
    duration = safe_int(event.get("duration_hours"))
    storm = bool(event.get("storm"))

    short_intense = (
        storm
        or peak_mm >= 10.0
        or (duration <= 2 and total_mm >= 8.0)
    )
    extreme = (
        peak_mm >= 15.0
        or total_mm >= 25.0
        or (storm and peak_mm >= 8.0)
    )
    return {
        "short_intense": short_intense,
        "extreme": extreme,
    }


def precipitation_event_text(event: Dict[str, Any], prefix: str) -> str:
    start_ts = str(event.get("hours", [{}])[0].get("time", ""))
    end_ts = str(event.get("hours", [{}])[-1].get("time", ""))
    same_day = bool(start_ts) and bool(end_ts) and start_ts[:10] == end_ts[:10]
    if same_day:
        interval = f"{dt_alert_label(start_ts)}–{fmt_clock(end_ts)}"
    else:
        interval = f"{dt_alert_label(start_ts)}–{dt_alert_label(end_ts)}"
    return (
        f"{prefix}: {interval}, "
        f"peak around {dt_alert_label(str(max(event.get('hours', [{}]), key=lambda h: safe_float(
            h.get('rain_mm'))).get('time', event.get('peak_label', ''))))} "
        f"at {safe_float(event.get('peak_mm')):.1f} mm/h, "
        f"{safe_float(event.get('total_mm')):.1f} mm in the interval."
    )


def aggregate_hourly_by_day(hourly: Dict[str, Any], air_hourly: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    air_map = {ts: air_hourly["european_aqi"][i]
               for i, ts in enumerate(air_hourly.get("time", []))} if air_hourly else {}
    gusts = hourly.get("wind_gusts_10m", [0] * len(hourly.get("time", [])))
    uvs = hourly.get("uv_index", [None] * len(hourly.get("time", [])))
    grouped: Dict[str, Dict[str, List[float]]] = {}
    for i, ts in enumerate(hourly["time"]):
        day = ts[:10]
        grouped.setdefault(day, {"humidity": [], "pressure": [], "wind_speed": [], "wind_gust": [],
                           "apparent_temperature": [], "rain_probability": [], "rain_amount": [], "uv": [], "aqi": []})
        grouped[day]["humidity"].append(safe_float(hourly["relative_humidity_2m"][i]))
        grouped[day]["pressure"].append(safe_float(hourly["surface_pressure"][i]))
        grouped[day]["wind_speed"].append(safe_float(hourly["wind_speed_10m"][i]))
        grouped[day]["wind_gust"].append(safe_float(gusts[i]))
        grouped[day]["apparent_temperature"].append(safe_float(hourly["apparent_temperature"][i]))
        grouped[day]["rain_probability"].append(safe_float(hourly["precipitation_probability"][i]))
        grouped[day]["rain_amount"].append(safe_float(hourly["precipitation"][i]))
        if uvs[i] is not None:
            grouped[day]["uv"].append(safe_float(uvs[i]))
        if air_map.get(ts) is not None:
            grouped[day]["aqi"].append(safe_float(air_map[ts]))
    out: Dict[str, Dict[str, Any]] = {}
    for day, vals in grouped.items():
        out[day] = {
            "humidity_avg": round(sum(vals["humidity"]) / len(vals["humidity"])) if vals["humidity"] else None,
            "pressure_avg": round(sum(vals["pressure"]) / len(vals["pressure"])) if vals["pressure"] else None,
            "wind_avg": round(sum(vals["wind_speed"]) / len(vals["wind_speed"])) if vals["wind_speed"] else None,
            "wind_gust_max": round(max(vals["wind_gust"])) if vals["wind_gust"] else None,
            "feels_avg": round(sum(vals["apparent_temperature"]) / len(vals["apparent_temperature"])) if vals["apparent_temperature"] else None,
            "rain_prob_avg": round(sum(vals["rain_probability"]) / len(vals["rain_probability"])) if vals["rain_probability"] else None,
            "uv_max": round(max(vals["uv"]), 1) if vals["uv"] else None,
            "aqi_max": round(max(vals["aqi"])) if vals["aqi"] else None,
        }
    return out


def build_alerts(model: Dict[str, Any], livecheck: Optional[Dict[str, Any]]) -> List[str]:
    alerts: List[str] = []
    cur = model["current"]
    today = model["daily"][0] if model.get("daily") else {}
    hourly_rows = model.get("hourly", [])

    if livecheck and livecheck.get("status") == "ok" and livecheck.get("warning"):
        guess = livecheck.get("guess", {})
        alerts.append(
            "Location mismatch: stored/configured city is "
            f"'{livecheck.get('reference_label', model['location']['label'])}', predicted/detected city is "
            f"'{guess.get('label', 'Unknown')}', source is '{guess.get('source', 'unknown')}'. "
            f"Distance {safe_float(livecheck.get('distance_km')):.1f} km over threshold "
            f"{safe_float(livecheck.get('threshold_km')):.1f} km. "
            f"Manual fix: {SCRIPT_PATH} --geocode \"CITY NAME\""
        )

    aqi_level = aqi_alert_level(today.get('aqi', cur.get('aqi')))
    if aqi_level:
        aqi_val = today.get('aqi', cur.get('aqi'))
        alerts.append(f"AQI {alert_level_name(aqi_level)} today: European AQI {fmt_aqi(aqi_val)}.")

    uv_level = uv_alert_level(today.get('uv', cur.get('uv')))
    if uv_level:
        uv_val = today.get('uv', cur.get('uv'))
        alerts.append(f"UV {alert_level_name(uv_level)} today: UV index {fmt_uv(uv_val)}.")

    rain_level = rain_alert_level(today.get('rain_prob', cur.get('rain_prob')),
                                  today.get('rain_sum', cur.get('precip')))
    if rain_level:
        alerts.append(
            f"Rain {alert_level_name(rain_level)} today: probability {
                fmt_percent(today.get('rain_prob', cur.get('rain_prob')))}, "
            f"precipitation {safe_float(today.get('rain_sum', cur.get('precip'))):.1f} mm."
        )

    precip_events = find_precipitation_events(hourly_rows)
    extreme_events = [e for e in precip_events if classify_precipitation_event(e)["extreme"]]
    short_events = [e for e in precip_events if classify_precipitation_event(e)["short_intense"]]

    if extreme_events:
        worst_extreme = max(extreme_events, key=lambda e: (safe_float(e.get('peak_mm')), safe_float(e.get('total_mm'))))
        alerts.append(precipitation_event_text(worst_extreme, "Extreme precipitation expected"))

    short_only_events: List[Dict[str, Any]] = []
    for event in short_events:
        if event not in extreme_events:
            short_only_events.append(event)
    if short_only_events:
        strongest_short = max(short_only_events, key=lambda e: (
            safe_float(e.get('peak_mm')), safe_float(e.get('total_mm'))))
        kind = "Short storm / intense rain expected" if strongest_short.get("storm") else "Short intense rain expected"
        alerts.append(precipitation_event_text(strongest_short, kind))
    elif not extreme_events:
        storm_events = [e for e in precip_events if e.get('storm')]
        if storm_events:
            strongest_storm = max(storm_events, key=lambda e: safe_float(e.get('peak_mm')))
            alerts.append(precipitation_event_text(strongest_storm, "Storm signal expected"))

    feel_level = temp_alert_level(cur.get('feels'))
    if feel_level:
        alerts.append(f"Apparent temperature {alert_level_name(feel_level)
                                              } now: feels like {fmt_temp(cur.get('feels'))}.")

    tmax_level = temp_alert_level(today.get('tmax'))
    if tmax_level:
        alerts.append(f"Maximum temperature {alert_level_name(tmax_level)} today: {fmt_temp(today.get('tmax'))}.")

    tmin_level = temp_alert_level(today.get('tmin'))
    if tmin_level:
        alerts.append(f"Minimum temperature {alert_level_name(tmin_level)} today: {fmt_temp(today.get('tmin'))}.")

    gust_peak = max(safe_float(cur.get('wind_gust')), safe_float(today.get('wind_gust_max')))
    if gust_peak >= 75:
        alerts.append(f"Very strong gusts today: peak gusts up to {fmt_wind(gust_peak)}.")
    elif gust_peak >= 62:
        alerts.append(f"Strong gusts today: peak gusts up to {fmt_wind(gust_peak)}.")

    return alerts


def extract_model(payload: Dict[str, Any], icon_mode: str) -> Dict[str, Any]:
    raw = payload["raw"]
    air = payload.get("air", {})
    current = raw["current"]
    hourly = raw["hourly"]
    daily = raw["daily"]
    air_hourly = air.get("hourly", {})
    current_code = safe_int(current["weather_code"])
    current_is_day = bool(safe_int(current.get("is_day"), 1))
    current_desc, current_icon, current_class = weather_icon_and_class(current_code, current_is_day, icon_mode)
    hourly_times = hourly.get("time", [])
    start_idx = choose_hourly_start_index(hourly_times, HOURLY_HOURS)
    current_idx = choose_hourly_start_index(hourly_times, HOURLY_HOURS)
    air_map = {ts: air_hourly["european_aqi"][i]
               for i, ts in enumerate(air_hourly.get("time", []))} if air_hourly else {}
    gusts = hourly.get("wind_gusts_10m", [None] * len(hourly_times))
    uvs = hourly.get("uv_index", [None] * len(hourly_times))
    hourly_rows = []
    for i in range(start_idx, len(hourly_times)):
        desc, icon, _ = weather_icon_and_class(safe_int(hourly["weather_code"][i]), True, icon_mode)
        ts = hourly["time"][i]
        hourly_rows.append({
            "time": ts,
            "label": dt_hour_label(ts),
            "icon": icon,
            "desc": desc,
            "weather_code": safe_int(hourly["weather_code"][i]),
            "temp": hourly["temperature_2m"][i],
            "feels": hourly["apparent_temperature"][i],
            "humidity": hourly["relative_humidity_2m"][i],
            "wind_speed": hourly["wind_speed_10m"][i],
            "wind_dir": deg_to_compass(safe_float(hourly["wind_direction_10m"][i])),
            "rain_prob": hourly["precipitation_probability"][i],
            "rain_mm": hourly["precipitation"][i],
            "aqi": air_map.get(ts),
            "uv": uvs[i],
            "gust": gusts[i],
            "comfort": comfort_score(hourly["apparent_temperature"][i], hourly["relative_humidity_2m"][i], hourly["wind_speed_10m"][i], hourly["precipitation_probability"][i], hourly["precipitation"][i], air_map.get(ts), uvs[i]),
        })
    stats_by_day = aggregate_hourly_by_day(hourly, air_hourly)
    current_ts = hourly_times[current_idx] if hourly_times else ""
    current_aqi = air_map.get(current_ts)
    current_uv = uvs[current_idx] if hourly_times else None
    current_rain_prob = safe_float(hourly["precipitation_probability"][current_idx]) if hourly_times else 0.0
    current_comfort = comfort_score(current["apparent_temperature"], current["relative_humidity_2m"],
                                    current["wind_speed_10m"], current_rain_prob, current["precipitation"], current_aqi, current_uv)
    daily_rows = []
    for i, d in enumerate(daily["time"][:FORECAST_DAYS]):
        desc, icon, _ = weather_icon_and_class(safe_int(daily["weather_code"][i]), True, icon_mode)
        stats = stats_by_day.get(d, {})
        uv_val = stats.get("uv_max") if stats.get("uv_max") is not None else daily.get(
            "uv_index_max", [None] * len(daily["time"]))[i]
        aqi_val = stats.get("aqi_max")
        comfort = comfort_score(stats.get("feels_avg", daily["apparent_temperature_max"][i]), stats.get(
            "humidity_avg"), daily["wind_speed_10m_max"][i], daily["precipitation_probability_max"][i], daily["precipitation_sum"][i], aqi_val, uv_val)
        daily_rows.append({
            "date": d,
            "label": day_label(d, i),
            "icon": icon,
            "desc": desc,
            "tmax": daily["temperature_2m_max"][i],
            "tmin": daily["temperature_2m_min"][i],
            "feels_avg": stats.get("feels_avg"),
            "humidity_avg": stats.get("humidity_avg"),
            "pressure_avg": stats.get("pressure_avg"),
            "rain_prob": daily["precipitation_probability_max"][i],
            "rain_sum": daily["precipitation_sum"][i],
            "wind_max": daily["wind_speed_10m_max"][i],
            "wind_gust_max": daily.get("wind_gusts_10m_max", [None] * len(daily["time"]))[i],
            "wind_dir": deg_to_compass(safe_float(daily["wind_direction_10m_dominant"][i])),
            "sunrise": daily["sunrise"][i],
            "sunset": daily["sunset"][i],
            "aqi": aqi_val,
            "uv": uv_val,
            "comfort": comfort,
        })
    model = {
        "location": payload["location"],
        "fetched_at": payload["fetched_at"],
        "current": {
            "desc": current_desc,
            "icon": current_icon,
            "class": current_class,
            "temp": current["temperature_2m"],
            "feels": current["apparent_temperature"],
            "humidity": current["relative_humidity_2m"],
            "wind_speed": current["wind_speed_10m"],
            "wind_dir": deg_to_compass(safe_float(current["wind_direction_10m"])),
            "wind_gust": current["wind_gusts_10m"],
            "pressure": current["surface_pressure"],
            "precip": current["precipitation"],
            "rain_prob": current_rain_prob,
            "aqi": current_aqi,
            "uv": current_uv,
            "comfort": current_comfort,
            "sunrise": daily_rows[0]["sunrise"] if daily_rows else "",
            "sunset": daily_rows[0]["sunset"] if daily_rows else "",
        },
        "daily": daily_rows,
        "hourly": hourly_rows,
    }
    return model

# ==============================================================================
# WAYBAR / TUI
# ==============================================================================


def build_waybar_json(model: Dict[str, Any], livecheck: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cur = model["current"]
    daily = model["daily"]
    alerts = build_alerts(model, livecheck)
    text = f"{livecheck_prefix(livecheck)}{cur['icon']} {fmt_temp(cur['temp'])}"
    tooltip_lines = [
        f"{cur['desc']}",
        f"Feels {fmt_temp(cur['feels'])}  Hum {fmt_percent(cur['humidity'])}  Wind {
            fmt_wind(cur['wind_speed'])} {cur['wind_dir']}",
        f"AQI {fmt_aqi(cur['aqi'])}  UV {fmt_uv(cur['uv'])}  Comfort {fmt_comfort(cur['comfort'])}",
    ]
    if len(daily) >= 2:
        tooltip_lines.append("")
        tooltip_lines.append(f"Tomorrow: {daily[1]['icon']} {fmt_temp(daily[1]['tmax'])}/{fmt_temp(daily[1]['tmin'])}  Rain {fmt_percent(
            daily[1]['rain_prob'])}  AQI {fmt_aqi(daily[1]['aqi'])}  UV {fmt_uv(daily[1]['uv'])}  Comfort {fmt_comfort(daily[1]['comfort'])}")
    if len(daily) >= 3:
        tooltip_lines.append(f"Day after: {daily[2]['icon']} {fmt_temp(daily[2]['tmax'])}/{fmt_temp(daily[2]['tmin'])}  Rain {fmt_percent(
            daily[2]['rain_prob'])}  AQI {fmt_aqi(daily[2]['aqi'])}  UV {fmt_uv(daily[2]['uv'])}  Comfort {fmt_comfort(daily[2]['comfort'])}")
    if alerts:
        tooltip_lines.append("")
        tooltip_lines.append("Alerts:")
        for a in alerts[:4]:
            tooltip_lines.append(f"• {a}")
    tooltip_lines.extend(livecheck_tooltip_lines(livecheck))
    css_classes = ["weather", cur["class"]]
    if livecheck and livecheck.get("status") == "ok" and livecheck.get("warning"):
        css_classes.append("warning")
    elif livecheck and livecheck.get("status") == "no_guess":
        css_classes.append("unknown-location")
    return {
        "text": text,
        "tooltip": "\n".join(tooltip_lines),
        "class": css_classes,
    }


def normalize_block(lines: List[str], width: int, height: int) -> List[str]:
    out = [fit_cell(line, width) for line in lines[:height]]
    while len(out) < height:
        out.append(" " * width)
    return out


def join_blocks(blocks: List[List[str]], widths: List[int], sep: str = "  ") -> List[str]:
    if not blocks:
        return []
    height = max(len(b) for b in blocks)
    normalized = [normalize_block(block, width, height) for block, width in zip(blocks, widths)]
    return [sep.join(block[i] for block in normalized) for i in range(height)]


def shorten_text(text: str, max_width: int) -> str:
    if visible_len(text) <= max_width:
        return text
    if max_width <= 1:
        return "…"
    plain = strip_ansi(text)
    out = ""
    cur = 0
    for ch in plain:
        w = char_width(ch)
        if cur + w > max_width - 1:
            break
        out += ch
        cur += w
    return out + "…"


def choose_top_layout(total_width: int, daily_count: int, compact: bool) -> Tuple[List[int], int]:
    if (not compact) and daily_count >= 3 and total_width >= 78:
        return [11, 28, 22, 22], 2
    if daily_count >= 2 and total_width >= 58:
        return [11, 23, 16], 1
    return [12, max(22, total_width - 14)], 0


def build_metric_labels(icon_mode: str, theme: Theme) -> List[str]:
    ic = ICON_MAP[icon_mode]
    return [
        theme.section_main(""), theme.dim(""), theme.dim(f"{ic['temp']} Temp"), theme.dim(f"{ic['feels']} Feels"),
        theme.dim(f"{ic['humidity']} Hum"), theme.dim(f"{ic['wind']} Wind"), theme.dim(f"{ic['pressure']} Press"),
        theme.dim(f"{ic['rain_info']} Rain"), theme.dim(f"{ic['aqi']} AQI"), theme.dim(f"{ic['uv']} UV"),
        theme.dim(f"{ic['comfort']} Comfort"), theme.dim(f"{ic['sunrise']} Rise"), theme.dim(f"{ic['sunset']} Set"),
    ]


def build_now_values(cur: Dict[str, Any], theme: Theme, desc_width: int = 18) -> List[str]:
    return [
        theme.section_main("NOW"),
        theme.bold_if_enabled(f"{cur['icon']}  {shorten_text(cur['desc'], desc_width)}"),
        theme.bold_if_enabled(theme.value_temp(cur['temp'])),
        theme.bold_if_enabled(theme.value_apparent_temp(cur['feels'])),
        theme.bold_if_enabled(theme.value_humidity(cur['humidity'])),
        theme.bold_if_enabled(theme.value_wind(cur['wind_speed']) + f" {cur['wind_dir']}"),
        theme.bold_if_enabled(theme.value_pressure(cur['pressure'])),
        theme.bold_if_enabled(theme.value_rain_prob(cur['rain_prob']) + "  " + theme.value_rain_mm(cur['precip'])),
        theme.bold_if_enabled(theme.value_aqi(cur['aqi'])),
        theme.bold_if_enabled(theme.value_uv(cur['uv'])),
        theme.bold_if_enabled(theme.value_comfort(cur['comfort'])),
        theme.bold_if_enabled(fmt_clock(cur['sunrise']) if cur['sunrise'] else '--:--'),
        theme.bold_if_enabled(fmt_clock(cur['sunset']) if cur['sunset'] else '--:--'),
    ]


def build_future_values(day: Dict[str, Any], title: str, theme: Theme, desc_width: int = 14) -> List[str]:
    return [
        theme.section_side(title),
        f"{day['icon']}  {shorten_text(day['desc'], desc_width)}",
        theme.value_temp(day['tmax']) + " / " + fmt_temp(day['tmin']),
        theme.value_apparent_temp(day['feels_avg']) if day.get('feels_avg') is not None else '--',
        theme.value_humidity(day['humidity_avg']) if day.get('humidity_avg') is not None else '--',
        theme.value_wind(day['wind_max']) + f" {day['wind_dir']}",
        theme.value_pressure(day['pressure_avg']) if day.get('pressure_avg') is not None else '--',
        theme.value_rain_prob(day['rain_prob']) + "  " + theme.value_rain_mm(day['rain_sum']),
        theme.value_aqi(day['aqi']),
        theme.value_uv(day['uv']),
        theme.value_comfort(day['comfort']),
        fmt_clock(day['sunrise']) if day['sunrise'] else '--:--',
        fmt_clock(day['sunset']) if day['sunset'] else '--:--',
    ]


def make_week_header(width: int, theme: Theme, compact: bool) -> str:
    label_w = 10
    icon_w = 2
    temp_w = 12 if not compact else 10
    rain_prob_w = 6
    rain_mm_w = 8
    aqi_w = 5
    uv_w = 4
    comfort_w = 8
    separator = '  '
    fixed = (
        label_w + icon_w + temp_w + rain_prob_w + rain_mm_w + aqi_w + uv_w + comfort_w
        + len(separator) * 7
    )
    desc_w = max(8, width - fixed)

    parts = [
        fit_cell(theme.section_side("Day"), label_w),
        fit_cell(theme.section_side(""), icon_w),
        fit_cell(theme.section_side("Temp"), temp_w),
        fit_cell(theme.section_side("Rain%"), rain_prob_w),
        fit_cell(theme.section_side("Rain"), rain_mm_w),
        fit_cell(theme.section_side("AQI"), aqi_w),
        fit_cell(theme.section_side("UV"), uv_w),
        fit_cell(theme.section_side("Comfort"), comfort_w),
        fit_cell(theme.section_side("Condition"), desc_w),
    ]
    return fit_cell(separator.join(parts), width)


def make_week_line(day: Dict[str, Any], width: int, theme: Theme, compact: bool) -> str:
    label_w = 10
    icon_w = 2
    temp_w = 12 if not compact else 10
    rain_prob_w = 6
    rain_mm_w = 8
    aqi_w = 5
    uv_w = 4
    comfort_w = 8
    separator = '  '
    fixed = (
        label_w + icon_w + temp_w + rain_prob_w + rain_mm_w + aqi_w + uv_w + comfort_w
        + len(separator) * 7
    )
    desc_w = max(8, width - fixed)

    parts = [
        fit_cell(day['label'], label_w),
        fit_cell(day['icon'], icon_w),
        fit_cell(theme.value_temp(day['tmax']) + ' / ' + theme.value_temp(day['tmin']), temp_w),
        fit_cell(theme.value_rain_prob(day['rain_prob']), rain_prob_w),
        fit_cell(theme.value_rain_mm(day['rain_sum']), rain_mm_w),
        fit_cell(theme.value_aqi(day['aqi']), aqi_w),
        fit_cell(theme.value_uv(day['uv']), uv_w),
        fit_cell(theme.value_comfort(day['comfort']), comfort_w),
        fit_cell(theme.dim(shorten_text(day['desc'], desc_w)), desc_w),
    ]
    return fit_cell(separator.join(parts), width)


HOUR_COLUMN_SPECS = {
    'time': {'title': 'Time', 'width': 10},
    'icon': {'title': '', 'width': 2},
    'temp': {'title': 'Temp', 'width': 5},
    'feels': {'title': 'Feels', 'width': 6},
    'rain_prob': {'title': 'Rain%', 'width': 6},
    'rain_mm': {'title': 'Rain', 'width': 8},
    'uv': {'title': 'UV', 'width': 4},
    'aqi': {'title': 'AQI', 'width': 5},
    'wind': {'title': 'Wind', 'width': 11},
    'humidity': {'title': 'Hum', 'width': 5},
    'comfort': {'title': 'Comfort', 'width': 8},
    'desc': {'title': 'Condition', 'width': 12},
}


def normalize_hours_columns(columns: List[str]) -> List[str]:
    valid = [c for c in columns if c in HOUR_COLUMN_SPECS]
    if 'desc' not in valid:
        valid.append('desc')
    else:
        valid = [c for c in valid if c != 'desc'] + ['desc']
    return valid or ['time', 'icon', 'temp', 'feels', 'rain_prob', 'rain_mm', 'wind', 'humidity', 'comfort', 'desc']


def compute_hour_column_layout(width: int, columns: List[str]) -> List[Tuple[str, int]]:
    columns = normalize_hours_columns(columns)
    separator = '  '
    fixed = sum(HOUR_COLUMN_SPECS[c]['width'] for c in columns if c != 'desc')
    fixed += len(separator) * (len(columns) - 1)
    desc_w = max(10, width - fixed) if 'desc' in columns else 0
    return [(c, desc_w if c == 'desc' else HOUR_COLUMN_SPECS[c]['width']) for c in columns]


def render_hour_column_value(column: str, hour: Dict[str, Any], theme: Theme) -> str:
    if column == 'time':
        return hour['label']
    if column == 'icon':
        return hour['icon']
    if column == 'temp':
        return theme.value_temp(hour['temp'])
    if column == 'feels':
        return theme.value_apparent_temp(hour.get('feels'))
    if column == 'rain_prob':
        return theme.value_rain_prob(hour.get('rain_prob'))
    if column == 'rain_mm':
        return theme.value_rain_mm(hour.get('rain_mm'))
    if column == 'uv':
        return theme.value_uv(hour.get('uv'))
    if column == 'aqi':
        return theme.value_aqi(hour.get('aqi'))
    if column == 'wind':
        return theme.value_wind(hour.get('wind_speed')) + f" {hour.get('wind_dir', '--')}"
    if column == 'humidity':
        return theme.value_humidity(hour.get('humidity'))
    if column == 'comfort':
        return theme.value_comfort(hour.get('comfort'))
    if column == 'desc':
        return theme.dim(hour.get('desc', ''))
    return '--'


def make_hour_header(width: int, theme: Theme, columns: List[str]) -> str:
    separator = '  '
    layout = compute_hour_column_layout(width, columns)
    parts: List[str] = []
    for c, col_w in layout:
        parts.append(fit_cell(theme.section_side(HOUR_COLUMN_SPECS[c]['title']), col_w))
    return fit_cell(separator.join(parts), width)


def make_hour_line(hour: Dict[str, Any], width: int, theme: Theme, compact: bool, columns: List[str]) -> str:
    separator = '  '
    layout = compute_hour_column_layout(width, columns)
    parts: List[str] = []
    for c, col_w in layout:
        value = render_hour_column_value(c, hour, theme)
        if c == 'desc':
            value = theme.dim(shorten_text(strip_ansi(value), col_w))
        parts.append(fit_cell(value, col_w))
    return fit_cell(separator.join(parts), width)


def wrap_tui_text(text: str, width: int) -> List[str]:
    plain = strip_ansi(text)
    wrapped = textwrap.wrap(plain, width=max(16, width), break_long_words=False, break_on_hyphens=False)
    return wrapped or [plain]


def render_tui(model: Dict[str, Any], colored: bool, livecheck: Optional[Dict[str, Any]], icon_mode: str, comfort_color: str, danger_color: str, width: int, compact: bool, days: int, hours: int, show_location_check: bool, hours_columns: Optional[List[str]] = None) -> str:
    theme = Theme(colored, comfort_color, danger_color)
    loc = model['location']['label']
    daily = model['daily']
    hourly = model['hourly'][:max(0, hours)]
    hours_columns = normalize_hours_columns(
        hours_columns or ['time', 'icon', 'temp', 'feels', 'rain_prob', 'rain_mm', 'wind', 'humidity', 'comfort', 'desc'])
    alerts = build_alerts(model, livecheck)
    total_width = clamp_int(width, MIN_TUI_WIDTH, MAX_TUI_WIDTH)
    top_widths, side_count = choose_top_layout(total_width, len(daily), compact)
    blocks: List[List[str]] = [build_metric_labels(icon_mode, theme), build_now_values(
        model['current'], theme, max(10, top_widths[1] - 4))]
    widths = [top_widths[0], top_widths[1]]
    if side_count >= 1 and len(daily) >= 2:
        blocks.append(build_future_values(daily[1], 'TOMORROW', theme, max(8, top_widths[2] - 4)))
        widths.append(top_widths[2])
    if side_count >= 2 and len(daily) >= 3:
        blocks.append(build_future_values(daily[2], 'DAY AFTER', theme, max(8, top_widths[3] - 4)))
        widths.append(top_widths[3])
    lines: List[str] = []
    title_prefix = theme.warn(f"{WARNING_SYMBOL} ") if livecheck and livecheck.get('status') == 'ok' and livecheck.get(
        'warning') else (theme.dim(f"{UNKNOWN_SYMBOL} ") if livecheck and livecheck.get('status') == 'no_guess' else '')
    fetched_dt = datetime.fromtimestamp(model['fetched_at'])
    fetched = fetched_dt.strftime(
        '%Y-%m-%d ') + format_ampm(fetched_dt) if ACTIVE_TIME_FORMAT == '12h' else fetched_dt.strftime('%Y-%m-%d %H:%M')
    header_left = theme.title(f"{title_prefix}Weather — {loc}")
    header_right = theme.dim(f"Updated {fetched}")
    gap = max(2, total_width - visible_len(header_left) - visible_len(header_right))
    if visible_len(header_left) + gap + visible_len(header_right) <= total_width:
        header_line = header_left + (' ' * gap) + header_right
    else:
        header_line = fit_cell(header_left, total_width)
    lines.append(fit_cell(header_line, total_width))
    lines.append(fit_cell(theme.line(hr(width=total_width)), total_width))
    lines.append("")
    lines.extend(fit_cell(line, total_width) for line in join_blocks(blocks, widths, sep='  '))
    week_days = daily[1:1 + max(0, days)]
    if week_days:
        lines.extend([
            "",
            fit_cell(theme.section_side('WEEK'), total_width),
            fit_cell(theme.line(hr(width=total_width)), total_width),
        ])
        lines.append(make_week_header(total_width, theme, compact))
        for d in week_days:
            lines.append(make_week_line(d, total_width, theme, compact))
    if hourly:
        lines.extend(["", fit_cell(theme.section_side(f'NEXT {len(hourly)}H'), total_width), fit_cell(
            theme.line(hr(width=total_width)), total_width)])
        lines.append(make_hour_header(total_width, theme, hours_columns))
        for h in hourly:
            lines.append(make_hour_line(h, total_width, theme, compact, hours_columns))
    lines.extend(["", fit_cell(theme.section_side('ALERTS'), total_width),
                 fit_cell(theme.line(hr(width=total_width)), total_width)])
    if alerts:
        for alert in alerts:
            for wrapped in wrap_tui_text(f"{ICON_MAP[icon_mode]['alert']} {alert}", total_width):
                lines.append(fit_cell(wrapped, total_width))
    else:
        lines.append(fit_cell(theme.ok('General good weather conditions.'), total_width))
#    lines.extend(["", fit_cell(theme.dim('Keys: j/k ↑/↓ PgUp/PgDn g/G r q'), total_width)])
    return "\n".join(lines)

# ==============================================================================
# INTERACTIVE TUI — preserved lifecycle/behavior from baseline
# ==============================================================================


def read_key() -> str:
    ch1 = sys.stdin.read(1)
    if ch1 != "\x1b":
        return ch1
    ch2 = sys.stdin.read(1)
    if ch2 != "[":
        return ch1 + ch2
    ch3 = sys.stdin.read(1)
    if ch3 in "ABCDHF":
        return "\x1b[" + ch3
    if ch3.isdigit():
        seq = "\x1b[" + ch3
        while True:
            ch = sys.stdin.read(1)
            seq += ch
            if ch.isalpha() or ch == "~":
                break
        return seq
    return "\x1b[" + ch3


def render_screen(lines: List[str], offset: int) -> None:
    cols, rows = term_size(100, 24)
    usable_rows = max(3, rows - 1)
    max_offset = max(0, len(lines) - usable_rows)
    offset = max(0, min(offset, max_offset))
    sys.stdout.write("\033[H\033[2J")
    visible = lines[offset:offset + usable_rows]
    for i in range(usable_rows):
        sys.stdout.write(f"\033[{i+1};1H")
        sys.stdout.write(clip_visible(visible[i] if i < len(visible) else "", cols))
    status = f"[q] quit  [j/k ↑/↓] scroll  [PgUp/PgDn] page  [g/G] top/bottom  [r] refresh  {
        offset+1}-{min(offset+usable_rows, len(lines))}/{len(lines)}"
    sys.stdout.write(f"\033[{rows};1H{clip_visible(status, cols)}")
    sys.stdout.flush()


def interactive_tui_loop(args: argparse.Namespace, model: Dict[str, Any], livecheck: Optional[Dict[str, Any]]) -> None:
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        print(render_tui(model, args.colored, livecheck, args.icons, args.comfort_color, args.danger_color,
              args.width, args.compact, args.days, args.hours, args.show_location_check, args.hours_columns))
        return

    def rebuild(force_refresh: bool = False) -> Tuple[List[str], Dict[str, Any], Optional[Dict[str, Any]]]:
        payload = fetch_weather(force_refresh=force_refresh, ttl_seconds=args.ttl)
        current_model = extract_model(payload, icon_mode=args.icons)
        ref_loc = Location(safe_float(payload['location']['lat']), safe_float(payload['location']['lon']), str(
            payload['location']['label']), str(payload['location'].get('source', 'unknown')))
        current_livecheck = compute_livecheck(ref_loc, force=force_refresh, ttl_seconds=args.livecheck_ttl)
        rendered = render_tui(current_model, args.colored, current_livecheck, args.icons, args.comfort_color, args.danger_color,
                              args.width, args.compact, args.days, args.hours, args.show_location_check, args.hours_columns)
        return rendered.splitlines(), current_model, current_livecheck
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    offset = 0
    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?1049h")
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        lines = render_tui(model, args.colored, livecheck, args.icons, args.comfort_color, args.danger_color,
                           args.width, args.compact, args.days, args.hours, args.show_location_check, args.hours_columns).splitlines()
        while True:
            cols, rows = term_size(100, 24)
            usable_rows = max(3, rows - 1)
            max_offset = max(0, len(lines) - usable_rows)
            offset = max(0, min(offset, max_offset))
            render_screen(lines, offset)
            key = read_key()
            if key in ("q", "Q", "\x03", "\x04"):
                break
            elif key in ("j", "\x1b[B"):
                offset = min(max_offset, offset + 1)
            elif key in ("k", "\x1b[A"):
                offset = max(0, offset - 1)
            elif key == "\x1b[6~":
                offset = min(max_offset, offset + usable_rows)
            elif key == "\x1b[5~":
                offset = max(0, offset - usable_rows)
            elif key == "g":
                offset = 0
            elif key == "G":
                offset = max_offset
            elif key in ("r", "R"):
                try:
                    lines, model, livecheck = rebuild(force_refresh=True)
                    offset = 0
                except Exception as exc:
                    lines = [f"Weather error: {exc}", "", "Press q to quit or r to retry."]
                    offset = 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\033[?25h")
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()

# ==============================================================================
# COMMANDS / MAIN
# ==============================================================================


def cmd_geocode(city: str, country_code: str = "") -> int:
    try:
        loc = resolve_manual_city(city, country_code)
    except Exception as exc:
        print(f"Geocode error: {exc}", file=sys.stderr)
        return 1
    print("Geocode result")
    print(f"Name:   {loc.label}")
    print(f"Lat:    {loc.lat}")
    print(f"Lon:    {loc.lon}")
    print(f"Source: {loc.source}")
    print(f"File:   {LOCATION_FILE}")
    if not sys.stdin.isatty():
        print("No interactive TTY available, not saving automatically.", file=sys.stderr)
        return 0
    ans = input(f"\nSave to {LOCATION_FILE}? [y/N]: ").strip().lower()
    if ans in {"y", "yes"}:
        save_location_file(loc)
        print(f"Saved to {LOCATION_FILE}")
    else:
        print("Not saved.")
    return 0


def cmd_ip_locate() -> int:
    loc = resolve_auto_ip()
    if loc is None:
        print("IP geolocation unavailable.", file=sys.stderr)
        return 1
    print("IP location")
    print(f"Name:   {loc.label}")
    print(f"Lat:    {loc.lat}")
    print(f"Lon:    {loc.lon}")
    print(f"Source: {loc.source}")
    return 0


def cmd_geoclue_test() -> int:
    loc = resolve_geoclue()
    if loc is None:
        print("GeoClue unavailable.")
        return 1
    print("GeoClue location")
    print(f"Name:   {loc.label}")
    print(f"Lat:    {loc.lat}")
    print(f"Lon:    {loc.lon}")
    print(f"Source: {loc.source}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weather widget/TUI for Waybar and Omarchy using Open-Meteo forecast and air-quality data.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--tui", action="store_true",
                        help="Render the terminal dashboard instead of Waybar JSON output")
    parser.add_argument("--hold", action="store_true",
                        help="Keep the TUI open in interactive mode with scrolling, refresh and quit keys")
    parser.add_argument("--colored", action="store_true", help="Enable ANSI colors in the TUI")
    parser.add_argument("--icons", choices=["emoji", "nerd", "ascii"],
                        default="nerd", help="Select the icon set for TUI and Waybar output")
    parser.add_argument("--units", choices=["metric", "imperial"], default="metric",
                        help="Choose metric (°C, km/h) or imperial (°F, mph) units")
    parser.add_argument("--h-format", choices=["24h", "12h"], default="24h",
                        help="Choose 24h or 12h AM/PM time formatting in the TUI")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh cached weather and air-quality data")
    parser.add_argument("--ttl", type=int, default=DEFAULT_CACHE_TTL_SECONDS, help="Weather cache TTL in seconds")
    parser.add_argument("--livecheck-ttl", type=int, default=DEFAULT_LIVECHECK_TTL_SECONDS,
                        help="Location live-check cache TTL in seconds")
    parser.add_argument("--geocode", metavar="CITY",
                        help="Geocode a city name and optionally save it as the fixed forecast location")
    parser.add_argument("--country", default="", help="Optional country code used together with --geocode")
    parser.add_argument("--ip-locate", action="store_true", help="Show the current IP-based guessed location and exit")
    parser.add_argument("--geoclue-test", action="store_true", help="Test GeoClue location lookup and exit")
    parser.add_argument("--comfort-color", default=DEFAULT_COMFORT_COLOR,
                        help="Best-comfort hex color for gradients, e.g. #7ee787")
    parser.add_argument("--danger-color", default=DEFAULT_DANGER_COLOR,
                        help="Worst-condition hex color for gradients, e.g. #ff6b6b")
    parser.add_argument("--width", type=int, default=DEFAULT_TUI_WIDTH, help="Target TUI width")
    parser.add_argument("--compact", action="store_true", help="Use a denser layout for narrow terminals")
    parser.add_argument("--days", type=int, default=6, help="Number of forecast days to show in the WEEK section")
    parser.add_argument("--hours", type=int, default=12, help="Number of forecast hours to show in the NEXT H section")
    parser.add_argument(
        "--hours-columns",
        default="time,icon,temp,feels,rain_prob,rain_mm,wind,humidity,comfort,desc",
        help=(
            "Comma-separated columns for the NEXT H table. "
            f"Available columns: {HOURS_COLUMNS_HELP}"
        ),
    )
    parser.add_argument("--show-location-check", action="store_true",
                        help="Show the dedicated location-check block in the TUI")
    parser.add_argument("--hide-location-check", action="store_true",
                        help="Hide the dedicated location-check block in the TUI")
    args = parser.parse_args()
    global ACTIVE_TEMP_UNIT, ACTIVE_WIND_UNIT, ACTIVE_TIME_FORMAT, DISPLAY_UNITS
    DISPLAY_UNITS = args.units
    ACTIVE_TEMP_UNIT = "fahrenheit" if args.units == "imperial" else "celsius"
    ACTIVE_WIND_UNIT = "mph" if args.units == "imperial" else "kmh"
    ACTIVE_TIME_FORMAT = args.h_format
    try:
        args.comfort_color = normalize_hex(args.comfort_color)
        args.danger_color = normalize_hex(args.danger_color)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.width = clamp_int(args.width, MIN_TUI_WIDTH, MAX_TUI_WIDTH)
    args.days = max(0, min(6, args.days))
    args.hours = max(0, min(24, args.hours))
    args.hours_columns = [c.strip().lower() for c in args.hours_columns.split(',') if c.strip()]
    args.show_location_check = bool(args.show_location_check) and not args.hide_location_check
    if args.geocode:
        return cmd_geocode(args.geocode, args.country)
    if args.ip_locate:
        return cmd_ip_locate()
    if args.geoclue_test:
        return cmd_geoclue_test()
    if args.refresh:
        invalidate_cache()
    try:
        payload = fetch_weather(force_refresh=args.refresh, ttl_seconds=args.ttl)
        model = extract_model(payload, icon_mode=args.icons)
        ref_loc = Location(safe_float(payload['location']['lat']), safe_float(payload['location']['lon']), str(
            payload['location']['label']), str(payload['location'].get('source', 'unknown')))
        livecheck = compute_livecheck(ref_loc, force=args.refresh, ttl_seconds=args.livecheck_ttl)
    except Exception as exc:
        if args.tui:
            print(f"Weather error: {exc}")
            return 1
        print(json.dumps({"text": f"{WARNING_SYMBOL} --°", "tooltip": f"Weather error: {exc}",
              "class": ["weather", "error"]}, ensure_ascii=False))
        return 0
    if args.tui:
        if args.hold:
            interactive_tui_loop(args, model, livecheck)
        else:
            print(render_tui(model, args.colored, livecheck, args.icons, args.comfort_color, args.danger_color,
                  args.width, args.compact, args.days, args.hours, args.show_location_check, args.hours_columns))
        return 0
    print(json.dumps(build_waybar_json(model, livecheck), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
