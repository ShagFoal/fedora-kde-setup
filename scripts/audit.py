#!/usr/bin/env python3
"""Read-only allowlist, config and recognizable-secret checks. Never prints values."""
import configparser
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {
    "files/.zshrc",
    "files/.config/starship.toml",
    "files/.config/konsolerc",
    "files/.config/fastfetch/config.jsonc",
    "files/.local/share/konsole/Profile 1.profile",
    "files/.local/share/konsole/Catppuccin-Mocha.colorscheme",
    "files/.config/dolphinrc",
    "files/.local/share/kxmlgui5/dolphin/dolphinui.rc",
    "files/.config/mpv/mpv.conf",
    "files/.config/kxkbrc",
    "files/.config/kcminputrc",
    "files/.config/kglobalshortcutsrc",
    "files/.config/kwinrc",
}
ALLOWED = CONFIGS | {
    ".gitignore", "README.md", "AUDIT.md", "install.sh", "dependencies.tsv",
    "SHA256SUMS", "scripts/audit.py", "scripts/merge-kconfig.py", "tests/test_install.py",
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
for path in ROOT.rglob("*"):
    relative = path.relative_to(ROOT).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        continue
    if path.is_symlink():
        issues.append(f"{relative}: symbolic link")
    elif path.is_file():
        actual.add(relative)
        if relative not in ALLOWED:
            issues.append(f"{relative}: unexpected file (contents not displayed)")
            continue
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            for label, pattern in RULES.items():
                if re.search(pattern, line):
                    issues.append(f"{relative}:{line_no}: {label} (value hidden)")
for name in sorted(ALLOWED - actual):
    issues.append(f"{name}: missing file")

if not issues:
    try:
        tomllib.loads((ROOT / "files/.config/starship.toml").read_text())
        json.loads((ROOT / "files/.config/fastfetch/config.jsonc").read_text())
        profile = configparser.ConfigParser()
        profile.read(ROOT / "files/.local/share/konsole/Profile 1.profile")
        assert profile["Appearance"]["ColorScheme"] == "Catppuccin-Mocha"
        assert profile["Appearance"]["Font"].startswith("JetBrainsMono Nerd Font,")
        assert profile["General"]["Command"] == "/bin/zsh"
        dolphin = configparser.ConfigParser()
        dolphin.read_string("[Root]\n" + (ROOT / "files/.config/dolphinrc").read_text())
        assert dolphin["General"]["DoubleClickViewAction"] == "go_up"
        assert not dolphin.has_option("UiSettings", "ColorScheme")
        toolbar = ET.parse(ROOT / "files/.local/share/kxmlgui5/dolphin/dolphinui.rc").getroot()
        assert toolbar.tag == "gui" and toolbar.attrib["name"] == "dolphin"
        assert toolbar.find("ToolBar[@name='mainToolBar']") is not None
        keyboard = configparser.ConfigParser(interpolation=None)
        keyboard.read(ROOT / "files/.config/kxkbrc")
        assert keyboard["Layout"]["LayoutList"] == "us,ru"
        assert keyboard["Layout"]["Options"] == "grp:caps_toggle"
        repeat = configparser.ConfigParser(interpolation=None)
        repeat.read(ROOT / "files/.config/kcminputrc")
        assert set(repeat.sections()) == {"Keyboard"}
        assert set(repeat["Keyboard"]) == {"repeatdelay", "repeatrate"}
        desktops = configparser.ConfigParser(interpolation=None)
        desktops.read(ROOT / "files/.config/kwinrc")
        assert set(desktops.sections()) == {"Desktops"}
        assert set(desktops["Desktops"]) == {"number", "rows"}
        assert desktops["Desktops"]["Number"] == "9" and desktops["Desktops"]["Rows"] == "3"
        shortcuts = configparser.ConfigParser(interpolation=None, delimiters=("=",))
        shortcuts.optionxform = str
        shortcuts.read(ROOT / "files/.config/kglobalshortcutsrc")
        assert set(shortcuts.sections()) == {"kwin", "services][org.kde.konsole.desktop"}
        assert dict(shortcuts["services][org.kde.konsole.desktop"]) == {"_launch": "Meta+Return"}
        for key in shortcuts["kwin"]:
            assert re.fullmatch(r"(?:Switch One Desktop (?:Down|Up|to the Left|to the Right)|Switch to Desktop [1-9][0-9]*|Switch to (?:Next|Previous) Desktop)", key)
        for desktop, binding in [(2, "Meta+1"), (5, "Meta+2"), (8, "Meta+3")]:
            assert shortcuts["kwin"][f"Switch to Desktop {desktop}"].split(",", 1)[0] == binding
        mpv_options = dict(line.split("=", 1) for line in (ROOT / "files/.config/mpv/mpv.conf").read_text().splitlines() if line and not line.startswith("#"))
        assert mpv_options["fullscreen"] == "yes" and mpv_options["save-position-on-quit"] == "yes"
        zshrc = (ROOT / "files/.zshrc").read_text()
        assert "backup-main" not in zshrc and not re.search(r"alias\s+bm=", zshrc)
        for number, line in enumerate((ROOT / "dependencies.tsv").read_text().splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            arch, url, archive_sha, member, file_sha, target, mode = line.split("\t")
            parsed = urlsplit(url)
            assert parsed.scheme == "https" and not parsed.username and not parsed.password
            assert parsed.hostname in {"github.com", "raw.githubusercontent.com"}
            assert parsed.path.startswith(("/starship/starship/", "/michel-kraemer/zsh-patina/", "/ryanoasis/nerd-fonts/", "/zsh-users/zsh-autosuggestions/"))
            assert arch in {"all", "x86_64", "aarch64"} and mode in {"644", "755"}
            assert re.fullmatch(r"[0-9a-f]{64}", archive_sha)
            assert re.fullmatch(r"[0-9a-f]{64}", file_sha)
            assert not target.startswith("/") and ".." not in Path(target).parts
            assert target.startswith((".local/bin/", ".local/share/fonts/JetBrainsMonoNerdFont/", ".zsh/zsh-autosuggestions/"))
        checked = set()
        for line in (ROOT / "SHA256SUMS").read_text().splitlines():
            expected, relative = line.split("  ", 1)
            assert relative in ALLOWED - {"SHA256SUMS"}
            checked.add(relative)
            assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
        assert checked == ALLOWED - {"SHA256SUMS"}
    except (AssertionError, ValueError, KeyError, OSError, configparser.Error, ET.ParseError) as error:
        issues.append(f"Config/lock/integrity validation failed: {type(error).__name__} {error}")

if issues:
    print("AUDIT FAILED")
    print("\n".join(issues))
    sys.exit(1)
print(f"AUDIT PASSED: {len(CONFIGS)} configs; {len(actual)} allowlisted files; no recognizable secrets or personal paths found.")
print("This pattern scan cannot guarantee the absence of every possible secret. Review future edits before publishing.")
