#!/usr/bin/env python3
"""Interactive, credential-isolated restoration into a new private directory."""
from datetime import datetime
import getpass
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time


class RestoreError(Exception):
    pass


class CommandError(RestoreError):
    def __init__(self, operation, code):
        self.code = code
        super().__init__(f"{operation}: команда завершилась с кодом {code}.")


def load_profile(path):
    profile = json.loads(Path(path).read_text())
    if not isinstance(profile, dict) or set(profile) != {"remote", "repository_path", "tag", "source_directory"}:
        raise RestoreError("Неверный состав restore.json.")
    if not all(isinstance(value, str) for value in profile.values()):
        raise RestoreError("Значения restore.json должны быть строками.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile["remote"]):
        raise RestoreError("Неверное имя подключения rclone.")
    relative = profile["repository_path"]
    if not relative or relative.startswith("/") or ":" in relative or ".." in relative.split("/") or PurePosixPath(relative).as_posix() != relative or any(ord(c) < 32 for c in relative):
        raise RestoreError("Путь репозитория должен быть относительным путём без URL и credentials.")
    for name in ("tag", "source_directory"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile[name]):
            raise RestoreError("Неверный тег или имя исходной папки.")
    return profile


def private_environment(work):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("RESTIC_", "RCLONE_"))}
    env["RCLONE_CONFIG"] = str(work / "rclone.conf")
    env["XDG_CACHE_HOME"] = str(work / "cache")
    return env


def run_private(command, env, work, operation):
    # Child diagnostics are private, transient, and never copied to the repository.
    with tempfile.TemporaryFile(dir=work) as output, tempfile.TemporaryFile(dir=work) as errors:
        child = subprocess.Popen(command, env=env, cwd=env["HOME"], stdout=output, stderr=errors)
        started = time.monotonic()
        try:
            while True:
                try:
                    code = child.wait(timeout=15)
                    break
                except subprocess.TimeoutExpired:
                    print(f"{operation}: {int(time.monotonic() - started)} секунд…", flush=True)
        except BaseException:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            raise
        if code != 0:
            raise CommandError(operation, code)
        output.seek(0)
        return output.read()


def snapshot_choices(payload, profile):
    records = json.loads(payload)
    if not isinstance(records, list):
        raise RestoreError("Restic вернул неверный список снимков.")
    selected = []
    for item in records:
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("id", ""))):
            raise RestoreError("Неверный идентификатор снимка.")
        paths = item.get("paths", [])
        if not isinstance(paths, list) or not isinstance(item.get("tags", []), list):
            raise RestoreError("Неверные пути или теги снимка.")
        if profile["tag"] not in item.get("tags", []) or len(paths) != 1 or not isinstance(paths[0], str) or PurePosixPath(paths[0]).name != profile["source_directory"]:
            continue
        try:
            instant = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise RestoreError("Неверная дата снимка.") from None
        if instant.tzinfo is None:
            raise RestoreError("В дате снимка не указан часовой пояс.")
        selected.append((instant, item))
    selected.sort(key=lambda pair: pair[0], reverse=True)
    if not selected:
        raise RestoreError("Нет снимков с нужным тегом и единственной исходной папкой Main.")
    for number, (instant, item) in enumerate(selected[:5], 1):
        host = "".join(c for c in str(item.get("hostname", "")) if c.isprintable())[:50]
        print(f"{number}. {instant.isoformat(timespec='seconds')}  {item['id'][:8]}  {host}")
    answer = input("Снимок: номер из списка или ID; Enter — самый новый: ").strip() or "1"
    if answer.isdigit() and 1 <= int(answer) <= min(5, len(selected)):
        return selected[int(answer) - 1][1]["id"]
    if re.fullmatch(r"[0-9a-f]{8,64}", answer):
        matches = [item["id"] for _, item in selected if item["id"].startswith(answer)]
        if len(matches) == 1:
            return matches[0]
    raise RestoreError("Не выбран однозначный снимок из проверенного списка.")


def restore_files(profile_path):
    profile = load_profile(profile_path)
    home = Path(os.environ.get("HOME", ""))
    if not home.is_absolute() or home == Path("/") or not home.is_dir() or home != home.resolve():
        raise RestoreError("Нужна обычная абсолютная домашняя папка без ссылок.")
    destination = None
    print("[1/4] Временная настройка доступа rclone.")
    print(f"Создай подключение {profile['remote']} для Google Drive (тип drive).")
    print("Введи OAuth client ID/secret и авторизуйся в браузере; затем заверши rclone config через q.")
    print("Текущие rclone.conf и переменные RESTIC_/RCLONE_ не используются.")
    try:
        with tempfile.TemporaryDirectory(prefix="dotfiles-restore-") as temporary:
            work = Path(temporary)
            env = private_environment(work)
            config = work / "rclone.conf"
            code = subprocess.run(["rclone", "--config", str(config), "config"], env=env, cwd=home).returncode
            if code != 0:
                raise CommandError("Настройка rclone", code)
            if not config.is_file() or config.is_symlink():
                raise RestoreError("Временное подключение rclone не создано.")
            config.chmod(0o600)
            if b"RCLONE_ENCRYPT_V0:" in config.read_bytes()[:1024]:
                env["RCLONE_CONFIG_PASS"] = getpass.getpass("Пароль шифрования временного конфига rclone: ")
            remotes = run_private(["rclone", "--config", str(config), "listremotes"], env, work, "Проверка подключения").decode().splitlines()
            if profile["remote"] + ":" not in remotes:
                raise RestoreError("Подключение с именем из restore.json не найдено во временном конфиге.")
            repository = f"rclone:{profile['remote']}:{profile['repository_path']}"
            command = ["restic", "--repo", repository, "--no-lock", "--cache-dir", str(work / "restic-cache"), "-o", "rclone.args=serve restic --stdio --contimeout 60s --timeout 60s --retries 5 --low-level-retries 10"]
            print("[2/4] Пароль Restic и выбор снимка.")
            snapshots = None
            for _ in range(3):
                phrase = getpass.getpass("Пароль Restic: ")
                if not phrase:
                    print("Пустой пароль не подходит.")
                    continue
                env["RESTIC_PASSWORD"] = phrase
                try:
                    snapshots = run_private(command + ["snapshots", "--json", "--tag", profile["tag"]], env, work, "Чтение снимков")
                    break
                except CommandError as error:
                    if error.code != 12:
                        raise
                    print("Пароль Restic не подошёл.")
            if snapshots is None:
                raise RestoreError("Три попытки не удались. Проверь пароль Restic и выбранный репозиторий.")
            snapshot = snapshot_choices(snapshots, profile)
            destination = Path(tempfile.mkdtemp(prefix="Restored-" + profile["source_directory"] + "-", dir=home))
            marker = destination / ".RESTORE_INCOMPLETE"
            marker.write_text("Восстановление не завершено. Не считайте эти данные проверенной копией.\n")
            target = destination / profile["source_directory"]
            print(f"[3/4] Восстановление снимка {snapshot[:8]} в {target}", flush=True)
            run_private(command + ["restore", snapshot + ":/" + profile["source_directory"], "--target", str(target), "--overwrite", "never", "--verify"], env, work, "Восстановление и проверка файлов")
            if not target.is_dir() or target.is_symlink():
                raise RestoreError("Restic не создал ожидаемую папку.")
            (destination / ".RESTORE_COMPLETE").write_text("snapshot=" + snapshot + "\nverified=true\n")
            marker.unlink()
            env.pop("RESTIC_PASSWORD", None)
            env.pop("RCLONE_CONFIG_PASS", None)
            phrase = ""
        print(f"[4/4] Готово. Restic проверил содержимое: {target}")
        print("Временные данные доступа удалены. Исходная папка Main не заменялась.")
        return target
    except BaseException:
        if destination is not None:
            print(f"Незавершённое восстановление оставлено в {destination}", file=sys.stderr)
        raise


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--activate-main"):
        raise RestoreError("Использование: python3 scripts/restore.py restore.json [--activate-main]")
    if os.geteuid() == 0 or not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RestoreError("Запусти ./install.sh --restore от обычного пользователя в интерактивном терминале.")
    activate = len(sys.argv) == 3
    if activate and os.path.lexists(Path(os.environ.get("HOME", "")) / "Main"):
        raise RestoreError("Main уже существует. Автоматическая замена запрещена.")
    target = restore_files(sys.argv[1])
    if activate:
        from links import adopt_main, LinkError
        try:
            target = adopt_main(target)
        except (LinkError, OSError) as error:
            raise RestoreError(f"Main оставлен отдельно в {target}: {error}") from None
        print(f"Main готов: {target}. Следующий этап — создание ссылок.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Восстановление остановлено пользователем; временные данные доступа удалены.", file=sys.stderr)
        sys.exit(130)
    except (RestoreError, OSError, ValueError, UnicodeError) as error:
        message = str(error) if isinstance(error, RestoreError) else type(error).__name__
        print("Ошибка восстановления: " + message, file=sys.stderr)
        print("Проверь доступ к хранилищу, путь и пароль. Текущие файлы Main не перезаписывались.", file=sys.stderr)
        sys.exit(1)
