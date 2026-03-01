#!/bin/sh
# Looking Glass IRC Bot - Developed by acidvegas in Python (https://git.supernets.org/acidvegas/looking-glass-irc)
# setup.sh

set -e

IMAGE="ircdocker"
CONTAINER="ircdocker"
BOT_PID="/tmp/ircdocker_bot.pid"

case "${1:-help}" in
	init)
		# give docker its own xfs filesystem with project quotas (run once)
		DOCKER_IMG="/docker.img"
		DOCKER_DIR="/var/lib/docker"

		systemctl stop docker docker.socket
		rm -rf "$DOCKER_DIR"

		apt-get install -y xfsprogs
		truncate -s 200G "$DOCKER_IMG"
		mkfs.xfs "$DOCKER_IMG"
		mkdir -p "$DOCKER_DIR"
		mount -o loop,pquota "$DOCKER_IMG" "$DOCKER_DIR"

		grep -q "$DOCKER_IMG" /etc/fstab || \
			echo "$DOCKER_IMG $DOCKER_DIR xfs loop,pquota 0 0" >> /etc/fstab

		tee /etc/docker/daemon.json >/dev/null <<'CONF'
{
	"storage-driver": "overlay2"
}
CONF
		systemctl start docker
		echo "docker configured with xfs quota support. now run: $0 build"
		;;
	build)
		docker build --network host -t "$IMAGE" .
		echo "image '$IMAGE' built. run with: $0 run"
		;;
	run)
		docker rm -f "$CONTAINER" 2>/dev/null || true
		docker run -d \
			--name "$CONTAINER" \
			--hostname "$(hostname)" \
			--network host \
			--restart unless-stopped \
			--memory 3g \
			--memory-swap 3g \
			--cpus 1 \
			--pids-limit 256 \
			--cap-drop ALL \
			--cap-add NET_RAW \
			--cap-add SETUID \
			--cap-add SETGID \
			--cap-add CHOWN \
			--cap-add DAC_OVERRIDE \
			--cap-add FOWNER \
			--cap-add NET_BIND_SERVICE \
			--storage-opt size=50G \
			"$IMAGE"
		echo "container '$CONTAINER' started"

		if [ -f "$BOT_PID" ] && kill -0 "$(cat "$BOT_PID")" 2>/dev/null; then
			echo "bot already running (pid $(cat "$BOT_PID"))"
		else
			python3 bot.py &
			echo $! > "$BOT_PID"
			echo "bot started (pid $!)"
		fi
		;;
	stop)
		if [ -f "$BOT_PID" ]; then
			kill "$(cat "$BOT_PID")" 2>/dev/null || true
			rm -f "$BOT_PID"
			echo "bot stopped"
		else
			echo "bot not running"
		fi
		;;
	nuke)
		if [ -f "$BOT_PID" ]; then
			kill "$(cat "$BOT_PID")" 2>/dev/null || true
			rm -f "$BOT_PID"
		fi
		docker rm -f "$CONTAINER" 2>/dev/null || true
		echo "bot and container destroyed"
		;;
	*)
		echo "usage: $0 {init|build|run|stop|nuke}"
		exit 1
		;;
esac
