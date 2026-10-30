"""Tk-independent parsing and formatting helpers for the ITGmania library."""

from __future__ import annotations

import re
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
COURSE_UNSAFE_CHARS = (";", ":", "\r", "\n")

__all__ = [
    "COURSE_UNSAFE_CHARS",
    "DIFFICULTY_ORDER",
    "RADAR_FIELDS",
    "TAP_FIELDS",
    "TECH_FIELDS",
    "course_append_bytes",
    "course_song_line",
    "course_song_lines",
    "course_trailing_risk",
    "difficulty_sort_key",
    "format_duration",
    "format_new_course",
    "looks_like_song_tree",
    "number",
    "parse_cache_file",
    "parse_course_text",
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


def tag_map(text: str) -> dict[str, str]:
    return {m.group(1).upper(): m.group(2).strip() for m in
            re.finditer(r"(?m)^#([^:;\r\n]+):([^;\r\n]*);", text)}


def split_path(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    if value.lower().startswith("songs/"):
        value = value[6:]
    return value


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
            result[key] = {"plays": score_list.findtext("NumTimesPlayed", "0"),
                           "last_played": score_list.findtext("LastPlayed", ""), **best_data}
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
            "Chart": display_name,
            "Score": number(score.get("Score")) if score else "",
            "Grade": GRADE_NAMES.get(score.get("Grade", ""), score.get("Grade", "")),
            "Best %": round(percent, 2) if score else "", "Plays": number(score.get("plays")),
            "Last played": score.get("last_played", ""), "Peak NPS": number(tags.get("PEAKNPS")),
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
