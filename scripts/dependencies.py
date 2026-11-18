#!/usr/bin/env python3
"""Install upstream releases and verify locally installed copies."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

from links import LinkError, directory_chain, normal_home, user_directory


BINARIES = ("starship", "zsh-patina")
FONT_DIR = Path("fonts/JetBrainsMonoNerdFont")
FONT_FILES = (
    "JetBrainsMonoNerdFont-Bold.ttf",
    "JetBrainsMonoNerdFont-BoldItalic.ttf",
    "JetBrainsMonoNerdFont-Italic.ttf",
    "JetBrainsMonoNerdFont-Regular.ttf",
    "OFL.txt",
)
AUTOSUGGESTION_FILES = ("zsh-autosuggestions.zsh", "LICENSE")
AUTOSUGGESTION_REPO = "https://github.com/zsh-users/zsh-autosuggestions.git"
MAX_BYTES = 100 * 1024 * 1024


class DependencyError(Exception):
    pass


def safe_file(path):
    directory_chain(path.parent)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise DependencyError(f"Expected a regular file or an unused path: {path}")


def download(url, destination, *, max_time=300):
    subprocess.run([
        "curl", "--disable", "--fail", "--location", "--silent", "--show-error",
        "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2",
        "--connect-timeout", "15", "--max-time", str(max_time), "--retry", "2",
        "--speed-limit", "1024", "--speed-time", "60",
        "--max-filesize", str(MAX_BYTES), "--output", str(destination), url,
    ], check=True)


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def latest_archive(work, repo, filename):
    metadata = work / "release.json"
    download(f"https://api.github.com/repos/{repo}/releases/latest", metadata)
    release = json.loads(metadata.read_bytes())
    matches = [asset for asset in release["assets"] if re.fullmatch(filename, asset["name"])]
    if len(matches) != 1:
        raise DependencyError(f"Expected one matching archive for the latest release of {repo}.")
    asset = matches[0]
    checksum = asset.get("digest")
    if not isinstance(checksum, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
        raise DependencyError(f"GitHub did not publish a SHA-256 for {asset['name']}.")
    url = asset["browser_download_url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(f"/{repo}/releases/download/"):
        raise DependencyError(f"Unexpected download URL for {repo}.")
    archive = work / asset["name"]
    # Release archives can take longer than metadata on a slow connection.
    download(url, archive, max_time=1200)
    if sha256(archive) != checksum.removeprefix("sha256:"):
        raise DependencyError(f"Download checksum mismatch for {asset['name']}.")
    print(f"{repo}: {release['tag_name']}", flush=True)
    return archive


def archive_files(path, names):
    wanted = set(names)
    files = {}
    with tarfile.open(path) as archive:
        for member in archive:
            name = PurePosixPath(member.name).name
            if name not in wanted:
                continue
            if name in files or not member.isfile() or not 0 < member.size <= MAX_BYTES:
                raise DependencyError(f"Expected one regular archive member: {name}")
            # Read the entry as bytes. Treat paths and links in the archive as data.
            with archive.extractfile(member) as file:
                files[name] = file.read()
    if missing := wanted - files.keys():
        raise DependencyError(f"{path.name} is missing: {', '.join(sorted(missing))}")
    return files


def fetch_autosuggestions(work):
    git = ["git", "-c", "credential.helper=", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    refs = subprocess.check_output(
        git + ["ls-remote", "--tags", "--refs", "--sort=-version:refname", AUTOSUGGESTION_REPO],
        env=env, text=True, timeout=60,
    )
    tag = re.search(r"\trefs/tags/(v\d+\.\d+\.\d+)$", refs, re.MULTILINE)
    if tag is None:
        raise DependencyError("No stable version tag found for zsh-autosuggestions.")
    release = tag[1]
    checkout = work / "zsh-autosuggestions"
    subprocess.run(
        git + ["clone", "--quiet", "--depth=1", "--no-tags", "--no-checkout",
               "--branch", release, AUTOSUGGESTION_REPO, str(checkout)],
        check=True, env=env, timeout=60,
    )
    files = {
        name: subprocess.check_output(["git", "-C", str(checkout), "show", f"HEAD:{name}"])
        for name in AUTOSUGGESTION_FILES
    }
    print(f"zsh-users/zsh-autosuggestions: {release}", flush=True)
    return files


def fetch_latest(work, arch):
    starship_target = "gnu" if arch == "x86_64" else "musl"
    starship = latest_archive(
        work, "starship/starship", re.escape(f"starship-{arch}-unknown-linux-{starship_target}.tar.gz"),
    )
    patina = latest_archive(
        work, "michel-kraemer/zsh-patina", rf"zsh-patina-v[A-Za-z0-9.+_-]+-{arch}-unknown-linux-gnu\.tar\.gz",
    )
    fonts = latest_archive(work, "ryanoasis/nerd-fonts", re.escape("JetBrainsMono.tar.xz"))
    files = archive_files(starship, ("starship",))
    files.update(archive_files(patina, ("zsh-patina",)))
    files.update(archive_files(fonts, FONT_FILES))
    files.update(fetch_autosuggestions(work))
    return files


def matches(path, digest, mode):
    return path.is_file() and stat.S_IMODE(path.stat().st_mode) == mode and sha256(path) == digest


def write_file(path, payload, mode):
    safe_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".dotfiles.")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def check(home, targets, record):
    if not record.is_file():
        raise DependencyError("Missing download checksums. Run bash install.sh to download and verify the dependencies.")
    checksums = json.loads(record.read_bytes())
    if not isinstance(checksums, dict):
        raise DependencyError("Invalid download checksums. Run bash install.sh.")
    mismatches = [
        str(target)
        for target, mode in targets.values()
        if not matches(target, checksums.get(str(target.relative_to(home))), mode)
    ]
    if mismatches:
        raise DependencyError("Dependencies differ or are missing. Run bash install.sh.\n" + "\n".join(mismatches))


def verify_launch(files, bin_dir):
    directory_chain(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    # Check executables on the same filesystem as the final copies.
    with tempfile.TemporaryDirectory(prefix=".dotfiles-check-", dir=bin_dir) as temp:
        work = Path(temp)
        for name in BINARIES:
            path = work / name
            path.write_bytes(files[name])
            path.chmod(0o700)
            try:
                subprocess.run(
                    [str(path), "--version"], check=True, timeout=10,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise DependencyError(f"The downloaded {name} cannot run on this system. Installed files were kept.") from error
        plugin = work / AUTOSUGGESTION_FILES[0]
        plugin.write_bytes(files[plugin.name])
        subprocess.run(["zsh", "-dfn", str(plugin)], check=True, timeout=10)


def back_up_files(home, backup_dir, targets):
    backup = None
    originals = {}
    for target in targets:
        safe_file(target)
        if not target.exists():
            continue
        if backup is None:
            directory_chain(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = Path(tempfile.mkdtemp(prefix=stamp + "-dependencies-", dir=backup_dir))
            print(f"Dependency backups: {backup}", flush=True)
        saved = backup / target.relative_to(home)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved, follow_symlinks=False)
        originals[target] = saved
    return originals


def restore_file(target, saved):
    if saved is None:
        safe_file(target)
        target.unlink(missing_ok=True)
    else:
        write_file(target, saved.read_bytes(), stat.S_IMODE(saved.stat().st_mode))


def install(home, targets, record, font_dir, arch):
    with tempfile.TemporaryDirectory(prefix="fedora-kde-dependencies-") as temp:
        files = fetch_latest(Path(temp), arch)
    verify_launch(files, targets[BINARIES[0]][0].parent)
    checksums = {}
    updates = {}
    for name, (target, mode) in targets.items():
        digest = hashlib.sha256(files[name]).hexdigest()
        checksums[str(target.relative_to(home))] = digest
        if not matches(target, digest, mode):
            updates[target] = (files[name], mode)

    data = (json.dumps(checksums, indent=2, sort_keys=True) + "\n").encode()
    checksums_changed = not record.is_file() or record.read_bytes() != data
    fonts_changed = any(target.parent == font_dir for target in updates)
    backup_targets = [*updates, record] if checksums_changed else updates
    originals = back_up_files(home, record.parent / "backups", backup_targets)
    with ExitStack() as rollback:
        for target, (payload, mode) in updates.items():
            rollback.callback(restore_file, target, originals.get(target))
            write_file(target, payload, mode)
        if fonts_changed or checksums_changed:
            subprocess.run(["fc-cache", str(font_dir)], check=True)
        if checksums_changed:
            rollback.callback(restore_file, record, originals.get(record))
            write_file(record, data, 0o600)
        rollback.pop_all()
    for target in updates:
        print(f"Installed: {target}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "plan", "install", "check"))
    parser.add_argument("arch", choices=("x86_64", "aarch64"))
    args = parser.parse_args()
    home = normal_home()
    font_dir = user_directory(home, "XDG_DATA_HOME", ".local/share") / FONT_DIR
    record = user_directory(home, "XDG_STATE_HOME", ".local/state") / "dotfiles/dependencies.json"
    targets = {name: (home / ".local/bin" / name, 0o755) for name in BINARIES}
    targets.update({name: (font_dir / name, 0o644) for name in FONT_FILES})
    targets.update({name: (home / ".zsh/zsh-autosuggestions" / name, 0o644) for name in AUTOSUGGESTION_FILES})
    for path, _ in targets.values():
        safe_file(path)
    safe_file(record)
    if args.action == "plan":
        print("Would fetch the latest Starship, zsh-patina, JetBrains Mono Nerd Font and zsh-autosuggestions.")
        for path, _ in targets.values():
            print(f"Dependency target: {path}")
    elif args.action == "install":
        install(home, targets, record, font_dir, args.arch)
    elif args.action == "check":
        check(home, targets, record)


if __name__ == "__main__":
    try:
        main()
    except (DependencyError, LinkError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError) as error:
        sys.exit(f"Dependency setup: {error}")
