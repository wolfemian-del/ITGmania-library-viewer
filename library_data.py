"""Tk-independent parsing and formatting helpers for the ITGmania library."""

from __future__ import annotations

import re
import shlex
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
    "COURSE_UNSAFE_CHARS",
    "DIFFICULTY_ORDER",
    "GRADE_OPTIONS",
    "GRADE_NAMES",
    "RADAR_FIELDS",
    "TAP_FIELDS",
    "TECH_FIELDS",
    "bpm_sort_key",
    "course_append_bytes",
    "course_song_line",
    "course_song_lines",
    "course_trailing_risk",
    "difficulty_sort_key",
    "format_bpm_display",
    "format_duration",
    "format_new_course",
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
    return {m.group(1).upper(): m.group(2).strip() for m in
            re.finditer(r"(?m)^#([^:;\r\n]+):([^;\r\n]*);", text)}


def split_path(value: str) -> str:
    """Normalize an ITGmania song path to its path below the Songs directory.

    Cache entries usually use ``/Songs/Pack/Song/file.sm`` while Stats.xml
    commonly uses ``Songs/Pack/Song``. Some installations may instead store
    a filesystem-absolute path, so strip the prefix through the *component*
    named Songs wherever it occurs.
    """
    parts = value.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.casefold() == "songs":
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
            "Peak NPS": number(tags.get("PEAKNPS")) if tags.get("PEAKNPS") else "",
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
        return {"free_terms": [], "directives": []}

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

    return {"free_terms": free_terms, "directives": directives}


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


