#!/usr/bin/env python3
"""Check or render selected KConfig entries while preserving other text."""
from pathlib import Path
import re
import sys


def header(line):
    stripped = line.strip()
    return stripped if re.fullmatch(r"\[.+\]", stripped) else None


def entry(line):
    if line.lstrip().startswith(("#", ";")) or "=" not in line:
        return None
    key, value = line.rstrip("\r\n").split("=", 1)
    return key.strip(), value


def parse(text, fragment=False):
    groups = {}
    group = None
    for number, line in enumerate(text.splitlines(), 1):
        if found := header(line):
            group = found
            groups.setdefault(group, {})
        elif found := entry(line):
            if group is None:
                if fragment:
                    raise ValueError(f"Fragment entry outside a section at line {number}")
                continue
            key, value = found
            if fragment and key in groups[group]:
                raise ValueError(f"Duplicate fragment entry at line {number}")
            groups[group][key] = value
        elif fragment and line.strip() and not line.lstrip().startswith(("#", ";")):
            raise ValueError(f"Invalid fragment line {number}")
    if fragment and (not groups or any(not values for values in groups.values())):
        raise ValueError("Expected nonempty fragment sections")
    return groups


def matches(updates, current):
    return all(current.get(group, {}).get(key) == value for group, values in updates.items() for key, value in values.items())


def shortcut_parts(value):
    for index, character in enumerate(value):
        if character != ",":
            continue
        backslashes = len(value[:index]) - len(value[:index].rstrip("\\"))
        if backslashes % 2 == 0:
            return re.split(r"\\t|\t", value[:index]), value[index:]
    return re.split(r"\\t|\t", value), ""


def normalized_key(value):
    if value.lower() in {"", "none"}:
        return None
    parts = value.split("+")
    if len(parts) > 1 and all(part in {"Meta", "Ctrl", "Alt", "Shift"} for part in parts[:-1]):
        return "+".join(sorted(parts[:-1]) + [parts[-1].upper()])
    return value


def resolve_shortcut_conflicts(updates, current):
    result = {group: dict(values) for group, values in updates.items()}
    wanted = {normalized_key(key) for values in updates.values() for value in values.values() for key in shortcut_parts(value)[0]}
    wanted.discard(None)
    for group, values in current.items():
        for key, value in values.items():
            if key.startswith("_") and key != "_launch":
                continue
            if key in updates.get(group, {}):
                continue
            active, suffix = shortcut_parts(value)
            kept = [binding for binding in active if normalized_key(binding) not in wanted]
            if kept != active:
                result.setdefault(group, {})[key] = (r"\t".join(kept) if kept else "none") + suffix
    return result


def merge(updates, text):
    output = []
    present_groups = set()
    group = None
    seen = set()

    def append_line(line):
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append(line)

    def flush():
        if group in updates:
            for key, value in updates[group].items():
                if key not in seen:
                    append_line(f"{key}={value}\n")

    for line in text.splitlines(keepends=True):
        if found := header(line):
            flush()
            group = found
            seen = set()
            present_groups.add(group)
            append_line(line)
        elif group in updates and (found := entry(line)) and found[0] in updates[group]:
            key, value = found
            seen.add(key)
            append_line(line if value == updates[group][key] else f"{key}={updates[group][key]}\n")
        else:
            append_line(line)
    flush()
    for group, values in updates.items():
        if group not in present_groups:
            if output and output[-1].strip():
                append_line("\n")
            append_line(group + "\n")
            for key, value in values.items():
                append_line(f"{key}={value}\n")
    result = "".join(output)
    if not matches(updates, parse(result)):
        raise ValueError("Rendered config does not contain the selected entries")
    return result


def main():
    if len(sys.argv) not in (4, 5) or sys.argv[1] not in ("--check", "--render"):
        raise ValueError("Usage: merge-kconfig.py --check FRAGMENT TARGET | --render FRAGMENT TARGET OUTPUT")
    mode, fragment, target = sys.argv[1:4]
    updates = parse(Path(fragment).read_text(), fragment=True)
    path = Path(target)
    current = path.read_text() if path.exists() else ""
    if Path(fragment).name == "kglobalshortcutsrc":
        updates = resolve_shortcut_conflicts(updates, parse(current))
    if mode == "--check" and len(sys.argv) == 4:
        return 0 if matches(updates, parse(current)) else 1
    if mode == "--render" and len(sys.argv) == 5:
        Path(sys.argv[4]).write_text(merge(updates, current))
        return 0
    raise ValueError("Invalid arguments")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"KConfig merge failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(2)
