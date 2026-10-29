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

__all__ = [
    "DIFFICULTY_ORDER",
    "RADAR_FIELDS",
    "TAP_FIELDS",
    "TECH_FIELDS",
    "course_append_bytes",
    "difficulty_sort_key",
    "format_duration",
    "looks_like_song_tree",
    "number",
    "parse_cache_file",
    "split_path",
    "stats_index",
    "tag_map",
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


def course_append_bytes(existing: bytes, song_lines: list[str]) -> bytes:
    """Validate an existing CRS and return only the bytes safe to append."""
    text = existing.decode("utf-8-sig")
    songs = list(re.finditer(r"#SONG\s*:", text, re.IGNORECASE))
    if not re.search(r"#COURSE\s*:", text, re.IGNORECASE) or not songs:
        raise ValueError("The selected file must contain #COURSE and at least one #SONG entry.")
    risky = re.search(r"#(MODS|GAINSECONDS)\s*:", text[songs[-1].end():], re.IGNORECASE)
    if risky:
        raise ValueError(
            f"This course ends with #{risky.group(1).upper()}, which may affect the chart entries being appended. "
            "The existing course was left unchanged. Remove or resolve that directive in the course file, then try again."
        )
    if not song_lines:
        raise ValueError("Add at least one chart before appending to a course.")

    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = newline if existing and not existing.endswith((b"\n", b"\r")) else b""
    return prefix + newline.join(line.encode("utf-8") for line in song_lines) + newline
