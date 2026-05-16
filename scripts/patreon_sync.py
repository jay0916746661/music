#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable

import browser_cookie3
import requests
from deep_translator import GoogleTranslator


CAMPAIGN_ID = "2293838"
API_URL = "https://www.patreon.com/api/posts"
DEFAULT_TARGET = Path("/Users/jimlin/Downloads/吉他練習")
TIMEOUT = 60

MODE_EXTENSIONS = {
    "core": {"pdf", "gp5", "gp", "jpg", "jpeg", "png"},
    "practice": {"pdf", "gp5", "gp", "jpg", "jpeg", "png", "wav", "mp3", "mp4"},
    "full": None,
}


@dataclass
class Attachment:
    post_id: str
    post_title: str
    post_url: str
    published_at: str
    filename: str
    ext: str
    size_bytes: int
    download_url: str
    embed_url: str | None
    post_description: str
    post_description_zh: str
    post_title_zh: str


@dataclass
class PreviewAttachment:
    post_id: str
    post_title: str
    post_url: str
    published_at: str
    filename: str
    ext: str
    size_bytes: int


def manifest_paths(target: Path) -> tuple[Path, Path]:
    manifest_dir = target / "_manifest"
    return manifest_dir / "manifest.json", manifest_dir / "manifest.csv"


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().strip(".")
    return value[:140] or fallback


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class TranslatorCache:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            self.cache = {}
        self.translator = GoogleTranslator(source="auto", target="zh-TW")

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if key in self.cache:
            return self.cache[key]

        trimmed = text[:3500]
        for attempt in range(1, 4):
            try:
                translated = self.translator.translate(trimmed)
                self.cache[key] = translated
                self.cache_path.write_text(
                    json.dumps(self.cache, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return translated
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    break
                time.sleep(attempt)
        return ""


def get_cookies():
    return browser_cookie3.edge(domain_name="patreon.com")


def get_json(url: str, *, cookies=None, params=None, retries: int = 5) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                cookies=cookies,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries:
                break
            time.sleep(min(8, attempt * 1.5))
    assert last_error is not None
    raise last_error


def fetch_posts() -> list[dict]:
    cookies = get_cookies()
    url = API_URL
    params = {
        "filter[campaign_id]": CAMPAIGN_ID,
        "sort": "-published_at",
        "page[count]": "50",
    }
    posts: list[dict] = []

    while url:
        payload = get_json(
            url,
            cookies=cookies,
            params=params if url == API_URL else None,
        )
        posts.extend(payload.get("data", []))
        url = payload.get("links", {}).get("next")
        params = None

    return posts


def extract_attachments(posts: Iterable[dict]) -> list[Attachment]:
    cookies = get_cookies()
    attachments: list[Attachment] = []
    translator = TranslatorCache(DEFAULT_TARGET / "_manifest" / "translation-cache.json")

    for post in posts:
        post_id = str(post["id"])
        title = post["attributes"].get("title") or f"Post {post_id}"
        post_url = post["attributes"].get("url") or f"https://www.patreon.com/posts/{post_id}"
        published_at = post["attributes"].get("published_at") or ""

        try:
            detail_payload = get_json(
                f"https://www.patreon.com/api/posts/{post_id}",
                cookies=cookies,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] skip post {post_id}: {exc}", file=sys.stderr)
            continue
        included = detail_payload.get("included", [])
        post_attrs = detail_payload["data"]["attributes"]
        embed = post_attrs.get("embed") or {}
        embed_url = embed.get("url")
        description = (
            strip_html(post_attrs.get("content"))
            or strip_html(embed.get("description"))
            or strip_html(post_attrs.get("teaser_text"))
        )
        title_zh = translator.translate(title) or title
        description_zh = translator.translate(description) if description else ""

        for item in included:
            if item.get("type") != "media":
                continue

            attrs = item.get("attributes") or {}
            if attrs.get("owner_relationship") != "attachment":
                continue

            filename = attrs.get("file_name") or f"{item['id']}"
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            attachments.append(
                Attachment(
                    post_id=post_id,
                    post_title=title,
                    post_url=post_url,
                    published_at=published_at,
                    filename=filename,
                    ext=ext,
                    size_bytes=int(attrs.get("size_bytes") or 0),
                    download_url=attrs.get("download_url") or "",
                    embed_url=embed_url,
                    post_description=description,
                    post_description_zh=description_zh,
                    post_title_zh=title_zh,
                )
            )

    return attachments


def extract_preview_attachments(posts: Iterable[dict]) -> list[PreviewAttachment]:
    items: list[PreviewAttachment] = []
    for post in posts:
        post_id = str(post["id"])
        title = post["attributes"].get("title") or f"Post {post_id}"
        post_url = post["attributes"].get("url") or f"https://www.patreon.com/posts/{post_id}"
        published_at = post["attributes"].get("published_at") or ""
        for meta in post["attributes"].get("attachments_preview_metadata", []) or []:
            filename = meta.get("file_name") or f"{post_id}"
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            items.append(
                PreviewAttachment(
                    post_id=post_id,
                    post_title=title,
                    post_url=post_url,
                    published_at=published_at,
                    filename=filename,
                    ext=ext,
                    size_bytes=int(meta.get("size_bytes") or 0),
                )
            )
    return items


def should_keep(attachment: Attachment, mode: str) -> bool:
    allowed = MODE_EXTENSIONS[mode]
    if allowed is None:
        return True
    return attachment.ext in allowed


def write_manifest(target: Path, attachments: list[Attachment]) -> None:
    manifest_json, manifest_csv = manifest_paths(target)
    manifest_dir = manifest_json.parent
    manifest_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "post_id": item.post_id,
            "post_title": item.post_title,
            "post_title_zh": item.post_title_zh,
            "post_url": item.post_url,
            "published_at": item.published_at,
            "post_description": item.post_description,
            "post_description_zh": item.post_description_zh,
            "filename": item.filename,
            "extension": item.ext,
            "size_bytes": item.size_bytes,
            "size_mb": round(item.size_bytes / 1024 / 1024, 2),
            "download_url": item.download_url,
            "embed_url": item.embed_url or "",
        }
        for item in attachments
    ]

    manifest_json.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with manifest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def load_manifest(target: Path) -> list[Attachment]:
    manifest_json, _ = manifest_paths(target)
    if not manifest_json.exists():
        return []
    rows = json.loads(manifest_json.read_text(encoding="utf-8"))
    attachments: list[Attachment] = []
    for row in rows:
        attachments.append(
            Attachment(
                post_id=str(row["post_id"]),
                post_title=row["post_title"],
                post_url=row["post_url"],
                published_at=row.get("published_at", ""),
                filename=row["filename"],
                ext=row.get("extension", ""),
                size_bytes=int(row.get("size_bytes") or 0),
                download_url=row.get("download_url", ""),
                embed_url=row.get("embed_url") or None,
                post_description=row.get("post_description", ""),
                post_description_zh=row.get("post_description_zh", ""),
                post_title_zh=row.get("post_title_zh", row["post_title"]),
            )
        )
    return attachments


def print_summary(attachments: list[Attachment]) -> None:
    counter = Counter()
    sizes = Counter()
    for item in attachments:
        counter[item.ext] += 1
        sizes[item.ext] += item.size_bytes

    print(f"attachments={len(attachments)}")
    print(f"size_gb={round(sum(sizes.values()) / 1024 / 1024 / 1024, 2)}")
    for ext, count in counter.most_common():
        print(f"{ext}\t{count}\t{round(sizes[ext] / 1024 / 1024 / 1024, 2)} GB")


def write_preview_manifest(target: Path, attachments: list[PreviewAttachment]) -> None:
    manifest_dir = target / "_manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "post_id": item.post_id,
            "post_title": item.post_title,
            "post_url": item.post_url,
            "published_at": item.published_at,
            "filename": item.filename,
            "extension": item.ext,
            "size_bytes": item.size_bytes,
            "size_mb": round(item.size_bytes / 1024 / 1024, 2),
        }
        for item in attachments
    ]
    (manifest_dir / "inventory.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (manifest_dir / "inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def write_post_catalog(target: Path, attachments: list[Attachment]) -> None:
    manifest_dir = target / "_manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    catalog: dict[str, dict] = {}
    for item in attachments:
        entry = catalog.setdefault(
            item.post_id,
            {
                "post_id": item.post_id,
                "post_title": item.post_title,
                "post_title_zh": item.post_title_zh,
                "post_url": item.post_url,
                "published_at": item.published_at,
                "post_description": item.post_description,
                "post_description_zh": item.post_description_zh,
                "video_url": item.embed_url or "",
                "files": [],
            },
        )
        entry["files"].append(
            {
                "filename": item.filename,
                "extension": item.ext,
                "size_bytes": item.size_bytes,
                "size_mb": round(item.size_bytes / 1024 / 1024, 2),
            }
        )

    rows = list(catalog.values())
    (manifest_dir / "posts-zh.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (manifest_dir / "posts-zh.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "post_id",
            "post_title",
            "post_title_zh",
            "post_url",
            "published_at",
            "post_description",
            "post_description_zh",
            "video_url",
            "file_count",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "post_id": row["post_id"],
                    "post_title": row["post_title"],
                    "post_title_zh": row["post_title_zh"],
                    "post_url": row["post_url"],
                    "published_at": row["published_at"],
                    "post_description": row["post_description"],
                    "post_description_zh": row["post_description_zh"],
                    "video_url": row["video_url"],
                    "file_count": len(row["files"]),
                }
            )


def build_post_meta(target: Path, attachments: list[Attachment]) -> dict[str, dict]:
    post_meta: dict[str, dict] = {}
    for item in attachments:
        post_dir = target / sanitize_filename(item.post_title)
        post_meta.setdefault(
            item.post_id,
            {
                "post_id": item.post_id,
                "title_en": item.post_title,
                "title_zh": item.post_title_zh,
                "post_url": item.post_url,
                "published_at": item.published_at,
                "description_en": item.post_description,
                "description_zh": item.post_description_zh,
                "video_url": item.embed_url or "",
                "files": [],
                "folder": str(post_dir),
            },
        )
        post_meta[item.post_id]["files"].append(
            {
                "filename": item.filename,
                "path": str(post_dir / sanitize_filename(item.filename, fallback=f"{item.post_id}.{item.ext or 'bin'}")),
                "extension": item.ext,
                "size_bytes": item.size_bytes,
            }
        )
    return post_meta


def write_post_readmes(post_meta: dict[str, dict]) -> None:
    for meta in post_meta.values():
        folder = Path(meta["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "_post.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [
            f"# {meta['title_zh'] or meta['title_en']}",
            "",
            f"- English title: {meta['title_en']}",
            f"- Patreon: {meta['post_url']}",
            f"- Published: {meta['published_at']}",
        ]
        if meta["video_url"]:
            lines.append(f"- Video: {meta['video_url']}")
        if meta.get("video_file"):
            lines.append(f"- Video file: {meta['video_file']}")
        if meta.get("video_status"):
            lines.append(f"- Video status: {meta['video_status']}")
        if meta.get("video_error"):
            lines.append(f"- Video note: {meta['video_error']}")
        lines.extend(
            [
                "",
                "## 中文說明",
                meta["description_zh"] or "暫無說明。",
                "",
                "## Original Description",
                meta["description_en"] or "No description.",
                "",
                "## Files",
            ]
        )
        for file_item in meta["files"]:
            lines.append(f"- {file_item['filename']}")
        (folder / "README_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def download_videos(target: Path, attachments: list[Attachment]) -> None:
    yt_dlp = shutil.which("yt-dlp") or shutil.which(str(Path.home() / ".local/bin/yt-dlp"))
    if not yt_dlp:
        raise RuntimeError("yt-dlp is not installed")

    post_meta = build_post_meta(target, attachments)
    for index, meta in enumerate(post_meta.values(), start=1):
        video_url = (meta.get("video_url") or "").strip()
        if not video_url:
            continue
        folder = Path(meta["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / "video.mp4").exists():
            existing = folder / "video.mp4"
            meta["video_file"] = str(existing)
            meta["video_status"] = "downloaded"
            print(f"[skip-video {index}/{len(post_meta)}] {meta['title_en']}")
            continue
        if any(folder.glob("video.*")):
            existing = next(folder.glob("video.*"))
            meta["video_file"] = str(existing)
            meta["video_status"] = "downloaded" if existing.suffix.lower() == ".mp4" else "downloaded-non-mp4"
            print(f"[skip-video {index}/{len(post_meta)}] {meta['title_en']}")
            continue

        outtmpl = str(folder / "video.%(ext)s")
        print(f"[down-video {index}/{len(post_meta)}] {meta['title_en']} -> {video_url}")
        result = subprocess.run(
            [
                yt_dlp,
                "--no-playlist",
                "--cookies-from-browser",
                "edge",
                "--recode-video",
                "mp4",
                "-o",
                outtmpl,
                video_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            meta["video_status"] = "link-only"
            last_line = ""
            for line in reversed(result.stdout.splitlines()):
                if line.strip():
                    last_line = line.strip()
                    break
            meta["video_error"] = last_line or "download failed"
            print(f"[warn-video] {meta['title_en']} failed\n{result.stdout}", file=sys.stderr)
            continue
        video_files = sorted(folder.glob("video.*"))
        if video_files:
            meta["video_file"] = str(video_files[0])
            meta["video_status"] = "downloaded"
        else:
            meta["video_status"] = "link-only"

    write_post_readmes(post_meta)


def download_attachments(target: Path, attachments: list[Attachment], mode: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.cookies = get_cookies()

    kept = [item for item in attachments if should_keep(item, mode)]
    write_manifest(target, kept)
    post_meta = build_post_meta(target, kept)

    for index, item in enumerate(kept, start=1):
        post_dir = target / sanitize_filename(item.post_title)
        post_dir.mkdir(parents=True, exist_ok=True)
        output = post_dir / sanitize_filename(item.filename, fallback=f"{item.post_id}.{item.ext or 'bin'}")

        if output.exists() and output.stat().st_size == item.size_bytes and item.size_bytes > 0:
            print(f"[skip {index}/{len(kept)}] {output.name}")
            continue

        success = False
        for attempt in range(1, 5):
            try:
                print(f"[down {index}/{len(kept)}] {item.post_title} -> {output.name} (try {attempt}/4)")
                with session.get(item.download_url, stream=True, timeout=TIMEOUT) as response:
                    response.raise_for_status()
                    with output.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 512):
                            if chunk:
                                handle.write(chunk)
                success = True
                break
            except Exception as exc:  # noqa: BLE001
                if output.exists() and output.stat().st_size == 0:
                    output.unlink(missing_ok=True)
                if attempt == 4:
                    print(f"[warn-file] {item.post_title} -> {output.name} failed: {exc}", file=sys.stderr)
                else:
                    time.sleep(min(10, attempt * 2))
        if not success:
            continue
    write_post_readmes(post_meta)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Patreon practice materials from Mauricio Murua.")
    parser.add_argument("command", choices=["inventory", "metadata", "download", "videos"])
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--mode", choices=sorted(MODE_EXTENSIONS.keys()), default="core")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    target = Path(args.target).expanduser()
    manifest_attachments = load_manifest(target)

    posts = None

    if args.command == "inventory":
        posts = fetch_posts()
        attachments = extract_preview_attachments(posts)
        target.mkdir(parents=True, exist_ok=True)
        write_preview_manifest(target, attachments)
        print_summary(attachments)
        return 0

    if manifest_attachments and args.command in {"download", "videos"}:
        attachments = manifest_attachments
    else:
        posts = fetch_posts()
        attachments = extract_attachments(posts)

    if args.command == "metadata":
        target.mkdir(parents=True, exist_ok=True)
        write_manifest(target, attachments)
        write_post_catalog(target, attachments)
        print_summary(attachments)
        return 0
    if args.command == "videos":
        target.mkdir(parents=True, exist_ok=True)
        download_videos(target, attachments)
        return 0
    download_attachments(target, attachments, args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
