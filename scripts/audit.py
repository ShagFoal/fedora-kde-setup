#!/usr/bin/env python3
"""Read-only audit of the bootstrap repo and optional live Main configs."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    ".gitignore", "README.md", "PLASMA_MANUAL.md", "install.sh",
    "scripts/dependencies.py", "SHA256SUMS", "restore.json", "scripts/audit.py",
    "scripts/links.py", "scripts/migrate-projects-bind.sh", "scripts/restore.py", "tests/test_install.py",
    "tests/test_restore.py", "tests/test_links.py", "tests/test_migrate_projects.py",
}
LOCAL_PLASMA_IMAGES = {
    f"KDE-Themes Screenshot/{name}.png"
    for name in ("Colors", "Plasma Style", "Pointers", "WIndow Decorations", "icons")
}
RULES = {
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "provider token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16})\b",
    "Google OAuth secret": r"\bGOCSPX-[A-Za-z0-9_-]{20,}\b",
    "Google OAuth client ID": r"\b[0-9]{6,}-[a-z0-9_-]{10,}\.apps\.googleusercontent\.com\b",
    "Google access token": r"\bya29\.[A-Za-z0-9_-]{20,}\b",
    "JWT": r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b",
    "credential URL": r"://[^\s/:@]+:[^\s/@]+@",
    "credential assignment": r"(?i)^\s*(?:export\s+)?[\w]*(?:password|passwd|secret|token|api_key)[\w]*\s*[=:]\s*['\"]?[^'\"\s$]{8,}",
    "email address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "personal absolute path": r"/home/[a-z_][a-z0-9_-]*/",
}
issues = []
actual = set()
scanned_configs = 0

def scan(path, label):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        for name, pattern in RULES.items():
            if re.search(pattern, line):
                issues.append(f"{label}:{number}: {name} (value hidden)")

for path in ROOT.rglob("*"):
    relative = path.relative_to(ROOT).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        continue
    if path.is_symlink():
        issues.append(f"{relative}: unexpected symbolic link in bootstrap repo")
    elif relative in LOCAL_PLASMA_IMAGES and path.is_file():
        # Local Plasma reference images are outside the distributed bootstrap.
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                issues.append(f"{relative}: expected PNG image")
    elif path.is_file():
        actual.add(relative)
        if relative not in ALLOWED:
            issues.append(f"{relative}: unexpected file; contents hidden")
        else:
            scan(path, relative)
for name in sorted(ALLOWED - actual):
    issues.append(f"{name}: missing file")
if not issues:
    try:
        profile = json.loads((ROOT / "restore.json").read_text())
        if profile != {"remote": "gdrive", "repository_path": "backups/main-restic", "tag": "main-only", "source_directory": "Main"}:
            raise ValueError("unexpected restore profile")
        checked = set()
        for line in (ROOT / "SHA256SUMS").read_text().splitlines():
            expected, name = line.split("  ", 1)
            if name not in ALLOWED - {"SHA256SUMS"} or name in checked:
                raise ValueError("unexpected or duplicate manifest entry")
            checked.add(name)
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                issues.append(f"{name}: checksum mismatch")
        if checked != ALLOWED - {"SHA256SUMS"}:
            raise ValueError("incomplete manifest")
    except (ValueError, KeyError, OSError) as error:
        issues.append("Profile/integrity validation failed: " + type(error).__name__)
if len(sys.argv) > 1:
    if sys.argv[1:] != ["--configs"]:
        issues.append("Usage: audit.py [--configs]")
    elif not issues:
        sys.dont_write_bytecode = True
        from links import plan, LinkError
        try:
            for source, _ in plan():
                # Project trees and the private SSH directory are directory links.
                if source.is_file():
                    scan(source, "Main/" + source.relative_to(Path.home() / "Main").as_posix())
                    scanned_configs += 1
        except (LinkError, OSError, UnicodeError) as error:
            issues.append("Main config validation failed: " + type(error).__name__)
if issues:
    print("AUDIT FAILED")
    print("\n".join(issues))
    sys.exit(1)
print(f"AUDIT PASSED: {len(actual)} allowlisted bootstrap files; no recognizable secrets found.")
if sys.argv[1:]:
    print(f"Scanned {scanned_configs} Main config files. Directory links were checked without scanning their contents.")
