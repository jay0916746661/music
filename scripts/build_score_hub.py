#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ROOT_ARG = os.environ.get("SCORE_HUB_ROOT") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not ROOT_ARG:
    raise SystemExit("Set SCORE_HUB_ROOT or pass the lesson root folder as the first argument.")

ROOT = Path(ROOT_ARG).expanduser()
MANIFEST = ROOT / "_manifest" / "manifest.json"
CATALOG = ROOT / "_manifest" / "practice-catalog.json"
OUT = PROJECT_ROOT / "data" / "score-hub.json"
PUBLIC_OUT = PROJECT_ROOT / "data" / "score-hub-public.json"


def file_url(path: Path) -> str:
    return "file://" + quote(str(path), safe="/():")


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().strip(".")
    return value[:140] or fallback


def to_embed(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(?:youtu\.be/|youtube\.com/watch\?v=)([^&?/]+)", url)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
    return ""


def series_from_title(title: str) -> str:
    patterns = [
        "Peaceful", "Twister", "Exercise", "Crystal", "Extensions", "Etude", "Jazz",
        "Blues", "Kintsugi", "Circle", "Smooth", "Lick", "Tsubasa", "Wings",
        "Omega", "Evenings", "Interchange", "Melodic", "Komorebi", "Opus",
        "System", "Natural", "Ending", "Standard",
    ]
    for pattern in patterns:
        if title.startswith(pattern):
            return pattern
    return title.split()[0]


def make_practice_steps(item: dict, ext_counts: Counter) -> list[str]:
    steps = []
    if ext_counts.get("pdf"):
        steps.append("先看譜面結構，標出段落與和弦重心。")
    if ext_counts.get("gp5") or ext_counts.get("gp"):
        steps.append("打開 Guitar Pro 對照指法與節奏，先慢速 loop。")
    if ext_counts.get("wav") or ext_counts.get("mp3"):
        steps.append("跟 backing track 做 2 輪，先求拍穩再求變奏。")
    if item.get("video_embed_url"):
        steps.append("先看影片一遍抓手感，再回到譜面做拆解。")
    if item.get("track") == "harmony-touch":
        steps.append("最後錄一版 clean tone，確認和弦轉位與旋律音有沒有唱出來。")
    elif item.get("track") == "fretboard-theory":
        steps.append("把主題句轉到另外兩個 key，確認不是只背位置。")
    elif item.get("track") == "blues-language":
        steps.append("抓 2 個句尾做 call-and-response，練到能自然接上去。")
    else:
        steps.append("完成後做一個 4 小節自己的變奏。")
    return steps[:5]


def main() -> int:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    catalog = {item["title"]: item for item in json.loads(CATALOG.read_text(encoding="utf-8"))}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["post_title"]].append(row)

    lessons = []
    series_counter = Counter()
    track_counter = Counter()
    format_counter = Counter()
    level_counter = Counter()

    for title, files in grouped.items():
        cat = catalog.get(title, {})
        folder = ROOT / sanitize_filename(title)
        ext_counts = Counter(item["extension"] for item in files)
        first = files[0]

        local_video = ""
        for candidate in sorted(folder.glob("*.mp4")):
            local_video = file_url(candidate)
            break

        pdf_links = []
        gp_links = []
        audio_links = []
        extra_links = []
        for item in files:
          fname = item["filename"]
          path = folder / fname
          link = {
              "label": fname,
              "extension": item["extension"],
              "href": file_url(path),
          }
          if item["extension"] == "pdf":
              pdf_links.append(link)
          elif item["extension"] in {"gp5", "gp"}:
              gp_links.append(link)
          elif item["extension"] in {"wav", "mp3"}:
              audio_links.append(link)
          else:
              extra_links.append(link)

        video_public = first.get("embed_url") or ""
        video_embed = to_embed(video_public)
        lesson = {
            "id": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
            "title": title,
            "series": series_from_title(title),
            "track": cat.get("track", "song-study"),
            "track_label": cat.get("track_label", "作品 / 單曲研究"),
            "level": cat.get("level", "core"),
            "priority_band": cat.get("priority_band", "later"),
            "priority_score": cat.get("priority_score", 50),
            "summary": (first.get("post_description_zh") or cat.get("summary") or "")[:220],
            "post_url": first.get("post_url", ""),
            "folder_href": file_url(folder),
            "video_local_url": local_video,
            "video_public_url": video_public,
            "video_embed_url": video_embed,
            "watch_url": local_video or video_embed or video_public,
            "formats": dict(ext_counts),
            "file_total": len(files),
            "pdf_links": pdf_links,
            "gp_links": gp_links,
            "audio_links": audio_links,
            "extra_links": extra_links,
            "practice_steps": make_practice_steps(cat, ext_counts),
            "extensions": cat.get("extensions", []),
        }
        lessons.append(lesson)
        series_counter[lesson["series"]] += 1
        track_counter[lesson["track_label"]] += 1
        level_counter[lesson["level"]] += 1
        for ext, count in ext_counts.items():
            format_counter[ext] += count

    lessons.sort(key=lambda item: (-item["priority_score"], item["series"], item["title"]))

    payload = {
        "mode": "local",
        "updatedAt": __import__("datetime").datetime.now().isoformat(),
        "stats": {
            "lesson_count": len(lessons),
            "pdf_count": format_counter.get("pdf", 0),
            "gp_count": format_counter.get("gp5", 0) + format_counter.get("gp", 0),
            "audio_count": format_counter.get("wav", 0) + format_counter.get("mp3", 0),
            "video_count": sum(1 for item in lessons if item["watch_url"]),
        },
        "series": [{"name": name, "count": count} for name, count in series_counter.most_common(18)],
        "tracks": [{"name": name, "count": count} for name, count in track_counter.most_common()],
        "levels": [{"name": name, "count": count} for name, count in level_counter.most_common()],
        "featured": lessons[:24],
        "lessons": lessons,
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    public_lessons = []
    for lesson in lessons:
        public_lessons.append({
            **lesson,
            "post_url": "",
            "folder_href": "",
            "video_local_url": "",
            "watch_url": lesson["video_embed_url"] or lesson["video_public_url"] or "",
            "pdf_links": [],
            "gp_links": [],
            "audio_links": [],
            "extra_links": [],
        })

    public_payload = {
        **payload,
        "mode": "public",
        "featured": public_lessons[:24],
        "lessons": public_lessons,
    }
    PUBLIC_OUT.write_text(json.dumps(public_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"lessons={len(lessons)}")
    print(f"wrote={OUT}")
    print(f"wrote={PUBLIC_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
