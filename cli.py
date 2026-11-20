#!/usr/bin/env python3
"""A terminal chat room backed by a shared directory."""

import argparse
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import errno
import getpass
import json
import math
import os
import re
import stat
import sys
import time
import unicodedata
import uuid


ROOM_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
MESSAGE_FILE = re.compile(r"(?:[01][0-9]|2[0-3])[0-5][0-9][0-5][0-9][0-9]{6}-[0-9a-f]{32}\.json")
MARKER = ".chillroom-v1"
MAX_TEXT_BYTES = 4096
MAX_NAME_BYTES = 64
MAX_FILE_BYTES = MAX_TEXT_BYTES * 2 + MAX_NAME_BYTES + 128
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def utc_now():
    return datetime.now(timezone.utc)


@contextmanager
def directory(path, parent=None):
    fd = os.open(path, DIRECTORY_FLAGS, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def valid_text(text, max_bytes, extra=""):
    return (
        isinstance(text, str)
        and text.strip()
        and all(ch.isprintable() or ch in extra + "\u200c\u200d" for ch in text)
        and len(text.encode("utf-8")) <= max_bytes
    )


@dataclass(frozen=True)
class Message:
    day: str
    filename: str
    author: str
    text: str

    @property
    def timestamp(self):
        key = self.filename
        return f"{key[:2]}:{key[2:4]}:{key[4:6]}"

    def lines(self, history=False):
        prefix = f"{self.day} {self.timestamp}Z" if history else self.timestamp
        first, *rest = self.text.expandtabs(4).split("\n")
        return [f"[{prefix}] {self.author}: {first}", *[f"    {line}" for line in rest]]


def read_message(day_fd, day, filename):
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=day_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None
        raise
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            return None
        payload = stream.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    author, text = data.get("author"), data.get("text")
    if valid_text(author, MAX_NAME_BYTES) and valid_text(text, MAX_TEXT_BYTES, "\n\t"):
        return Message(day, filename, author, text)
    return None


class Room:
    def __init__(self, fd):
        self.fd = fd

    def days(self):
        days = []
        for name in os.listdir(self.fd):
            try:
                day = date.fromisoformat(name)
            except ValueError:
                continue
            if day.isoformat() == name:
                days.append(name)
        return sorted(days, reverse=True)

    def send(self, author, text):
        if not valid_text(author, MAX_NAME_BYTES):
            raise ValueError(f"name must be printable and 1–{MAX_NAME_BYTES} UTF-8 bytes")
        if not valid_text(text, MAX_TEXT_BYTES, "\n\t"):
            raise ValueError(f"message must be printable and 1–{MAX_TEXT_BYTES} UTF-8 bytes")
        now = utc_now()
        day = now.date().isoformat()
        filename = f"{now:%H%M%S%f}-{uuid.uuid4().hex}.json"
        temporary = f".{filename}.tmp"
        payload = json.dumps({"author": author, "text": text}, ensure_ascii=False).encode("utf-8")
        try:
            os.mkdir(day, 0o2770, dir_fd=self.fd)
        except FileExistsError:
            pass
        with directory(day, self.fd) as day_fd:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640, dir_fd=day_fd)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temporary, filename, src_dir_fd=day_fd, dst_dir_fd=day_fd)
            except OSError:
                try:
                    os.unlink(temporary, dir_fd=day_fd)
                except OSError:
                    pass
                raise
        return Message(day, filename, author, text)

    def filenames(self, day):
        try:
            with directory(day, self.fd) as day_fd:
                return {name for name in os.listdir(day_fd) if MESSAGE_FILE.fullmatch(name)}
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                raise
            return set()

    def messages(self, day, names, limit=None, seen=None):
        messages = []
        if not names or limit == 0:
            return messages
        observed = set()
        try:
            with directory(day, self.fd) as day_fd:
                for name in sorted(names, reverse=True):
                    try:
                        message = read_message(day_fd, day, name)
                    except FileNotFoundError:
                        continue
                    observed.add(name)
                    if message is not None:
                        messages.append(message)
                        if len(messages) == limit:
                            break
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                raise
        if seen is not None:
            seen.update(observed)
        return messages

    def history(self, limit):
        messages = []
        for day in self.days() if limit else ():
            messages.extend(self.messages(day, self.filenames(day), limit - len(messages)))
            if len(messages) == limit:
                break
        return list(reversed(messages))

    def prune(self, keep_days, temp_hours, max_files, apply):
        now = utc_now()
        first_kept_day = now.date() - timedelta(days=keep_days - 1)
        temp_cutoff = now.timestamp() - temp_hours * 3600
        removed = 0
        for day in reversed(self.days()):
            expired = day < first_kept_day.isoformat()
            try:
                with directory(day, self.fd) as day_fd:
                    for name in os.listdir(day_fd):
                        temporary = name.startswith(".") and name.endswith(".tmp")
                        key = name[1:-4] if temporary else name
                        if not MESSAGE_FILE.fullmatch(key) or not (temporary or expired):
                            continue
                        try:
                            info = os.stat(name, dir_fd=day_fd, follow_symlinks=False)
                            if not stat.S_ISREG(info.st_mode) or (temporary and info.st_mtime >= temp_cutoff):
                                continue
                            if apply:
                                os.unlink(name, dir_fd=day_fd)
                            removed += 1
                        except FileNotFoundError:
                            continue
                        if removed == max_files:
                            return removed
                if expired and apply:
                    try:
                        os.rmdir(day, dir_fd=self.fd)
                    except OSError as exc:
                        if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                            raise
            except OSError as exc:
                if exc.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                    raise
        return removed


def init_room(root_fd, name):
    try:
        os.mkdir(name, 0o2770, dir_fd=root_fd)
    except FileExistsError:
        pass
    with directory(name, root_fd) as room_fd:
        entries = os.listdir(room_fd)
        if MARKER not in entries:
            if entries:
                raise ValueError(f"directory {name!r} already exists and is not empty")
            try:
                os.mkdir(MARKER, 0o770, dir_fd=room_fd)
            except FileExistsError:
                pass
        with directory(MARKER, room_fd):
            pass


def active_days():
    today = utc_now().date()
    return [(today + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]


def poll_room(room, seen):
    days = active_days()
    for day in seen.keys() - set(days):
        del seen[day]
    for day in days:
        known = seen.setdefault(day, set())
        messages = room.messages(day, room.filenames(day) - known, seen=known)
        yield from reversed(messages)


def cell_width(ch):
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def wrap_line(line, width):
    cells = 0
    start = 0
    for index, ch in enumerate(line):
        size = cell_width(ch)
        if cells + size > width and index > start:
            yield line[start:index]
            cells, start = 0, index
        cells += size
    yield line[start:]


def draw_chat(screen, room_name, messages, text, cursor, status):
    import curses

    height, width = screen.getmaxyx()
    screen.erase()
    if height < 4 or width < 6:
        screen.refresh()
        return
    screen.addnstr(0, 0, f"chillroom / {room_name}  (UTC)", width - 1, curses.A_BOLD)
    visible = deque(maxlen=height - 3)
    for message in messages:
        for line in message.lines():
            visible.extend(wrap_line(line, width - 1))
    for row, line in enumerate(visible, start=1):
        screen.addstr(row, 0, line)
    status_line = next(wrap_line(status or "Enter to send  |  Ctrl+D to leave", width - 1))
    screen.addstr(height - 2, 0, status_line, curses.A_DIM)
    start, cells = cursor, 0
    while start > 0 and cells + cell_width(text[start - 1]) < width - 3:
        start -= 1
        cells += cell_width(text[start])
    screen.addstr(height - 1, 0, "> " + next(wrap_line(text[start:], width - 3)))
    screen.move(height - 1, cells + 2)
    screen.refresh()


def chat(screen, room, args):
    import curses

    screen.timeout(200)
    seen = {day: room.filenames(day) for day in active_days()}
    messages = deque(room.history(args.limit), maxlen=max(200, args.limit))
    for message in messages:
        if message.day in seen:
            seen[message.day].add(message.filename)
    text, cursor, status = "", 0, ""
    next_poll = 0.0
    redraw = True
    while True:
        if time.monotonic() >= next_poll:
            next_poll = time.monotonic() + args.poll
            try:
                for message in poll_room(room, seen):
                    messages.append(message)
                    redraw = True
                if status == "Storage unavailable. Retrying…":
                    status = ""
                    redraw = True
            except OSError:
                status = "Storage unavailable. Retrying…"
                redraw = True
        if redraw:
            try:
                draw_chat(screen, args.room, messages, text, cursor, status)
            except curses.error:
                # A resize can invalidate drawing coordinates between calls.
                pass
            redraw = False
        try:
            key = screen.get_wch()
        except curses.error:
            continue
        redraw = True
        if key == "\x04" and not text:
            return
        if key in ("\n", "\r", curses.KEY_ENTER) and text.strip():
            try:
                message = room.send(args.name, text)
            except (OSError, ValueError) as exc:
                status = f"Send failed · {exc.strerror if isinstance(exc, OSError) else exc}"
            else:
                messages.append(message)
                seen.setdefault(message.day, set()).add(message.filename)
                text, cursor, status = "", 0, ""
        elif key in (curses.KEY_BACKSPACE, "\b", "\x7f") and cursor > 0:
            text, cursor = text[:cursor - 1] + text[cursor:], cursor - 1
        elif key == curses.KEY_DC:
            text = text[:cursor] + text[cursor + 1:]
        elif key == curses.KEY_LEFT:
            cursor = max(0, cursor - 1)
        elif key == curses.KEY_RIGHT:
            cursor = min(len(text), cursor + 1)
        elif key in (curses.KEY_HOME, "\x01"):
            cursor = 0
        elif key in (curses.KEY_END, "\x05"):
            cursor = len(text)
        elif key == "\x15":
            text, cursor = "", 0
        elif isinstance(key, str) and (key.isprintable() or key in "\u200c\u200d"):
            if len(text.encode("utf-8")) + len(key.encode("utf-8")) <= MAX_TEXT_BYTES:
                text, cursor, status = text[:cursor] + key + text[cursor:], cursor + 1, ""


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive(value):
    number = nonnegative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def poll_interval(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0.2:
        raise argparse.ArgumentTypeError("must be at least 0.2 seconds")
    return seconds


def parse_args():
    parser = argparse.ArgumentParser(prog="chillroom", description=__doc__)
    parser.add_argument("--root", default=os.environ.get("CHILLROOM_ROOT"), help="shared directory (or CHILLROOM_ROOT)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize a room")
    join = commands.add_parser("join", help="open an interactive chat")
    send = commands.add_parser("send", help="publish a message")
    history = commands.add_parser("history", help="show recent messages")
    prune = commands.add_parser("prune", help="preview or remove expired files")
    for command in (init, join, send, history, prune):
        command.add_argument("room")
    for command in (join, send):
        command.add_argument("--name", default=os.environ.get("CHILLROOM_NAME"), help="display name (or CHILLROOM_NAME)")
    join.add_argument("--poll", type=poll_interval, default=3, metavar="SECONDS")
    send.add_argument("text", nargs="?", help="message text, or read from stdin if omitted")
    for command in (join, history):
        command.add_argument("--limit", type=nonnegative, default=20, help="number of recent messages to show")
    prune.add_argument("--keep-days", type=positive, default=7, help="UTC calendar days to keep, including today")
    prune.add_argument("--temp-hours", type=positive, default=24, help="age at which to remove incomplete writes")
    prune.add_argument("--max-files", type=positive, help="limit the number of files processed in one run")
    prune.add_argument("--apply", action="store_true", help="delete files instead of previewing the count")
    args = parser.parse_args()
    if not args.root:
        parser.error("set CHILLROOM_ROOT or pass --root before the command")
    if not ROOM_NAME.fullmatch(args.room):
        parser.error("room must be 1–64 letters, digits, underscores or hyphens, starting with a letter or digit")
    if args.command in ("join", "send") and args.name is None:
        args.name = getpass.getuser()
    return args


def run(args):
    with directory(os.path.realpath(args.root)) as root_fd:
        if args.command == "init":
            init_room(root_fd, args.room)
            print(f"Room ready · {args.room}")
            return
        with directory(args.room, root_fd) as room_fd:
            try:
                with directory(MARKER, room_fd):
                    pass
            except FileNotFoundError as exc:
                raise ValueError(f"room {args.room!r} has not been initialized") from exc
            room = Room(room_fd)
            if args.command == "send":
                text = args.text
                if text is None:
                    text = sys.stdin.buffer.read(MAX_TEXT_BYTES + 1).decode("utf-8")
                room.send(args.name, text)
            elif args.command == "history":
                for message in room.history(args.limit):
                    print("\n".join(message.lines(history=True)))
            elif args.command == "join":
                if not sys.stdin.isatty() or not sys.stdout.isatty():
                    raise ValueError("join requires a terminal; use send or history for redirected input/output")
                if not valid_text(args.name, MAX_NAME_BYTES):
                    raise ValueError(f"name must be printable and 1–{MAX_NAME_BYTES} UTF-8 bytes")
                try:
                    import curses
                except ImportError as exc:
                    raise ValueError("join requires Python's curses module") from exc
                try:
                    curses.wrapper(chat, room, args)
                except curses.error as exc:
                    raise ValueError(f"could not open the terminal: {exc}") from exc
            elif args.command == "prune":
                count = room.prune(args.keep_days, args.temp_hours, args.max_files, args.apply)
                action = "Removed" if args.apply else "Would remove"
                print(f"{action} {count} file(s)")


def main():
    try:
        run(parse_args())
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, OverflowError) as exc:
        print(f"chillroom: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
