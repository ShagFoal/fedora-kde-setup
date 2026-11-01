#!/usr/bin/env python3
"""Read-only audit of the bootstrap repo and optional live Main configs."""
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    ".gitignore", "README.md", "PLASMA_MANUAL.md", "install.sh",
    "dependencies.tsv", "SHA256SUMS", "restore.json", "scripts/audit.py",
    "scripts/links.py", "scripts/restore.py", "tests/test_install.py",
    "tests/test_restore.py", "tests/test_links.py",
}
RULES = {
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "provider token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16})\b",
    "JWT": r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b",
    "credential URL": r"://[^\s/:@]+:[^\s/@]+@",
    "credential assignment": r"(?i)^\s*(?:export\s+)?[\w]*(?:password|passwd|secret|token|api_key)[\w]*\s*[=:]\s*['\"]?[^'\"\s$]{8,}",
    "email address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "personal absolute path": r"/home/[a-z_][a-z0-9_-]*/",
}
issues = []
actual = set()

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
        assert profile == {"remote": "gdrive", "repository_path": "backups/main-restic", "tag": "main-only", "source_directory": "Main"}
        checked = set()
        for line in (ROOT / "SHA256SUMS").read_text().splitlines():
            expected, name = line.split("  ", 1)
            assert name in ALLOWED - {"SHA256SUMS"}
            checked.add(name)
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
        assert checked == ALLOWED - {"SHA256SUMS"}
        for line in (ROOT / "dependencies.tsv").read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            arch, url, archive_sha, member, file_sha, target, mode = line.split("\t")
            parsed = urlsplit(url)
            assert arch in {"all", "x86_64", "aarch64"} and mode in {"644", "755"}
            assert parsed.scheme == "https" and parsed.hostname in {"github.com", "raw.githubusercontent.com"}
            assert not parsed.username and not parsed.password
            assert re.fullmatch(r"[0-9a-f]{64}", archive_sha) and re.fullmatch(r"[0-9a-f]{64}", file_sha)
            assert not target.startswith("/") and ".." not in Path(target).parts
            assert target.startswith((".local/bin/", ".zsh/zsh-autosuggestions/", ".local/share/fonts/JetBrainsMonoNerdFont/"))
    except (AssertionError, ValueError, KeyError, OSError) as error:
        issues.append("Profile/dependency/integrity validation failed: " + type(error).__name__)
if len(sys.argv) > 1:
    if sys.argv[1:] != ["--configs"]:
        issues.append("Usage: audit.py [--configs]")
    else:
        from links import plan, LinkError
        try:
            for source, target in plan():
                scan(source, "Main/" + source.relative_to(Path.home() / "Main").as_posix())
        except (LinkError, OSError) as error:
            issues.append("Main config validation failed: " + type(error).__name__)
if issues:
    print("AUDIT FAILED")
    print("\n".join(issues))
    sys.exit(1)
print(f"AUDIT PASSED: {len(actual)} allowlisted bootstrap files; no recognizable secrets found.")
if sys.argv[1:]:
    print("Also scanned nine current Main configs; values were not displayed.")
