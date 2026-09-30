"""Extract YouTube video transcripts to plans/references/ as markdown.

Usage:
    fetch_transcript.py <url1> [<url2> ...]
    fetch_transcript.py --force <url>      # overwrite existing files
    fetch_transcript.py --lang fr <url>    # prefer French captions (default: en)

Writes one markdown file per video to plans/references/, named:
    {channel-slug}-{title-slug}-{videoId}.md

Creates plans/references/INDEX.md skeleton if missing.

Requires: youtube-transcript-api>=1.2,<2.0

Exit codes:
    0 = at least one video processed (new write or skip)
    1 = no video could be processed (all failed)
    2 = bad CLI usage / missing dependency
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# Force UTF-8 stdout/stderr — Windows shells default to cp1252 and crash on accented chars.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )
except ImportError:
    print(
        "ERROR: missing dependency 'youtube-transcript-api'. Install with:\n"
        '  .venv\\Scripts\\pip.exe install "youtube-transcript-api>=1.2,<2.0"',
        file=sys.stderr,
    )
    sys.exit(2)


# parents[0]=scripts, [1]=extract-transcript, [2]=skills, [3]=.claude, [4]=repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
REFS_DIR = REPO_ROOT / "plans" / "references"
INDEX_FILE = REFS_DIR / "INDEX.md"

LANGUAGE_CODES = {
    "en": ["en", "en-US", "en-GB"],
    "fr": ["fr", "fr-FR"],
}


def preferred_languages(lang: str) -> list[str]:
    """Caption language codes to try, the requested language first, then the other one."""
    others = [code for key, codes in LANGUAGE_CODES.items() if key != lang for code in codes]
    return LANGUAGE_CODES[lang] + others


PARAGRAPH_GAP_S = 2.0  # break paragraph when silence between segments > this
MAX_PARAGRAPH_S = 45.0  # force break after this many seconds even without gap

VIDEO_ID_RE = re.compile(r"(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})")
BARE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Pull the 11-char videoId from a URL or return the URL itself if it's a bare ID."""
    m = VIDEO_ID_RE.search(url)
    if m:
        return m.group(1)
    if BARE_ID_RE.match(url.strip()):
        return url.strip()
    return None


def slugify(text: str, max_len: int = 60) -> str:
    text = text.lower()
    # Replace common French diacritics before stripping non-ASCII
    replacements = str.maketrans(
        "àáâäãåèéêëìíîïòóôöõùúûüñçÿ",  # fr-ok: accent-stripping table
        "aaaaaaeeeeiiiiooooouuuuncy",
    )
    text = text.translate(replacements)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len].rstrip("-") or "untitled"


def fetch_oembed(video_id: str) -> dict[str, str]:
    """Return {title, author_name, author_url} via YouTube's public oEmbed endpoint."""
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  warn: oEmbed failed ({e}), using videoId for naming", file=sys.stderr)
        return {"title": video_id, "author_name": "unknown", "author_url": ""}
    return {
        "title": data.get("title", video_id),
        "author_name": data.get("author_name", "unknown"),
        "author_url": data.get("author_url", ""),
    }


def fetch_transcript(api: YouTubeTranscriptApi, video_id: str, lang: str = "en"):
    """Return (snippets, language_code, is_generated).

    Tries `lang`, then the other supported language, then any transcript
    auto-translated to `lang`.
    """
    transcript_list = api.list(video_id)
    languages = preferred_languages(lang)

    transcript = None
    for code in languages:
        try:
            transcript = transcript_list.find_transcript([code])
            break
        except NoTranscriptFound:
            continue

    if transcript is None:
        # Take any available one, attempt translation to `lang`
        for t in transcript_list:
            transcript = t
            break
        if transcript is None:
            raise NoTranscriptFound(video_id, languages, transcript_list)
        if transcript.is_translatable:
            with contextlib.suppress(Exception):
                transcript = transcript.translate(lang)

    fetched = transcript.fetch()
    return fetched.snippets, fetched.language_code, fetched.is_generated


def snippets_to_paragraphs(snippets) -> list[str]:
    """Group transcript snippets into readable paragraphs based on timing gaps.

    `snippets` is an iterable of FetchedTranscriptSnippet objects with
    `.text`, `.start`, `.duration` attributes.
    """
    paragraphs: list[list[str]] = []
    current: list[str] = []
    paragraph_start: float | None = None
    last_end: float = 0.0

    for snip in snippets:
        text = snip.text.replace("\n", " ").strip()
        # Skip music/sound markers and empty snippets
        if not text or (text.startswith("[") and text.endswith("]")):
            continue

        start = snip.start
        duration = snip.duration

        if paragraph_start is None:
            paragraph_start = start

        gap = start - last_end if last_end else 0
        elapsed = start - paragraph_start

        if (gap > PARAGRAPH_GAP_S or elapsed > MAX_PARAGRAPH_S) and current:
            paragraphs.append(current)
            current = []
            paragraph_start = start

        current.append(text)
        last_end = start + duration

    if current:
        paragraphs.append(current)

    return [" ".join(p) for p in paragraphs]


def write_transcript_file(
    video_id: str,
    url: str,
    meta: dict[str, str],
    paragraphs: list[str],
    language: str,
    is_generated: bool,
    force: bool,
) -> tuple[Path, str]:
    """Write the transcript file. Returns (path, status) where status is 'wrote' or 'skipped'."""
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    channel_slug = slugify(meta["author_name"], 30)
    title_slug = slugify(meta["title"], 60)
    filename = f"{channel_slug}-{title_slug}-{video_id}.md"
    path = REFS_DIR / filename

    if path.exists() and not force:
        print(f"  skip: {path.name} already exists (use --force to overwrite)")
        return path, "skipped"

    captions_type = "auto" if is_generated else "manual"
    safe_title = meta["title"].replace('"', "'")

    lines = [
        "---",
        "source: youtube",
        f"url: {url}",
        f"videoId: {video_id}",
        f"channel: {meta['author_name']}",
        f"channel_url: {meta['author_url']}",
        f'title: "{safe_title}"',
        f"language: {language}",
        f"captions_type: {captions_type}",
        f"extracted_at: {date.today().isoformat()}",
        "---",
        "",
        f"# {meta['title']}",
        "",
    ]
    if captions_type == "auto":
        lines.append(
            "> ⚠️ **YouTube auto-captions**: no punctuation, technical jargon sometimes "
            "mis-transcribed, precise figures (paces, %, durations) to be checked against the "
            "video before use."
        )
        lines.append("")

    lines.extend(paragraphs)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"  ok: wrote {path.name} "
        f"({len(paragraphs)} paragraphs, lang={language}, type={captions_type})"
    )
    return path, "wrote"


def ensure_index_file() -> None:
    if INDEX_FILE.exists():
        return
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    skeleton = (
        "# Reference corpus — coaching methodologies\n"
        "\n"
        "> Read at the start of each session by the `entraineur` skill. The **pillars** below "
        "are distilled by Claude after extracting each transcript.\n"
        "> To dig into a methodology: open the matching transcript file.\n"
        "\n"
        "---\n"
        "\n"
        "## Marathon\n"
        "\n"
        "_(no reference indexed yet)_\n"
        "\n"
        "## Ultra / trail\n"
        "\n"
        "_(no reference indexed yet)_\n"
        "\n"
        "## Recovery / injury\n"
        "\n"
        "_(no reference indexed yet)_\n"
        "\n"
        "## Nutrition\n"
        "\n"
        "_(no reference indexed yet)_\n"
        "\n"
        "## Strength / prevention\n"
        "\n"
        "_(no reference indexed yet)_\n"
    )
    INDEX_FILE.write_text(skeleton, encoding="utf-8")
    print(f"  ok: created {INDEX_FILE.relative_to(REPO_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract YouTube transcript(s) to plans/references/"
    )
    parser.add_argument("urls", nargs="+", help="One or more YouTube URLs (or bare 11-char IDs)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing transcript files")
    parser.add_argument(
        "--lang",
        choices=sorted(LANGUAGE_CODES),
        default="en",
        help="Preferred caption language (default: en); falls back to the other one",
    )
    args = parser.parse_args()

    ensure_index_file()
    api = YouTubeTranscriptApi()

    success = 0
    for url in args.urls:
        print(f"\n[{url}]")
        video_id = extract_video_id(url)
        if not video_id:
            print(f"  error: could not extract videoId from {url}", file=sys.stderr)
            continue
        try:
            meta = fetch_oembed(video_id)
            snippets, language, is_generated = fetch_transcript(api, video_id, args.lang)
            paragraphs = snippets_to_paragraphs(snippets)
            if not paragraphs:
                print("  error: transcript is empty after filtering", file=sys.stderr)
                continue
            write_transcript_file(
                video_id, url, meta, paragraphs, language, is_generated, args.force
            )
            success += 1
        except TranscriptsDisabled:
            print("  error: transcripts disabled for this video", file=sys.stderr)
        except NoTranscriptFound:
            print("  error: no transcript available in any language", file=sys.stderr)
        except VideoUnavailable:
            print("  error: video unavailable (private, deleted, region-blocked)", file=sys.stderr)
        except Exception as e:
            print(f"  error: {type(e).__name__}: {e}", file=sys.stderr)

    if success == 0:
        return 1

    print(
        f"\n[done] {success}/{len(args.urls)} video(s) processed.\n"
        f"Next step (Claude): read the new transcript file(s), distill 5-8 pillars, "
        f"propose an INDEX.md entry, wait for athlete validation."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
