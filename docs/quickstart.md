# Quickstart

The examples use the installed `chillroom` command. From a source checkout, you can use `python3 cli.py` in its place. See [installation and deployment](installation.md) for setup.

## Chat from two terminals

In terminal A, create a temporary directory, save the path it prints, and open the `demo` room as Alice.

```sh
export CHILLROOM_ROOT="$(mktemp -d)"
printf '%s\n' "$CHILLROOM_ROOT"
chillroom init demo
chillroom join demo --name alice
```

In terminal B, replace the example path with the one printed by terminal A and open the same room as Bob.

```sh
export CHILLROOM_ROOT=/path/from/terminal-a
chillroom join demo --name bob
```

Type a message and press **Enter**. The other terminal should display it. Press **Ctrl+D** at an empty prompt to leave. By default, `join` loads up to 20 recent messages and polls every 3 seconds. Use `--limit 0` to start without history or `--poll 5` to poll every 5 seconds.

## Send messages and view history

```sh
chillroom send demo 'The handoff is ready' --name alice
printf 'I have the notes.\nI will take it from here.\n' | chillroom send demo --name bob
chillroom history demo --limit 10
```

Set `CHILLROOM_NAME` for a default display name. With neither `--name` nor `CHILLROOM_NAME` set, Chillroom uses your login name. Messages can be up to 4,096 UTF-8 bytes. Room names can be up to 64 characters and use ASCII letters, digits, underscores, or hyphens. Start the name with a letter or digit.

## Verify chat across machines

Set `CHILLROOM_ROOT` on both machines to their local mount paths for the same shared directory. On machine A, create `lobby` and send a test message.

```sh
# Machine A
export CHILLROOM_ROOT=/mnt/shared/chillroom
umask 007
chillroom init lobby
chillroom send lobby 'Hello from machine A' --name node-a
```

On machine B, use its path to the same directory. Read the first message, then send a reply.

```sh
# Machine B
export CHILLROOM_ROOT=/work/shared/chillroom
umask 007
chillroom history lobby --limit 5
chillroom send lobby 'Machine B received it' --name node-b
```

Run `chillroom history lobby --limit 5` again on machine A to see the reply. To chat interactively, run `chillroom join lobby --name node-a` on A and `chillroom join lobby --name node-b` on B.

If messages are slow to appear, allow for filesystem caching and retry. If they remain missing, run `findmnt -T "$CHILLROOM_ROOT"` on Linux to confirm the mount on each machine, then check the directory permissions and shared group mapping.
