#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path("/Volumes/T7 藍/吉他練習")
MANIFEST = ROOT / "_manifest" / "manifest.json"
PROJECT_ROOT = Path("/Users/jimlin/Documents/Codex/2026-04-25/dj")


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().strip(".")
    return value[:140] or fallback


def to_youtube_embed(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"(?:youtu\.be/|youtube\.com/watch\?v=)([^&?/]+)", url)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
    return ""


def infer_level(title: str) -> tuple[str, int]:
    if "🟥" in title or "Master" in title:
        return "master", 4
    if "🟨" in title or "Advanced" in title:
        return "advanced", 3
    if "🟩" in title or "Intermediate" in title:
        return "intermediate", 2
    if "🟦" in title or "Pathfinder" in title:
        return "foundation", 1
    if any(k in title for k in ["Exercise", "Omega", "Circle", "Etude"]):
        return "foundation", 1
    return "core", 2


def infer_track(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["twister", "string skipping", "whammy", "metal"]):
        return "technique-riff"
    if any(k in t for k in ["peaceful", "tsubasa", "kintsugi", "komorebi", "evenings", "opus", "wings", "extensions", "chord melody"]):
        return "harmony-touch"
    if any(k in t for k in ["blues", "srv", "gary moore", "lick"]):
        return "blues-language"
    if any(k in t for k in ["jazz", "251", "451", "misty", "fly me", "smooth", "standard"]):
        return "jazz-voicing"
    if any(k in t for k in ["mixolyd", "lydian", "phrygian", "harmonic", "circle", "arpeggio", "omega", "exercise", "etude", "mode", "mystery"]):
        return "fretboard-theory"
    return "song-study"


def infer_series(title: str) -> str:
    patterns = [
        "Peaceful", "Twister", "Exercise", "Crystal", "Extensions", "Etude", "Jazz",
        "Blues", "Kintsugi", "Circle", "Smooth", "Lick", "Tsubasa", "Wings",
        "Omega", "Evenings", "Interchange", "Melodic", "Komorebi", "Opus",
    ]
    for pattern in patterns:
        if title.startswith(pattern):
            return pattern
    return title.split()[0]


def priority_score(title: str, level_rank: int, track: str, files: list[dict]) -> int:
    score = 50
    if track == "fretboard-theory":
        score += 18
    if track == "harmony-touch":
        score += 16
    if track == "blues-language":
        score += 12
    if track == "jazz-voicing":
        score += 10
    if track == "technique-riff":
        score += 4

    if level_rank == 1:
        score += 20
    elif level_rank == 2:
        score += 12
    elif level_rank == 3:
        score += 3
    else:
        score -= 6

    ext_counts = Counter(f["extension"] for f in files)
    if ext_counts.get("gp5") or ext_counts.get("gp"):
        score += 8
    if ext_counts.get("pdf"):
        score += 6
    if ext_counts.get("wav") or ext_counts.get("mp3"):
        score += 6
    if ext_counts.get("mp4"):
        score += 4
    if ext_counts.get("zip"):
        score += 2

    if any(word in title.lower() for word in ["circle", "omega", "exercise", "extension", "tsubasa", "peaceful", "mixolyd", "lydian", "phrygian", "blues"]):
        score += 10
    return score


TRACK_INFO = {
    "fretboard-theory": {
        "label": "指板 / 理論基礎",
        "summary": "先把音階、和弦功能、位置感打穩，這條最適合當日常主線。",
        "extensions": [
            "把同一個句型轉去 3 個調",
            "60 / 80 / 100 bpm 三段節拍器練習",
            "把 GP5 裡的主題句抄到 MuseScore 或 Logic MIDI",
        ],
    },
    "harmony-touch": {
        "label": "和聲 / 觸弦 / 氣氛",
        "summary": "這條最接近你想做的 Peaceful 風格，適合練和弦進行、音色和右手控制。",
        "extensions": [
            "同一進行做 clean / reverb / delay 三種音色",
            "只留下上方旋律音，改寫成 4 小節變奏",
            "把和弦名稱寫出來，再做一版慢速錄音",
        ],
    },
    "blues-language": {
        "label": "Blues 樂句語言",
        "summary": "拿來建立即興語感和收尾句，很適合當每日 10 到 20 分鐘 vocabulary 練習。",
        "extensions": [
            "從每首裡抓 2 個句尾做 call-and-response",
            "換三個節奏版本：原版、延後、切分",
            "跟 backing track 錄 2 輪 12 小節",
        ],
    },
    "jazz-voicing": {
        "label": "Jazz 和聲 / Voicing",
        "summary": "偏和弦色彩與標準進行，適合搭配 MuseScore 做記譜整理。",
        "extensions": [
            "把 251 / 451 進行移到 4 個 key",
            "每個 voicing 都找最上方旋律音",
            "丟進 Logic 做 Rhodes + guitar 的 8 小節 loop",
        ],
    },
    "technique-riff": {
        "label": "技巧 / Riff / 速度",
        "summary": "這條適合當加強包，不建議一開始就拿它當唯一主線。",
        "extensions": [
            "只練右手節奏和乾淨 mute",
            "分成 2 小節 chunk loop",
            "錄一版乾淨速度、一版目標速度的 80%",
        ],
    },
    "song-study": {
        "label": "作品 / 單曲研究",
        "summary": "適合拿來當週目標，練完整結構和表現。",
        "extensions": [
            "拆成 intro / main phrase / ending 三段",
            "做一版更簡化的練習版編排",
            "用自己的 tone 再錄一次",
        ],
    },
}

SKILL_TREE = {
    "01_節奏與基礎": {
        "tracks": ["fretboard-theory"],
        "summary": "先點亮拍點、位置感、調式與基本練習曲，這裡是主線底盤。",
    },
    "02_和聲與氣氛": {
        "tracks": ["harmony-touch"],
        "summary": "Peaceful / Tsubasa / Extensions 這條線，專注和弦進行、觸弦與空氣感。",
    },
    "03_Blues語言": {
        "tracks": ["blues-language"],
        "summary": "建立 lick vocabulary、句尾、推拉拍與藍調語感。",
    },
    "04_Jazz和聲": {
        "tracks": ["jazz-voicing"],
        "summary": "251、451、voicing、standard 類教材都放在這裡。",
    },
    "05_技巧與Riff": {
        "tracks": ["technique-riff"],
        "summary": "速度、riff、string skipping、twister 類重手感內容。",
    },
    "06_作品與應用": {
        "tracks": ["song-study"],
        "summary": "完整曲目與單曲研究，適合做週目標或錄音任務。",
    },
}


def build_catalog(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["post_title"]].append(row)

    entries = []
    for title, files in grouped.items():
        level, rank = infer_level(title)
        track = infer_track(title)
        series = infer_series(title)
        folder = ROOT / sanitize_filename(title)
        local_video = ""
        preferred_local = folder / "video.mp4"
        if preferred_local.exists():
            local_video = str(preferred_local)
        else:
            mp4_files = sorted(folder.glob("*.mp4"))
            if mp4_files:
                local_video = str(mp4_files[0])
        ext_counts = Counter(f["extension"] for f in files)
        score = priority_score(title, rank, track, files)
        remote_video = next((f.get("embed_url") for f in files if f.get("embed_url")), "")
        stream_video_url = next(
            (f.get("download_url") for f in files if f.get("extension") == "mp4" and f.get("download_url")),
            "",
        )
        embed_video_url = to_youtube_embed(remote_video)
        entries.append(
            {
                "title": title,
                "series": series,
                "track": track,
                "track_label": TRACK_INFO[track]["label"],
                "level": level,
                "level_rank": rank,
                "priority_score": score,
                "priority_band": "now" if score >= 86 else "next" if score >= 72 else "later",
                "summary": TRACK_INFO[track]["summary"],
                "extensions": TRACK_INFO[track]["extensions"],
                "file_count": len(files),
                "extensions_available": dict(ext_counts),
                "folder": str(folder),
                "files": sorted({f["filename"] for f in files}),
                "local_video": local_video,
                "stream_video_url": stream_video_url,
                "video_url": remote_video,
                "embed_video_url": embed_video_url,
                "preferred_watch_url": stream_video_url or embed_video_url or remote_video or (f"file://{local_video}" if local_video else ""),
                "post_url": files[0].get("post_url", ""),
                "description_zh": files[0].get("post_description_zh", ""),
            }
        )
    entries.sort(key=lambda item: (-item["priority_score"], item["level_rank"], item["title"]))
    return entries


def write_outputs(entries: list[dict]) -> None:
    manifest_dir = ROOT / "_manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    (manifest_dir / "practice-catalog.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (manifest_dir / "practice-catalog.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["title", "series", "track_label", "level", "priority_score", "priority_band", "file_count", "folder", "video_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow({key: entry[key] for key in fieldnames})

    curated_counts = {
        "fretboard-theory": 5,
        "harmony-touch": 5,
        "blues-language": 3,
        "jazz-voicing": 3,
        "technique-riff": 2,
        "song-study": 2,
    }
    now = []
    for track, limit in curated_counts.items():
        now.extend([e for e in entries if e["track"] == track][:limit])
    seen = set()
    now = [e for e in now if not (e["title"] in seen or seen.add(e["title"]))]
    next_up = [e for e in entries if e["priority_band"] == "next"][:18]
    tracks = defaultdict(list)
    for entry in entries:
        tracks[entry["track"]].append(entry)

    lines = [
        "# 吉他練習索引",
        "",
        "這份索引會把目前已整理出的 Patreon 教材，分成可直接開練的優先順序、學習軌道與延伸練習。",
        "",
        "## 現在最值得先練",
    ]
    for entry in now:
        lines.extend([
            f"### {entry['title']}",
            f"- 軌道：{entry['track_label']}",
            f"- 難度：{entry['level']}",
            f"- 檔案數：{entry['file_count']}",
            f"- 資料夾：[開啟資料夾]({entry['folder']})",
        ])
        if entry["video_url"]:
            lines.append(f"- 影片連結：{entry['video_url']}")
        if entry["description_zh"]:
            lines.append(f"- 說明：{entry['description_zh'][:140]}...")
        lines.append("- 延伸練習：")
        for suggestion in entry["extensions"]:
            lines.append(f"  - {suggestion}")
        lines.append("")

    lines.extend(["## 第二梯隊", ""])
    for entry in next_up:
        lines.append(f"- {entry['title']}｜{entry['track_label']}｜{entry['level']}｜[資料夾]({entry['folder']})")

    lines.extend(["", "## 學習軌道", ""])
    for track, info in TRACK_INFO.items():
        lines.append(f"### {info['label']}")
        lines.append(info["summary"])
        lines.append("")
        for entry in tracks[track][:12]:
            lines.append(f"- {entry['title']}｜{entry['level']}｜[資料夾]({entry['folder']})")
        lines.append("")
        lines.append("延伸練習：")
        for suggestion in info["extensions"]:
            lines.append(f"- {suggestion}")
        lines.append("")

    lines.extend([
        "## 建議練習節奏",
        "",
        "1. 每天先從 `現在最值得先練` 裡選 1 個主題。",
        "2. 再從不同軌道補 1 個短練習，避免只用同一種手感。",
        "3. 每完成一個主題，就把其中 2 小節做成自己的變奏或轉調版。",
        "",
    ])

    (manifest_dir / "practice-roadmap-zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    hub_dir = ROOT / "00_練習索引"
    hub_dir.mkdir(parents=True, exist_ok=True)
    (hub_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_skill_tree(entries)
    write_platform_snapshot(entries, now, next_up)


def safe_link_name(entry: dict) -> str:
    return sanitize_filename(f"{entry['priority_band']}_{entry['level']}_{entry['title']}")


def write_skill_tree(entries: list[dict]) -> None:
    tree_dir = ROOT / "01_技能樹分類"
    tree_dir.mkdir(parents=True, exist_ok=True)

    top_lines = [
        "# 吉他技能樹分類",
        "",
        "這裡不是搬動原始教材，而是用技能樹的方式建立入口。每個捷徑都會連回原始教材資料夾。",
        "",
        "## 技能樹主幹",
    ]

    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry["track"]].append(entry)

    for folder_name, info in SKILL_TREE.items():
        branch_dir = tree_dir / folder_name
        branch_dir.mkdir(parents=True, exist_ok=True)
        branch_lines = [
            f"# {folder_name}",
            "",
            info["summary"],
            "",
            "## 現在先練",
        ]
        branch_entries = []
        for track in info["tracks"]:
            branch_entries.extend(grouped[track])

        now_entries = [e for e in branch_entries if e["priority_band"] == "now"][:18]
        next_entries = [e for e in branch_entries if e["priority_band"] == "next"][:18]
        later_entries = [e for e in branch_entries if e["priority_band"] == "later"][:24]

        for label in ["現在先練", "下一步", "之後擴充"]:
            (branch_dir / label).mkdir(parents=True, exist_ok=True)

        for bucket_name, bucket_entries in [
            ("現在先練", now_entries),
            ("下一步", next_entries),
            ("之後擴充", later_entries),
        ]:
            target_dir = branch_dir / bucket_name
            for entry in bucket_entries:
                link_path = target_dir / safe_link_name(entry)
                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()
                os.symlink(entry["folder"], link_path)

            if bucket_name != "現在先練":
                branch_lines.append(f"## {bucket_name}")
            for entry in bucket_entries:
                branch_lines.append(f"- {entry['title']}｜{entry['level']}｜[原始資料夾]({entry['folder']})")
                if entry["video_url"]:
                    branch_lines.append(f"  - 影片：{entry['video_url']}")
                for suggestion in entry["extensions"][:2]:
                    branch_lines.append(f"  - 延伸：{suggestion}")
            branch_lines.append("")

        (branch_dir / "README.md").write_text("\n".join(branch_lines) + "\n", encoding="utf-8")
        top_lines.extend(
            [
                f"### {folder_name}",
                info["summary"],
                f"- [打開分類]({branch_dir})",
                "",
            ]
        )

    (tree_dir / "README.md").write_text("\n".join(top_lines) + "\n", encoding="utf-8")


def write_platform_snapshot(entries: list[dict], now: list[dict], next_up: list[dict]) -> None:
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    branch_cards = []
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry["track"]].append(entry)

    def public_item(item: dict) -> dict:
        watch_url = item["embed_video_url"] or item["video_url"] or ""
        return {
            "title": item["title"],
            "series": item["series"],
            "track": item["track"],
            "track_label": item["track_label"],
            "level": item["level"],
            "priority_band": item["priority_band"],
            "summary": item["summary"],
            "extensions": item["extensions"],
            "post_url": item["post_url"],
            "folder": item["post_url"],
            "video_url": item["video_url"],
            "embed_video_url": item["embed_video_url"],
            "preferred_watch_url": watch_url,
            "local_video": "",
            "stream_video_url": "",
        }

    for folder_name, info in SKILL_TREE.items():
        branch_entries = []
        for track in info["tracks"]:
            branch_entries.extend(grouped[track])
        branch_cards.append(
            {
                "id": folder_name,
                "title": folder_name,
                "summary": info["summary"],
                "current": [
                    {
                        "title": public_item(item)["title"],
                        "level": public_item(item)["level"],
                        "folder": public_item(item)["folder"],
                        "local_video": public_item(item)["local_video"],
                        "stream_video_url": public_item(item)["stream_video_url"],
                        "video_url": public_item(item)["video_url"],
                        "embed_video_url": public_item(item)["embed_video_url"],
                        "preferred_watch_url": public_item(item)["preferred_watch_url"],
                    }
                    for item in branch_entries[:6]
                ],
            }
        )

    payload = {
        "updatedAt": __import__("datetime").datetime.now().isoformat(),
        "hero": {
            "title": "下載中的教材已同步成技能樹",
            "copy": "平台現在可以讀到你外接碟裡的練習樹，先練什麼、接著練什麼，都有清楚入口。",
        },
        "now": [public_item(item) for item in now[:12]],
        "next": [public_item(item) for item in next_up[:12]],
        "branches": branch_cards,
    }
    (data_dir / "skill-tree-snapshot.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = build_catalog(rows)
    write_outputs(entries)
    print(f"titles={len(entries)}")
    print("wrote practice hub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
