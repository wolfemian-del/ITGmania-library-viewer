"""Tk-independent parsing and formatting helpers for the ITGmania library."""

from __future__ import annotations

import re
import shlex
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path


TECH_FIELDS = ("Crossovers", "HalfCrossovers", "FullCrossovers", "Footswitches",
               "UpFootswitches", "DownFootswitches", "Sideswitches", "Jacks",
               "Brackets", "Doublesteps")
DIFFICULTY_ORDER = ("Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit")
DIFFICULTY_RANK = {difficulty.casefold(): index for index, difficulty in enumerate(DIFFICULTY_ORDER)}
RADAR_FIELDS = ("Stream", "Voltage", "Air", "Freeze", "Chaos", "Notes",
                "TapsAndHolds", "Jumps", "Holds", "Mines", "Hands", "Rolls",
                "Lifts", "Fakes")
TAP_FIELDS = ("W1", "W2", "W3", "W4", "W5", "Miss")
GRADE_NAMES = {
    "Tier01": "★★★★", "Tier02": "★★★", "Tier03": "★★", "Tier04": "★",
    "Tier05": "S+", "Tier06": "S", "Tier07": "S-", "Tier08": "A+",
    "Tier09": "A", "Tier10": "A-", "Tier11": "B+", "Tier12": "B",
    "Tier13": "B-", "Tier14": "C+", "Tier15": "C", "Tier16": "C-", "Tier17": "D",
}
GRADE_OPTIONS = tuple(GRADE_NAMES.values())
# Best grade first (low index). Accept both Tier keys and display labels.
GRADE_RANK = {name.casefold(): index for index, name in enumerate(GRADE_NAMES.values())}
GRADE_RANK.update({tier.casefold(): index for index, tier in enumerate(GRADE_NAMES)})
COURSE_UNSAFE_CHARS = (";", ":", "\r", "\n")

__all__ = [
    "CHART_FILTER_FIELDS",
    "COURSE_UNSAFE_CHARS",
    "DIFFICULTY_ORDER",
    "GRADE_OPTIONS",
    "GRADE_NAMES",
    "RADAR_FIELDS",
    "SEARCH_FIELD_ALIASES",
    "TAP_FIELDS",
    "TECH_FIELDS",
    "aggregate_bpm_distribution",
    "aggregate_difficulty_distribution",
    "aggregate_meter_distribution",
    "bpm_sort_key",
    "build_dialog_query",
    "course_append_bytes",
    "course_song_line",
    "course_song_lines",
    "course_trailing_risk",
    "difficulty_sort_key",
    "distribution_summary_stats",
    "filter_texts_match",
    "filter_token_text",
    "format_bpm_display",
    "format_duration",
    "format_new_course",
    "get_active_chart_filter",
    "get_active_chart_filters",
    "grade_sort_key",
    "looks_like_song_tree",
    "match_chart_query",
    "number",
    "parse_bpms",
    "parse_cache_file",
    "parse_course_text",
    "parse_duration_seconds",
    "parse_numeric_bound",
    "parse_search_query",
    "replace_search_directive",
    "split_dialog_query",
    "split_path",
    "stats_index",
    "tag_map",
    "validate_course_fields",
]


def number(value: str | None, default: float = 0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def format_duration(seconds) -> str:
    total = max(0, int(round(number(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def difficulty_sort_key(value):
    difficulty = str(value or "")
    return DIFFICULTY_RANK.get(difficulty.casefold(), len(DIFFICULTY_ORDER)), difficulty.casefold()


def grade_sort_key(value):
    """Sort grades by ITGmania tier order (S+ before S before S-, etc.)."""
    grade = str(value or "").strip()
    if not grade:
        return len(GRADE_RANK), ""
    return GRADE_RANK.get(grade.casefold(), len(GRADE_RANK)), grade.casefold()


def parse_bpms(value: str | None) -> tuple[float, float] | None:
    """Return (min, max) BPM from a #BPMS tag value, or None if unusable."""
    text = (value or "").strip()
    if not text:
        return None
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            part = part.split("=", 1)[1].strip()
        try:
            values.append(float(part))
        except ValueError:
            continue
    if not values:
        return None
    return min(values), max(values)


def format_bpm_display(displaybpm: str | None, bpm_min, bpm_max) -> str:
    """Format a BPM cell from #DISPLAYBPM and/or parsed #BPMS bounds."""
    raw = (displaybpm or "").strip()
    if raw == "*":
        return "*"
    if raw:
        # Single value or explicit min:max (colon-separated).
        if ":" in raw:
            left, right = (piece.strip() for piece in raw.split(":", 1))
            try:
                lo, hi = float(left), float(right)
            except ValueError:
                pass
            else:
                return _format_bpm_pair(lo, hi)
        else:
            try:
                value = float(raw)
            except ValueError:
                pass
            else:
                return _format_bpm_number(value)
    if bpm_min is None or bpm_max is None or bpm_min == "" or bpm_max == "":
        return ""
    return _format_bpm_pair(float(bpm_min), float(bpm_max))


def _format_bpm_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _format_bpm_pair(lo: float, hi: float) -> str:
    if lo == hi:
        return _format_bpm_number(lo)
    return f"{_format_bpm_number(lo)}–{_format_bpm_number(hi)}"


def bpm_sort_key(row: dict):
    """Sort by max BPM, then min BPM (fast charts with a slow gimmick rank high)."""
    bpm_max = row.get("bpm_max", "")
    bpm_min = row.get("bpm_min", "")
    if bpm_max in (None, "") or bpm_min in (None, ""):
        return (float("inf"), float("inf"))
    return (float(bpm_max), float(bpm_min))


def tag_map(text: str) -> dict[str, str]:
    tags = {}
    # ITGmania MSD tags start with #KEY: and end at an unescaped ;.
    # A backslash escapes the next character (e.g. \; is a literal semicolon, \\ is a literal backslash).
    for m in re.finditer(r"(?m)^#([^:;\r\n]+):((?:\\.|[^;\r\n])*?);", text):
        raw_val = m.group(2).strip()
        decoded_val = raw_val.replace(r"\;", ";").replace(r"\\", "\\")
        tags[m.group(1).upper()] = decoded_val
    return tags


def split_path(value: str) -> str:
    """Normalize an ITGmania song path to its path below the Songs or AdditionalSongs directory.

    Cache entries usually use ``/Songs/Pack/Song/file.sm`` while Stats.xml
    commonly uses ``Songs/Pack/Song`` or ``AdditionalSongs/Pack/Song``. Some installations
    may instead store a filesystem-absolute path, so strip the prefix through the
    first component named Songs or AdditionalSongs wherever it occurs.
    """
    parts = value.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.casefold() in ("songs", "additionalsongs"):
            return "/".join(parts[index + 1:]).strip("/")
    return "/".join(parts).strip("/")


def stats_index(stats_file: Path) -> dict[tuple[str, str, str], dict]:
    root = ET.parse(stats_file).getroot()
    result: dict[tuple[str, str, str], dict] = {}
    song_scores = root.find("SongScores")
    if song_scores is None:
        return result
    for song in song_scores.findall("Song"):
        song_path = split_path(song.get("Dir", ""))
        for steps in song.findall("Steps"):
            key = (song_path.casefold(), steps.get("StepsType", "").casefold(),
                   steps.get("Difficulty", "").casefold())
            score_list = steps.find("HighScoreList")
            if score_list is None:
                continue
            scores = score_list.findall("HighScore")
            best = max(scores, key=lambda score: number(score.findtext("PercentDP")), default=None)
            best_data = {}
            if best is not None:
                best_data = {tag: best.findtext(tag, "") for tag in
                             ("Score", "Grade", "PercentDP", "MaxCombo", "DateTime")}
                taps = best.find("TapNoteScores")
                if taps is not None:
                    best_data.update({"tap_" + name: taps.findtext(name, "") for name in TAP_FIELDS})
                radar = best.find("RadarValues")
                if radar is not None:
                    best_data.update({"score_" + name: radar.findtext(name, "") for name in RADAR_FIELDS})
            entry = result.setdefault(key, {"plays": "0", "last_played": ""})
            plays = score_list.findtext("NumTimesPlayed", "0")
            if number(plays) > number(entry["plays"]):
                entry["plays"] = plays
            last_played = score_list.findtext("LastPlayed", "")
            if last_played > entry["last_played"]:
                entry["last_played"] = last_played
            # Several Stats.xml Song entries can normalize to the same key.
            # Merge them without letting a later, lower record replace the best.
            if best_data and ("PercentDP" not in entry or
                              number(best_data.get("PercentDP")) > number(entry.get("PercentDP"))):
                entry.update(best_data)
    return result


def parse_cache_file(path: Path, scores: dict) -> list[dict]:
    # Cache files are UTF-8 Simfile text; split away the song metadata before chart parsing.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    chunks = re.split(r"(?m)^#NOTEDATA:;\s*\r?\n", text)
    song_tags = tag_map(chunks[0])
    song_file = song_tags.get("SONGFILENAME", "")
    song_dir = split_path(song_file)
    song_dir = song_dir.rsplit("/", 1)[0] if "/" in song_dir else ""
    pack = song_dir.split("/", 1)[0] if song_dir else ""
    bpm_bounds = parse_bpms(song_tags.get("BPMS"))
    bpm_min = bpm_bounds[0] if bpm_bounds else ""
    bpm_max = bpm_bounds[1] if bpm_bounds else ""
    bpm_display = format_bpm_display(song_tags.get("DISPLAYBPM"), bpm_min, bpm_max)
    rows = []
    for chunk in chunks[1:]:
        tags = tag_map(chunk)
        chart_type = tags.get("STEPSTYPE", "")
        difficulty = tags.get("DIFFICULTY", "")
        if not chart_type or not difficulty:
            continue
        radar_values = tags.get("RADARVALUES", "").split(",")
        radar = {name: number(value) for name, value in zip(RADAR_FIELDS, radar_values)}
        tech = [number(v, -1) for v in tags.get("TECHCOUNTS", "").split(",")]
        key = (song_dir.casefold(), chart_type.casefold(), difficulty.casefold())
        score = scores.get(key, {})
        percent = number(score.get("PercentDP")) * 100
        display_name = tags.get("CHARTNAME") or tags.get("DESCRIPTION", "")
        rows.append({
            "Title": song_tags.get("TITLE", path.stem), "Artist": song_tags.get("ARTIST", ""),
            "Pack": pack, "Type": chart_type, "Difficulty": difficulty, "Course path": song_dir,
            "Meter": number(tags.get("METER")),
            "Time": number(song_tags.get("MUSICLENGTH")) if song_tags.get("MUSICLENGTH") else "",
            "BPM": bpm_display, "bpm_min": bpm_min, "bpm_max": bpm_max,
            "Chart": display_name,
            "Score": number(score.get("Score")) if score else "",
            "Grade": GRADE_NAMES.get(score.get("Grade", ""), score.get("Grade", "")),
            "Best %": round(percent, 2) if score else "", "Plays": number(score.get("plays")),
            "Last played": score.get("last_played", ""),
            # ITGmania formats #PEAKNPS as player-separated sections (P1|P2); take player 1.
            "Peak NPS": number(tags.get("PEAKNPS", "").split("|")[0]) if tags.get("PEAKNPS") else "",
            "Taps/Holds": radar.get("TapsAndHolds", ""), "Jumps": radar.get("Jumps", ""),
            "Holds": radar.get("Holds", ""), "Rolls": radar.get("Rolls", ""),
            "Mines": radar.get("Mines", ""), "Hands": radar.get("Hands", ""),
            "Lifts": radar.get("Lifts", ""),
            **{name: number(score.get("tap_" + name)) if score else "" for name in TAP_FIELDS},
            "Max combo": number(score.get("MaxCombo")) if score else "",
            **{name: tech[i] if i < len(tech) and tech[i] >= 0 else ""
               for i, name in enumerate(TECH_FIELDS)},
        })
    return rows


def looks_like_song_tree(cache: Path) -> bool:
    """Return whether the selected folder resembles Songs/Pack/Song/*.sm|*.ssc."""
    for pack in cache.iterdir():
        if not pack.is_dir():
            continue
        for song in pack.iterdir():
            if song.is_dir() and any(
                chart.is_file() and chart.suffix.casefold() in {".sm", ".ssc"}
                for chart in song.iterdir()
            ):
                return True
    return False


def course_song_line(course_path: str, difficulty: str) -> str:
    """Format one #SONG entry for a CRS file."""
    return f"#SONG:{course_path}:{difficulty}:;"


def course_song_lines(rows: list[dict]) -> list[str]:
    """Format #SONG lines from chart rows that already carry Course path and Difficulty."""
    return [course_song_line(row["Course path"], row["Difficulty"]) for row in rows]


def format_new_course(title: str, song_lines: list[str], newline: str = "\n") -> str:
    """Build a complete new CRS document body (including a trailing newline)."""
    lines = [f"#COURSE:{title};", *song_lines]
    return newline.join(lines) + newline


def _contains_unsafe_course_text(value: str) -> bool:
    return any(char in value for char in COURSE_UNSAFE_CHARS)


def validate_course_fields(rows: list[dict], title: str | None = None) -> str | None:
    """Return a human-readable error if course fields are invalid, else None.

    When ``title`` is provided (not None), a blank title is rejected. Pass
    ``title=None`` to skip title checks (e.g. append flows that do not set one).

    Does not decide mixed-type policy; callers that care about mixed chart types
    should inspect the rows themselves after this returns None.
    """
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            return "Enter a title for this course."
        if _contains_unsafe_course_text(cleaned):
            return "Course titles cannot contain semicolons, colons, or newlines."
    if not rows:
        return "Add at least one chart to the course."
    if any(not row.get("Course path") or not row.get("Difficulty") for row in rows):
        return "One or more selected charts are missing a song path or difficulty."
    if any(_contains_unsafe_course_text(str(row.get("Course path", ""))) for row in rows):
        return "Song paths cannot contain semicolons, colons, or newlines."
    if any(_contains_unsafe_course_text(str(row.get("Difficulty", ""))) for row in rows):
        return "Difficulties cannot contain semicolons, colons, or newlines."
    return None


def parse_course_text(text: str) -> dict:
    """Parse CRS text into title, ordered song entries, and trailing-risk info.

    Returns a dict with:
      title: str | None
      songs: list of {path, difficulty, raw} in file order
      trailing_risk: 'MODS' | 'GAINSECONDS' | None
      has_course: bool
    """
    course_match = re.search(r"#COURSE\s*:([^;]*);", text, re.IGNORECASE)
    title = course_match.group(1).strip() if course_match else None
    songs = []
    for match in re.finditer(
        r"#SONG\s*:([^:;\r\n]*):([^:;\r\n]*):([^;]*);", text, re.IGNORECASE
    ):
        songs.append({
            "path": match.group(1).strip(),
            "difficulty": match.group(2).strip(),
            "raw": match.group(0),
        })
    song_starts = list(re.finditer(r"#SONG\s*:", text, re.IGNORECASE))
    trailing_risk = None
    if song_starts:
        trailing_risk = course_trailing_risk(text)
    return {
        "title": title,
        "songs": songs,
        "trailing_risk": trailing_risk,
        "has_course": course_match is not None,
    }


def course_trailing_risk(text: str) -> str | None:
    """Return 'MODS' or 'GAINSECONDS' if that directive follows the last #SONG, else None."""
    songs = list(re.finditer(r"#SONG\s*:", text, re.IGNORECASE))
    if not songs:
        return None
    risky = re.search(r"#(MODS|GAINSECONDS)\s*:", text[songs[-1].end():], re.IGNORECASE)
    if not risky:
        return None
    return risky.group(1).upper()


def course_append_bytes(existing: bytes, song_lines: list[str]) -> bytes:
    """Validate an existing CRS and return only the bytes safe to append."""
    text = existing.decode("utf-8-sig")
    parsed = parse_course_text(text)
    if not parsed["has_course"] or not list(re.finditer(r"#SONG\s*:", text, re.IGNORECASE)):
        raise ValueError("The selected file must contain #COURSE and at least one #SONG entry.")
    risk = parsed["trailing_risk"]
    if risk:
        raise ValueError(
            f"This course ends with #{risk}, which may affect the chart entries being appended. "
            "The existing course was left unchanged. Remove or resolve that directive in the course file, then try again."
        )
    if not song_lines:
        raise ValueError("Add at least one chart before appending to a course.")

    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = newline if existing and not existing.endswith((b"\n", b"\r")) else b""
    return prefix + newline.join(line.encode("utf-8") for line in song_lines) + newline


SEARCH_FIELD_ALIASES = {
    "m": "meter",
    "meter": "meter",
    "diff_meter": "meter",
    "bpm": "bpm",
    "tempo": "bpm",
    "time": "time",
    "len": "time",
    "length": "time",
    "title": "title",
    "t": "title",
    "artist": "artist",
    "a": "artist",
    "pack": "pack",
    "p": "pack",
    "chart": "chart",
    "c": "chart",
    "diff": "difficulty",
    "difficulty": "difficulty",
    "d": "difficulty",
    "type": "type",
    "mode": "type",
    "grade": "grade",
    "g": "grade",
    "score": "score",
    "percent": "percent",
    "pct": "percent",
    "plays": "plays",
    "nps": "peak_nps",
    "peak_nps": "peak_nps",
    "peaknps": "peak_nps",
    **{f.casefold(): f.casefold() for f in TECH_FIELDS},
}


def parse_duration_seconds(value: str) -> float | None:
    """Parse a duration string in seconds (e.g. '120', '90.5') or mm:ss / hh:mm:ss."""
    value = str(value or "").strip()
    if not value:
        return None
    if ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except (TypeError, ValueError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_numeric_bound(raw: str, is_duration: bool = False) -> tuple | None:
    """Parse an operator or range constraint into a normalized tuple.

    Returns:
      ('range', low, high)
      ('>', val)
      ('>=', val)
      ('<', val)
      ('<=', val)
      ('==', val)
    """
    raw = str(raw or "").strip()
    if not raw:
        return None

    def conv(s: str) -> float | None:
        if is_duration:
            return parse_duration_seconds(s)
        try:
            return float(s.strip())
        except (TypeError, ValueError):
            return None

    if raw.startswith(">="):
        v = conv(raw[2:])
        return (">=", v) if v is not None else None
    if raw.startswith("<="):
        v = conv(raw[2:])
        return ("<=", v) if v is not None else None
    if raw.startswith(">"):
        v = conv(raw[1:])
        return (">", v) if v is not None else None
    if raw.startswith("<"):
        v = conv(raw[1:])
        return ("<", v) if v is not None else None
    if raw.startswith("="):
        v = conv(raw[1:])
        return ("==", v) if v is not None else None

    if ".." in raw:
        parts = raw.split("..", 1)
        low, high = conv(parts[0]), conv(parts[1])
        if low is not None and high is not None:
            return ("range", min(low, high), max(low, high))

    if "-" in raw and not raw.startswith("-"):
        parts = raw.split("-", 1)
        low, high = conv(parts[0]), conv(parts[1])
        if low is not None and high is not None:
            return ("range", min(low, high), max(low, high))

    v = conv(raw)
    return ("==", v) if v is not None else None


def _compare_bound(bound: tuple, actual) -> bool:
    if actual in (None, ""):
        return False
    try:
        val = float(actual)
    except (TypeError, ValueError):
        return False

    op = bound[0]
    if op == "range":
        return bound[1] <= val <= bound[2]
    target = bound[1]
    if op == ">":
        return val > target
    if op == ">=":
        return val >= target
    if op == "<":
        return val < target
    if op == "<=":
        return val <= target
    if op == "==":
        return val == target
    return False


def _compare_bpm_bound(bound: tuple, row: dict) -> bool:
    b_min = row.get("bpm_min")
    b_max = row.get("bpm_max")
    if b_min in (None, "") or b_max in (None, ""):
        return False
    try:
        b_min = float(b_min)
        b_max = float(b_max)
    except (TypeError, ValueError):
        return False

    op = bound[0]
    if op == "range":
        low, high = bound[1], bound[2]
        return b_max >= low and b_min <= high
    val = bound[1]
    if op == ">":
        return b_max > val
    if op == ">=":
        return b_max >= val
    if op == "<":
        return b_min < val
    if op == "<=":
        return b_min <= val
    if op == "==":
        return b_min <= val <= b_max
    return False


def parse_search_query(query: str) -> dict:
    """Parse a query string into free-text terms and structured field criteria."""
    query = str(query or "").strip()
    if not query:
        return {"free_terms": [], "free_text": "", "directives": []}

    try:
        tokens = shlex.split(query)
    except ValueError:
        tokens = query.split()

    free_terms = []
    directives = []

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            prefix, val = token.split(":", 1)
            field = prefix.strip().casefold()
            if field in SEARCH_FIELD_ALIASES:
                canonical = SEARCH_FIELD_ALIASES[field]
                val = val.strip().strip('"').strip("'")
                directives.append((canonical, val))
                continue
        free_terms.append(token.casefold())

    free_text = " ".join(shlex.quote(term) for term in free_terms)
    return {"free_terms": free_terms, "free_text": free_text, "directives": directives}


def match_chart_query(row: dict, query: str | dict) -> bool:
    """Return whether a chart row satisfies the search query."""
    criteria = query if isinstance(query, dict) else parse_search_query(query)

    # 1. Free terms match anywhere across main textual fields
    if criteria.get("free_terms"):
        text_corpus = " ".join(
            str(row.get(k, "")) for k in ("Title", "Artist", "Pack", "Chart", "Type", "Difficulty")
        ).casefold()
        for term in criteria["free_terms"]:
            if term not in text_corpus:
                return False

    # 2. Field directives
    for field, raw_val in criteria.get("directives", []):
        if field == "meter":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Meter")):
                return False
        elif field == "bpm":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bpm_bound(b, row):
                return False
        elif field == "time":
            b = parse_numeric_bound(raw_val, is_duration=True)
            if not b or not _compare_bound(b, row.get("Time")):
                return False
        elif field == "title":
            if raw_val.casefold() not in str(row.get("Title", "")).casefold():
                return False
        elif field == "artist":
            if raw_val.casefold() not in str(row.get("Artist", "")).casefold():
                return False
        elif field == "pack":
            if raw_val.casefold() not in str(row.get("Pack", "")).casefold():
                return False
        elif field == "chart":
            if raw_val.casefold() not in str(row.get("Chart", "")).casefold():
                return False
        elif field == "difficulty":
            if raw_val.casefold() not in str(row.get("Difficulty", "")).casefold():
                return False
        elif field == "type":
            if raw_val.casefold() not in str(row.get("Type", "")).casefold():
                return False
        elif field == "grade":
            chart_grade = str(row.get("Grade", ""))
            if raw_val.startswith((">=", "<=", ">", "<")):
                op = raw_val[:2] if raw_val[:2] in (">=", "<=") else raw_val[:1]
                target_grade = raw_val[len(op):].strip()
                c_rank = grade_sort_key(chart_grade)
                t_rank = grade_sort_key(target_grade)
                # Lower grade_sort_key rank means higher/better grade
                if op == ">=" and not (c_rank <= t_rank):
                    return False
                if op == "<=" and not (c_rank >= t_rank):
                    return False
                if op == ">" and not (c_rank < t_rank):
                    return False
                if op == "<" and not (c_rank > t_rank):
                    return False
            else:
                if raw_val.casefold() != chart_grade.casefold():
                    return False
        elif field == "score":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Score")):
                return False
        elif field == "percent":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Best %")):
                return False
        elif field == "plays":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Plays")):
                return False
        elif field == "peak_nps":
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get("Peak NPS")):
                return False
        elif field in {f.casefold() for f in TECH_FIELDS}:
            canonical_field = next(f for f in TECH_FIELDS if f.casefold() == field)
            b = parse_numeric_bound(raw_val)
            if not b or not _compare_bound(b, row.get(canonical_field)):
                return False

    return True


def filter_token_text(token) -> str:
    """Text form of a chart filter token: a plain string, or several values joined by spaces.

    A BPM range bar needs two directives (bpm:>=120 bpm:<140), so its token is a tuple of values.
    """
    if token is None:
        return ""
    if isinstance(token, str):
        return token
    return " ".join(token)


def filter_texts_match(first, second) -> bool:
    """Whether two chart filter texts select the same charts, however they were typed.

    Each text is one filter value or several joined by spaces ("11", ">=120 <140"); a bar's token tuple
    is accepted too. Every value is read the way the search reads it (parse_numeric_bound), so "11.0"
    matches "11" and "=11", and the order of the values does not matter ("<140 >=120" matches
    ">=120 <140"). Text that is not a number (a difficulty name) is compared ignoring case.
    """
    def readings(text):
        values = filter_token_text(text).split()
        keys = [parse_numeric_bound(value) or ("text", value.casefold()) for value in values]
        return sorted(keys, key=repr)

    return bool(filter_token_text(first).strip()) and readings(first) == readings(second)


def _needs_quotes(text: str) -> bool:
    return not text or any(char.isspace() or char in "\"'\\" for char in text)


def _quote_for_search(text: str) -> str:
    """Quote text for the search box so that shlex.split reads it back unchanged.

    Text with no spaces or quote characters stays as it is. Anything else goes in double quotes,
    with backslashes and double quotes escaped (the only escapes shlex honors inside them).
    """
    if not _needs_quotes(text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_search_token(token: str) -> str:
    """Write one token from shlex.split back as search text that reads as the same single token.

    A directive such as `pack:In The Groove` gets only its value quoted (pack:"In The Groove").
    Every other token, including free text that happens to contain a colon, is quoted as a whole,
    so a quoted phrase like "Dance Dance: Revolution" stays one phrase instead of splitting at the
    space before the colon.
    """
    prefix, colon, value = token.partition(":")
    if colon and not _needs_quotes(prefix) and SEARCH_FIELD_ALIASES.get(prefix.casefold()):
        return f"{prefix}:{_quote_for_search(value) if value else ''}"
    return _quote_for_search(token)


def replace_search_directive(query: str, directive_prefix: str, new_value: str | tuple[str, ...] | list[str] | None) -> str:
    """Replace or remove a directive in a search query, preserving free-text terms and other directives.

    Uses shlex tokenization consistent with parse_search_query and SEARCH_FIELD_ALIASES.
    If new_value is None, removes any directives matching directive_prefix or its aliases.
    If new_value is a string, replaces the first matching directive in-place or appends it.
    If new_value is several values, they are written as several directives of that field
    (e.g. (">=120", "<140") gives "bpm:>=120 bpm:<140") in the first matching directive's place.
    Any other directives of that field are removed.
    """
    canonical_target = SEARCH_FIELD_ALIASES.get(directive_prefix.casefold(), directive_prefix.casefold())
    if new_value is None:
        new_values = []
    elif isinstance(new_value, str):
        new_values = [new_value]
    else:
        new_values = list(new_value)

    def _directive_tokens() -> list[str]:
        tokens_out = []
        for value in new_values:
            already_quoted = len(value) >= 2 and value.startswith('"') and value.endswith('"')
            text = value if already_quoted or not value else _quote_for_search(value)
            tokens_out.append(f"{canonical_target}:{text}")
        return tokens_out

    raw_query = str(query or "").strip()
    if not raw_query:
        return " ".join(_directive_tokens())

    try:
        tokens = shlex.split(raw_query)
        unbalanced = False
    except ValueError:
        # Unbalanced quote: parse_search_query splits on spaces in this case, so the words are raw text.
        tokens = raw_query.split()
        unbalanced = True

    # Each piece is (text, is_new_directive). Kept pieces are the query's own words.
    pieces = []
    replaced = False

    for token in tokens:
        if ":" in token:
            field = token.split(":", 1)[0].strip().casefold()
            if SEARCH_FIELD_ALIASES.get(field) == canonical_target:
                if not replaced and new_values:
                    pieces.extend((text, True) for text in _directive_tokens())
                    replaced = True
                continue
        pieces.append((token, False))

    if not replaced and new_values:
        pieces.extend((text, True) for text in _directive_tokens())

    if not unbalanced:
        # shlex took the quotes off, so each kept word is written back with quotes where it needs them.
        return " ".join(text if is_new else _format_search_token(text) for text, is_new in pieces)

    # Unbalanced case: keep the words as typed, so the search still reads the same way, unless that would
    # break the result: either a new value needs quotes (a space-separated search cannot hold it), or the
    # word that held the stray quote is gone and the rest is balanced, which the search would now read with
    # its quotes stripped. Then each kept word's quotes are escaped so it is still read as typed.
    typed = " ".join(text for text, _ in pieces)
    try:
        shlex.split(typed)
        typed_reads_as_typed = False
    except ValueError:
        typed_reads_as_typed = not any(is_new and _needs_quotes(text) for text, is_new in pieces)
    if typed_reads_as_typed:
        return typed
    return " ".join(text if is_new else _quote_for_search(text) for text, is_new in pieces)


# Chart metric name -> canonical search directive field that filters it.
CHART_FILTER_FIELDS = {"Difficulty": "difficulty", "Meter": "meter", "BPM": "bpm"}


def get_active_chart_filters(diff_filter: str, search_query: str) -> list[tuple[str, str]]:
    """Return [(metric_name, active_value), ...] for every chart metric currently filtering the table.

    Order is Difficulty, Meter, BPM. The difficulty combobox takes precedence over a diff: directive.
    When a field has several directives (bpm:>=120 bpm:<140) their values are joined with spaces,
    which is the same text filter_token_text gives for a BPM bar.
    """
    values: dict[str, list[str]] = {metric: [] for metric in CHART_FILTER_FIELDS}
    metric_by_field = {field: metric for metric, field in CHART_FILTER_FIELDS.items()}
    for field, val in parse_search_query(search_query).get("directives", []):
        if field in metric_by_field and val:
            values[metric_by_field[field]].append(val)

    active = []
    if diff_filter and diff_filter != "All difficulties":
        active.append(("Difficulty", diff_filter))
    elif values["Difficulty"]:
        active.append(("Difficulty", " ".join(values["Difficulty"])))
    for metric in ("Meter", "BPM"):
        if values[metric]:
            active.append((metric, " ".join(values[metric])))
    return active


def get_active_chart_filter(diff_filter: str, search_query: str) -> tuple[str, str] | None:
    """Return the first (metric_name, active_value) from get_active_chart_filters, or None."""
    active = get_active_chart_filters(diff_filter, search_query)
    return active[0] if active else None


def aggregate_meter_distribution(rows: list[dict], active_val: str | None = None) -> list[tuple[str, int, str, bool]]:
    """Aggregate row counts per meter level.

    Float meters like 11.0 are normalized to integer strings ("11"). parse_cache_file stores a chart with
    no METER tag as 0, so such charts get an ordinary "0" bar: the table shows 0 for them and meter:0
    finds them, which keeps the bar's number equal to the rows after clicking it. Only rows with no
    value at all or text that is not a number (not produced by parse_cache_file) are grouped into "?"
    at the end (non-interactive).
    Returns list of (label, count, filter_token, is_active).
    """
    counts: dict[str, int] = {}
    numeric_keys: dict[float, str] = {}
    missing_count = 0

    for row in rows:
        meter_raw = row.get("Meter")
        if meter_raw in (None, ""):
            missing_count += 1
            continue
        try:
            m_val = float(meter_raw)
            label = str(int(m_val)) if m_val.is_integer() else f"{m_val:g}"
            counts[label] = counts.get(label, 0) + 1
            numeric_keys[m_val] = label
        except (TypeError, ValueError):
            missing_count += 1

    result = []
    for m_val in sorted(numeric_keys.keys()):
        label = numeric_keys[m_val]
        count = counts[label]
        is_active = filter_texts_match(active_val, label) if active_val is not None else False
        result.append((label, count, label, is_active))

    if missing_count > 0:
        result.append(("?", missing_count, "", False))

    return result


def aggregate_difficulty_distribution(rows: list[dict], active_val: str | None = None) -> list[tuple[str, int, str, bool]]:
    """Aggregate row counts per difficulty tier in canonical DIFFICULTY_ORDER.

    Returns list of (label, count, filter_token, is_active).
    """
    counts: dict[str, int] = {diff: 0 for diff in DIFFICULTY_ORDER}
    extra_diffs: dict[str, int] = {}

    for row in rows:
        diff = str(row.get("Difficulty") or "").strip()
        matched = False
        for d in DIFFICULTY_ORDER:
            if diff.casefold() == d.casefold():
                counts[d] += 1
                matched = True
                break
        if not matched and diff:
            extra_diffs[diff] = extra_diffs.get(diff, 0) + 1

    result = []
    for diff in DIFFICULTY_ORDER:
        count = counts.get(diff, 0)
        is_active = (active_val.casefold() == diff.casefold()) if active_val else False
        result.append((diff, count, diff, is_active))

    for diff, count in extra_diffs.items():
        is_active = (active_val.casefold() == diff.casefold()) if active_val else False
        result.append((diff, count, diff, is_active))

    return result


# (bar label, bpm: directive values that select the bar). Each range is half-open [low, high), so a
# chart at exactly 140 BPM belongs to 140-159 only, and a chart at 139.5 belongs to 120-139.
BPM_BINS = (
    ("<120", ("<120",)),
    ("120-139", (">=120", "<140")),
    ("140-159", (">=140", "<160")),
    ("160-179", (">=160", "<180")),
    ("180-199", (">=180", "<200")),
    ("200+", (">=200",)),
)


def _bpm_range(row: dict) -> tuple[float, float] | None:
    """Return a row's (bpm_min, bpm_max), or None when either is missing or not a number."""
    try:
        low, high = row.get("bpm_min"), row.get("bpm_max")
        if low in (None, "") or high in (None, ""):
            return None
        return float(low), float(high)
    except (TypeError, ValueError):
        return None


def aggregate_bpm_distribution(
    rows: list[dict], active_val: str | None = None
) -> list[tuple[str, int, tuple[str, ...], bool]]:
    """Count charts per BPM range; a chart counts in every range its tempo span touches.

    A chart that runs 100-150 BPM is counted in <120, 120-139 and 140-159. Each bar is counted with
    the same test as the bpm: filter (_compare_bpm_bound) on the bar's own directives, so the number
    on a bar always equals the number of rows the table shows after clicking it. Bar counts therefore
    add up to more than the number of charts when some charts change tempo across ranges.

    Returns list of (label, count, filter_token, is_active). filter_token is a tuple of bpm:
    directive values; is_active compares its space-joined text with active_val.
    """
    bounds_by_label = {
        label: [parse_numeric_bound(value) for value in values] for label, values in BPM_BINS
    }
    counts = {label: 0 for label, _ in BPM_BINS}
    missing_count = 0

    for row in rows:
        if _bpm_range(row) is None:
            missing_count += 1
            continue
        for label, bounds in bounds_by_label.items():
            if all(_compare_bpm_bound(bound, row) for bound in bounds):
                counts[label] += 1

    result = []
    for label, values in BPM_BINS:
        is_active = bool(active_val) and filter_texts_match(active_val, values)
        result.append((label, counts[label], values, is_active))

    if missing_count > 0:
        result.append(("?", missing_count, "", False))

    return result


def distribution_summary_stats(metric: str, rows: list[dict]) -> str:
    """Calculate summary statistics for the active distribution metric on current visible rows.

    For multimodal data, the lowest mode is selected deterministically.
    """
    if not rows:
        return "0 charts"

    if metric == "Meter":
        vals = []
        for r in rows:
            m = r.get("Meter")
            if m not in (None, ""):
                try:
                    v = float(m)
                    vals.append(int(v) if v.is_integer() else v)
                except (TypeError, ValueError):
                    pass
        if not vals:
            return f"{len(rows):,} charts"
        mean_val = statistics.mean(vals)
        med_val = statistics.median(vals)
        modes = statistics.multimode(vals)
        mode_val = min(modes)
        return f"{len(rows):,} charts · Median: {med_val:g} · Mean: {mean_val:.1f} · Mode: {mode_val:g}"

    if metric == "Difficulty":
        diff_counts = {d: 0 for d in DIFFICULTY_ORDER}
        for r in rows:
            d = str(r.get("Difficulty") or "")
            for c in DIFFICULTY_ORDER:
                if d.casefold() == c.casefold():
                    diff_counts[c] += 1
                    break
        sorted_diffs = sorted(diff_counts.items(), key=lambda item: (-item[1], DIFFICULTY_ORDER.index(item[0])))
        top_diff, top_count = sorted_diffs[0]
        if top_count > 0:
            return f"{len(rows):,} charts · Mode: {top_diff} ({top_count:,})"
        return f"{len(rows):,} charts"

    if metric == "BPM":
        vals = []
        for r in rows:
            b = r.get("bpm_max")
            if b not in (None, ""):
                try:
                    vals.append(float(b))
                except (TypeError, ValueError):
                    pass
        if not vals:
            return f"{len(rows):,} charts"
        mean_val = statistics.mean(vals)
        med_val = statistics.median(vals)
        return (f"{len(rows):,} charts · Median: {med_val:.0f} · Mean: {mean_val:.0f}\n"
                "A chart counts in every range its tempo touches.")

    return f"{len(rows):,} charts"


# --- Advanced Search dialog <-> search-bar text -------------------------------------------
# The dialog has boxes for only some filters. split_dialog_query() fills the boxes from the
# search bar and hands back everything the boxes cannot show exactly as "other", so applying
# the dialog never silently drops or changes a filter. build_dialog_query() is the reverse.

DIALOG_TEXT_FIELDS = ("title", "artist", "pack")
DIALOG_RANGE_FIELDS = ("meter", "bpm", "time", "peak_nps")
_DIALOG_RANGE_TOKEN_NAMES = {"meter": "meter", "bpm": "bpm", "time": "time", "peak_nps": "nps"}


def _has_quote_chars(text: str) -> bool:
    return any(char in text for char in "\"'\\")


def _format_dialog_token(field: str, value: str) -> str:
    """Write ``field:value`` so parse_search_query reads the same value back."""
    token = f"{field}:{value}"
    if not any(char.isspace() or char in "\"'\\" for char in token):
        return token
    if not _has_quote_chars(value):
        return f'{field}:"{value}"'
    return shlex.quote(token)


def _format_bound_number(value: float, is_duration: bool) -> str:
    if is_duration:
        return format_duration(value)
    return str(int(value)) if float(value).is_integer() else str(value)


def _absorb_into_dialog(slots: dict, field: str, value: str) -> bool:
    """Put one filter into a dialog box if the box can show it exactly; return whether it did."""
    if field in DIALOG_TEXT_FIELDS:
        if slots[field] or _has_quote_chars(value):
            return False
        slots[field] = value
        return True

    if field in DIALOG_RANGE_FIELDS:
        is_duration = field == "time"
        bound = parse_numeric_bound(value, is_duration=is_duration)
        if bound is None:
            return False
        numbers = bound[1:]
        # A time box shows whole seconds only; a fractional time would be rounded.
        if is_duration and not all(float(n).is_integer() for n in numbers):
            return False
        low, high = slots[field]
        op = bound[0]
        if op in ("range", "==") and not low and not high:
            new_low, new_high = (bound[1], bound[2]) if op == "range" else (bound[1], bound[1])
            slots[field] = [_format_bound_number(new_low, is_duration),
                            _format_bound_number(new_high, is_duration)]
            return True
        if op == ">=" and not low:
            slots[field][0] = _format_bound_number(bound[1], is_duration)
            return True
        if op == "<=" and not high:
            slots[field][1] = _format_bound_number(bound[1], is_duration)
            return True
        # Strict > and < have no box: the boxes mean >= and <=.
        return False

    if field == "grade":
        # The Min Grade box means "this grade or better" (>=) and exists once.
        if slots["grade"] or not value.startswith(">="):
            return False
        wanted = value[2:].strip().casefold()
        for option in GRADE_OPTIONS:
            if option.casefold() == wanted:
                slots["grade"] = option
                return True
        return False

    return False


def split_dialog_query(query: str) -> dict:
    """Split search-bar text into Advanced Search dialog box values plus leftovers.

    Returns a dict with free_text, title, artist, pack, grade (a grade label or ""), meter,
    bpm, time and peak_nps (each a (min, max) pair of strings, "" when unset), and other:
    search text for every filter the boxes cannot show exactly (for example plays:>=3,
    jacks:>0, grade:<B, meter:>10). build_dialog_query() adds ``other`` back unchanged.
    """
    parsed = parse_search_query(query)
    slots = {"title": "", "artist": "", "pack": "", "grade": "",
             **{name: ["", ""] for name in DIALOG_RANGE_FIELDS}}
    other = []
    for field, value in parsed["directives"]:
        if not _absorb_into_dialog(slots, field, value):
            other.append(_format_dialog_token(field, value))
    result = {"free_text": parsed["free_text"], **slots, "other": " ".join(other)}
    for name in DIALOG_RANGE_FIELDS:
        result[name] = tuple(slots[name])
    return result


def build_dialog_query(parts: dict) -> str:
    """Turn Advanced Search dialog box values (see split_dialog_query) into search-bar text."""
    def text(key: str) -> str:
        return str(parts.get(key) or "").strip()

    tokens = []
    if text("free_text"):
        tokens.append(text("free_text"))
    for field in DIALOG_TEXT_FIELDS:
        if text(field):
            tokens.append(_format_dialog_token(field, text(field)))
    for field in DIALOG_RANGE_FIELDS:
        low, high = (str(part or "").strip() for part in parts.get(field, ("", "")))
        name = _DIALOG_RANGE_TOKEN_NAMES[field]
        if low and high:
            tokens.append(f"{name}:{low}" if low == high else f"{name}:{low}-{high}")
        elif low:
            tokens.append(f"{name}:>={low}")
        elif high:
            tokens.append(f"{name}:<={high}")
    if text("grade") and text("grade") != "Any":
        tokens.append(f"grade:>={text('grade')}")
    if text("other"):
        tokens.append(text("other"))
    return " ".join(tokens)


