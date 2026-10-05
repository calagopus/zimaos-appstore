#!/usr/bin/env python3
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_NOTES = 700

IMAGE_RE = re.compile(
    r"(?P<prefix>image:\s*ghcr\.io/calagopus/panel:)"
    r"(?P<version>\d+(?:\.\d+)*)(?P<variant>-[A-Za-z0-9.-]+?)?(?:@sha256:[0-9a-f]{64})?(?P<eol>[ \t]*$)",
    re.M,
)

# Keys inside the top-level x-casaos block are indented by two spaces.
VERSION_RE = re.compile(r"^  version:.*$", re.M)
UPDATE_AT_RE = re.compile(r"^  update_at:.*$", re.M)
RELEASE_NOTES_RE = re.compile(r"^  release_notes:\n.*?(?=^  \S|^\S|\Z)", re.M | re.S)


def digest(ref: str) -> str:
    out = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{.Manifest.Digest}}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", out):
        sys.exit(f"unexpected digest for {ref}: {out!r}")
    return out


def format_notes(body: str, version: str) -> str:
    lines = []
    for line in body.replace("\r", "").splitlines():
        line = line.rstrip()
        if line.startswith("**Full Changelog**"):
            continue
        line = re.sub(r"^#+\s*", "", line)
        lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    link = f"https://github.com/calagopus/panel/releases/tag/release-{version}"
    if not text:
        return f"See {link}"
    if len(text) > MAX_NOTES:
        text = text[:MAX_NOTES].rsplit("\n", 1)[0].rstrip() + f"\n…\nFull notes: {link}"
    return text


def yaml_block(text: str) -> str:
    body = "\n".join(("      " + l) if l else "" for l in text.split("\n"))
    return f"  release_notes:\n    en_US: |-\n{body}\n"


def sub_once(pattern: re.Pattern, repl: str, text: str, what: str, path: Path) -> str:
    text, n = pattern.subn(lambda _: repl, text, count=1)
    if n != 1:
        sys.exit(f"no {what} key in x-casaos of {path}")
    return text


def main() -> None:
    version, notes_file = sys.argv[1], sys.argv[2]
    notes = format_notes(Path(notes_file).read_text(), version)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changed = []

    for compose in sorted(Path("Apps").glob("*/docker-compose.yml")):
        text = compose.read_text()
        m = IMAGE_RE.search(text)
        if not m or m["version"] == version:
            continue

        tag = f"{version}{m['variant'] or ''}"
        ref = f"ghcr.io/calagopus/panel:{tag}"
        text = text[: m.start()] + f"{m['prefix']}{tag}@{digest(ref)}{m['eol']}" + text[m.end():]
        text = sub_once(VERSION_RE, f'  version: "{version}"', text, "version:", compose)
        text = sub_once(UPDATE_AT_RE, f'  update_at: "{today}"', text, "update_at:", compose)
        text = sub_once(RELEASE_NOTES_RE, yaml_block(notes), text, "release_notes:", compose)
        compose.write_text(text)
        changed.append(compose.parent.name)

    print("\n".join(changed))


main()
