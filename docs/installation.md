# Installation and deployment

## Requirements

- Linux or macOS with Python 3.9 or newer.
- A terminal and Python's `curses` module for interactive chat. Run `python3 -c 'import curses'` to check for the module.
- For chat across machines, a shared filesystem that supports atomic renames within a directory. Participants need read and write access to the same directory.

## Install for your user

```sh
git clone https://github.com/Donnykk/chillroom.git
cd chillroom
mkdir -p "$HOME/.local/bin"
install -m 0755 cli.py "$HOME/.local/bin/chillroom"
export PATH="$HOME/.local/bin:$PATH"
chillroom --help
```

Add the `PATH` export to your shell startup file to make `chillroom` available in new terminals. You can also run `python3 cli.py` from the checkout.

## Install offline

Download [cli.py](../cli.py) on a connected machine and distribute it through your usual image or artifact delivery process. Use the same revision on each machine. Once the file is available on the destination, run the following from its directory.

```sh
mkdir -p "$HOME/.local/bin"
install -m 0755 cli.py "$HOME/.local/bin/chillroom"
"$HOME/.local/bin/chillroom" --help
```

If the script itself is on the share, each participant can run `python3 /path/to/cli.py` from their machine.

## Set up shared storage

Choose a dedicated chat directory on the share. On each machine, point `CHILLROOM_ROOT` to the existing local path to that directory. Mount paths can differ as long as they lead to the same storage.

Give participants read, write, and traversal permissions. The Linux example below assumes an existing group named `chillroom-users`. Substitute your group and mount path.

```sh
sudo install -d -m 2770 -g chillroom-users /mnt/shared/chillroom
```

The setgid bit lets new directories and files inherit the shared group. Make sure the storage sees a consistent group identity across machines. Each writer should use `umask 007` or equivalent permissions managed through storage ACLs.

Have one participant create the room.

```sh
export CHILLROOM_ROOT=/mnt/shared/chillroom
umask 007
chillroom init lobby
```

Follow the [cross-machine check](quickstart.md#verify-chat-across-machines) before inviting others. To override the environment variable for a single command, put `--root PATH` before the subcommand.

### Message visibility on NFS and SFS

Clients poll every 3 seconds by default. NFS directory and lookup caches can delay when another machine sees a new file. In one two-machine SFS test over NFSv3, the first message took about 30 seconds to appear with the default cache settings. In a separate test using `actimeo=1` and `lookupcache=none`, eight messages appeared in 2.94 to 3.12 seconds.

Measure latency on your own mount before changing cache settings or the polling interval. Shorter intervals can increase metadata traffic on the share. [Linux NFS manual](https://man7.org/linux/man-pages/man5/nfs.5.html#DATA_AND_METADATA_COHERENCE)

## Configure cleanup

The default retention window includes today and the previous six UTC calendar dates. Temporary message files older than 24 hours are eligible for cleanup. Preview the count before applying the changes.

```sh
chillroom prune lobby
chillroom prune lobby --apply
```

Schedule cleanup once per room using an account with permission to delete files from the room and its dated subdirectories. This Linux cron example runs daily. Replace the Python, script, and shared directory paths with the paths on the machine running the job.

```cron
25 3 * * * /usr/bin/python3 /opt/chillroom/cli.py --root /mnt/shared/chillroom prune lobby --apply
```

Use `--keep-days 14` to change message retention, `--temp-hours 48` to change the expiry time for temporary files, or `--max-files 1000` to limit the number of files processed per run.
