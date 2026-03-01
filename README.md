# IRCtainer
> IRC bot that lets the channel run whatever they want in a Docker container.

Designed to sit on a remote box and give your channel a shared shell for recon, scanning, and general screwing around over IRC. The container runs with `--network host`, so users can install and run anything that binds to the network — spin up an nginx instance, run a listener, whatever.

ANSI colors from command output are translated to IRC colors on the fly. The container image comes with [grc](https://github.com/garabik/grc) and color-forced aliases pre-configured, so tools like `ls`, `ping`, `nmap`, `traceroute`, etc. display in full color on IRC out of the box.

## Requirements
- [Docker](https://docs.docker.com/engine/install/)
- [Python 3](https://python.org/)
  - [apv](https://pypi.org/project/apv/)
- [xfsprogs](https://xfs.wiki.kernel.org/) *(for disk quota support with Docker)*

## Commands

| Command             | Description                          |
| ------------------- | ------------------------------------ |
| `@<command>`        | Run a shell command in the container |
| `@silent <command>` | Run a command with no output         |
| `@stop`             | Kill the running command             |
| `@rebuild`          | Destroy and recreate the container   |
| `@stats`            | Show container resource usage        |

### Admin Only

| Command                 | Description                                                  |
| ----------------------- | ------------------------------------------------------------ |
| `@on`                   | Enable the bot and rebuild container                         |
| `@off`                  | Disable the bot and destroy container                        |
| `@settings <key> <val>` | Change `max_lines` / `timeout` / `flood_time` / `line_delay` |
| `@raw <line>`           | Send raw IRC data *(PM only)*                                |

## Setup

Initialize the XFS-backed Docker storage *(one-time)*:
```sh
./setup.sh init
```

Build the container image:
```sh
./setup.sh build
```

Start the container and bot:
```sh
./setup.sh run
```

Stop the bot:
```sh
./setup.sh stop
```

Destroy everything:
```sh
./setup.sh nuke
```

Edit the connection settings at the top of `irctainer.py` before running.

## Container Limits

| Resource | Limit  |
| -------- | ------ |
| Memory   | 3 GB   |
| CPU      | 1 core |
| Disk     | 50 GB  |
| PIDs     | 256    |

The bot monitors resource usage and will auto-rebuild the container if the process limit is hit. Idle containers are recycled after 24 hours.

## Todo
- Create an Incus variant to be able to change which engine is used *(Incus allows systemd and other features that Docker does not)*
- Document grc and color tricks
- Possibly allow other images to be ran directly off Docker

---

###### Mirrors: [SuperNETs](https://git.supernets.org/acidvegas/irctainer) • [GitHub](https://github.com/acidvegas/irctainer) • [GitLab](https://gitlab.com/acidvegas/irctainer) • [Codeberg](https://codeberg.org/acidvegas/irctainer)
