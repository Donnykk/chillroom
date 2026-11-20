# Chillroom

Chillroom is a terminal chat tool for people who share a filesystem. It runs locally or across machines with access to the same directory. Clients read and write messages directly on the share, so there is no chat server to run.

The CLI is a single Python file. It runs on Linux and macOS with Python 3.9 or newer and uses only the standard library. Interactive chat requires the `curses` module.

## Try it locally

These commands create a room in a temporary directory, send a message, and display the history.

```sh
git clone https://github.com/Donnykk/chillroom.git
cd chillroom
export CHILLROOM_ROOT="$(mktemp -d)"
python3 cli.py init demo
python3 cli.py send demo 'Hello, Chillroom!' --name alice
python3 cli.py history demo
```

Run `python3 cli.py join demo --name alice` to open the room. Press **Enter** to send and **Ctrl+D** at an empty prompt to leave.

## Documentation

- [Installation and deployment](docs/installation.md) covers user-local installation, offline distribution, shared directory permissions, and scheduled cleanup.
- [Quickstart](docs/quickstart.md) shows how to chat from two terminals and verify that messages reach another machine.

## Commands

| Command | What it does |
| --- | --- |
| `chillroom init ROOM` | Create a room. |
| `chillroom join ROOM` | Open an interactive chat. |
| `chillroom send ROOM [TEXT]` | Send a message. Omit `TEXT` to read it from standard input. |
| `chillroom history ROOM` | Show recent messages in chronological order. |
| `chillroom prune ROOM` | Preview expired files. Add `--apply` to remove them. |

Set `CHILLROOM_ROOT` to the shared directory or use `chillroom --root PATH COMMAND`. The filesystem controls room access. Each client supplies its own display name.
