#!/usr/bin/env python3
# Looking Glass IRC Bot - Developed by acidvegas in Python (https://git.supernets.org/acidvegas/looking-glass-irc)
# bot.py

import asyncio
import logging
import re
import socket
import time

try:
	import apv
except ImportError:
	raise ImportError('missing apv library (pip install apv)')

SERVER    = 'irc.supernets.org'
PORT      = 6697
SSL       = True
NICK      = 'looking_glass'
CHANNEL   = '#war'
PREFIX    = '@'
ADMIN     = 'acidvegas!~stillfree@most.dangerous.motherfuck'

IMAGE     = 'ircdocker'
CONTAINER = 'ircdocker'

max_lines    = 1000
max_timeout  = 120
flood_time   = 3
line_delay   = 0.05

DOCKER_RUN_ARGS = [
	'docker', 'run', '-d',
	'--name', CONTAINER,
	'--network', 'host',
	'--restart', 'unless-stopped',
	'--memory', '3g',
	'--memory-swap', '3g',
	'--cpus', '1',
	'--pids-limit', '256',
	'--cap-drop', 'ALL',
	'--cap-add', 'NET_RAW',
	'--cap-add', 'SETUID',
	'--cap-add', 'SETGID',
	'--cap-add', 'CHOWN',
	'--cap-add', 'DAC_OVERRIDE',
	'--cap-add', 'FOWNER',
	'--cap-add', 'NET_BIND_SERVICE',
	'--storage-opt', 'size=50G',
	'--hostname', socket.gethostname(),
	IMAGE,
]

ANSI_TO_IRC = {
	30: '01', 31: '04', 32: '03', 33: '08',
	34: '02', 35: '06', 36: '10', 37: '00',
	90: '14', 91: '04', 92: '09', 93: '08',
	94: '12', 95: '13', 96: '11', 97: '00',
}

MONITOR_INTERVAL = 30
THRESHOLDS       = (75, 80, 90, 100)
PIDS_LIMIT       = 256
PIDS_THRESHOLDS  = (50, 75, 90)

enabled = True
boot_time = time.time()
container_start_time = time.time()
last_cmd_time = 0
cmd_executed = False
flood_track = {}
flood_warned = {}

BOOBY_TRAPS = ['rm -rf /', ':(){ :|:& };:', '.fbi.gov', 'fbi.gov', '>{forking}']


def is_booby_trapped(cmd: str) -> bool:
	lower = cmd.lower()
	if 'rm ' in lower and ' -rf' in lower and '/' in lower:
		return True
	if ':(){ :|:& };:' in cmd:
		return True
	if 'fbi.gov' in lower:
		return True
	return False

# irc formatting
BOLD      = '\x02'
RESET     = '\x0f'
GREEN     = '\x0303'
RED       = '\x0304'
ORANGE    = '\x0307'
PINK      = '\x0313'
CYAN      = '\x0311'
GREY      = '\x0314'
BLUE      = '\x0312'


def ansi_to_irc(text: str) -> str:
	def _convert(m):
		codes = [int(c) for c in m.group(1).split(';') if c.isdigit()]
		out = ''
		for code in codes:
			if code == 0:
				out += '\x0f'
			elif code == 1:
				out += '\x02'
			elif code == 4:
				out += '\x1f'
			elif code in ANSI_TO_IRC:
				out += f'\x03{ANSI_TO_IRC[code]}'
		return out

	text = re.sub(r'\033\[([0-9;]*)m', _convert, text)
	text = re.sub(r'\033[\[\]()][?!>]?[0-9;]*[A-Za-z~]', '', text)
	text = re.sub(r'\033[()][A-Z0-9]', '', text)
	text = re.sub(r'\033[>=]', '', text)
	return text


def parse_source(raw: str) -> str:
	'''Extract nick!user@host from :nick!user@host'''
	return raw.lstrip(':')


def is_admin(source: str) -> bool:
	return source == ADMIN


def format_duration(seconds: float) -> str:
	d = int(seconds)
	days, d = divmod(d, 86400)
	hours, d = divmod(d, 3600)
	mins, secs = divmod(d, 60)
	parts = []
	if days:
		parts.append(f'{days}d')
	if hours:
		parts.append(f'{hours}h')
	if mins:
		parts.append(f'{mins}m')
	parts.append(f'{secs}s')
	return ' '.join(parts)


async def send(writer: asyncio.StreamWriter, data: str):
	writer.write(f'{data}\r\n'.encode())
	await writer.drain()


async def say(writer: asyncio.StreamWriter, text: str):
	await send(writer, f'PRIVMSG {CHANNEL} :{text}')


async def act(writer: asyncio.StreamWriter, text: str):
	await send(writer, f'PRIVMSG {CHANNEL} :\x01ACTION {text}\x01')


# --- container management ---

async def container_running() -> bool:
	proc = await asyncio.create_subprocess_exec(
		'docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
	)
	out, _ = await proc.communicate()
	return out.strip() == b'true'


async def destroy_container() -> str:
	logging.info('destroying container')
	proc = await asyncio.create_subprocess_exec(
		'docker', 'rm', '-f', CONTAINER,
		stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
	)
	await proc.wait()
	return 'container destroyed'


async def rebuild_container() -> str:
	global container_start_time, last_cmd_time, cmd_executed
	logging.info('rebuilding container')
	await destroy_container()

	start = await asyncio.create_subprocess_exec(
		*DOCKER_RUN_ARGS,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
	)
	out, _ = await start.communicate()

	if start.returncode == 0:
		container_start_time = time.time()
		last_cmd_time = 0
		cmd_executed = False
		logging.info('container rebuilt')
		return 'container rebuilt'
	else:
		msg = out.decode(errors='replace').strip()[:200]
		logging.error(f'rebuild failed: {msg}')
		return f'{RED}rebuild failed: {msg}{RESET}'


# --- command execution ---

current_proc = None
stopped = False


async def handle_cmd(cmd: str, writer: asyncio.StreamWriter, lock: asyncio.Lock, silent: bool = False):
	global current_proc, stopped, last_cmd_time, cmd_executed
	logging.info(f'running{"(silent)" if silent else ""}: {cmd}')
	stopped = False
	last_cmd_time = time.time()
	cmd_executed = True

	if not await container_running():
		await say(writer, f'{RED}error: container is not running. use {PREFIX}rebuild{RESET}')
		return

	if silent:
		await act(writer, f'{CYAN}executing command...{RESET}')

	async with lock:
		proc = await asyncio.create_subprocess_exec(
			'docker', 'exec',
			'-e', 'TERM=xterm-256color',
			'-e', 'DEBIAN_FRONTEND=noninteractive',
			'-e', 'CLICOLOR_FORCE=1',
			CONTAINER,
			'bash', '-c', 'source /root/.bashrc 2>/dev/null; eval "$1"', '_', cmd,
			stdin=asyncio.subprocess.DEVNULL,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.STDOUT,
		)
		current_proc = proc

		lines_sent = 0
		try:
			while not stopped:
				line = await asyncio.wait_for(proc.stdout.readline(), timeout=max_timeout)
				if not line:
					break
				lines_sent += 1
				if silent:
					continue
				raw = ansi_to_irc(line.decode(errors='replace')).rstrip()
				if not raw.strip():
					continue
				indent = len(raw) - len(raw.lstrip(' '))
				text = '\u00a0' * indent + raw.lstrip(' ') if indent else raw
				if lines_sent <= max_lines:
					logging.info(f'output: {text[:200]}')
					await say(writer, text)
					await asyncio.sleep(line_delay)
				else:
					proc.kill()
					logging.info('max lines reached, killing process')
					break
		except asyncio.TimeoutError:
			proc.kill()
			logging.warning(f'command timed out: {cmd}')
			await say(writer, f'{RED}error: command timed out{RESET}')
		finally:
			current_proc = None

		await proc.wait()
		rc = proc.returncode

		if stopped:
			logging.info(f'stopped: {cmd} ({lines_sent} lines)')
			await act(writer, f'{CYAN}cmd finished:{RESET} {ORANGE}cancelled{RESET}')
		elif silent:
			if rc == 0:
				await say(writer, f'{GREEN}done:{RESET} {GREY}{cmd}{RESET} {GREEN}({lines_sent} lines){RESET}')
			else:
				await say(writer, f'{RED}failed (exit {rc}):{RESET} {GREY}{cmd}{RESET}')
			await act(writer, f'{CYAN}cmd finished:{RESET} {GREEN}{rc}{RESET}' if rc == 0 else f'{CYAN}cmd finished:{RESET} {RED}{rc}{RESET}')
		else:
			if lines_sent == 0:
				await say(writer, f'{GREY}(no output){RESET}')
			elif lines_sent > max_lines:
				await say(writer, f'{ORANGE}showing {max_lines} lines out of {lines_sent} total. killing process...{RESET}')
			await act(writer, f'{CYAN}cmd finished:{RESET} {GREEN}{rc}{RESET}' if rc == 0 else f'{CYAN}cmd finished:{RESET} {RED}{rc}{RESET}')
		logging.info(f'done: {cmd} ({lines_sent} lines, exit {rc})')


# --- stats ---

async def get_container_stats():
	if not await container_running():
		return None

	proc = await asyncio.create_subprocess_exec(
		'docker', 'stats', '--no-stream', '--format',
		'{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}\t{{.PIDs}}',
		CONTAINER,
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
	)
	out, _ = await proc.communicate()
	if proc.returncode != 0:
		return None

	parts = out.decode(errors='replace').strip().split('\t')
	if len(parts) < 4:
		return None

	cpu_pct = float(parts[0].rstrip('%'))
	mem_pct = float(parts[1].rstrip('%'))
	mem_usage = parts[2]
	pids = int(parts[3])

	disk_proc = await asyncio.create_subprocess_exec(
		'docker', 'exec', CONTAINER, 'df', '-h', '--output=used,size,pcent', '/',
		stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
	)
	disk_out, _ = await disk_proc.communicate()
	disk_lines = disk_out.decode(errors='replace').strip().splitlines()
	disk_parts = disk_lines[-1].split() if len(disk_lines) >= 2 else []
	disk_used = disk_parts[0] if len(disk_parts) >= 1 else '?'
	disk_total = disk_parts[1] if len(disk_parts) >= 2 else '?'
	disk_pct = float(disk_parts[2].rstrip('%')) if len(disk_parts) >= 3 else 0.0

	return {
		'cpu': cpu_pct,
		'mem': mem_pct,
		'mem_usage': mem_usage,
		'disk_pct': disk_pct,
		'disk_used': disk_used,
		'disk_total': disk_total,
		'pids': pids,
	}


def check_thresholds(value: float, name: str, detail: str, alerted: dict) -> str | None:
	triggered = None
	for t in THRESHOLDS:
		if value >= t and not alerted.get((name, t)):
			alerted[(name, t)] = True
			triggered = t
		elif value < t and alerted.get((name, t)):
			alerted[(name, t)] = False
	if triggered:
		return f'{ORANGE}warning: {name} at {value:.0f}% {detail}{RESET}'
	return None


async def monitor_loop(writer: asyncio.StreamWriter):
	alerted = {}
	while True:
		await asyncio.sleep(MONITOR_INTERVAL)
		try:
			stats = await get_container_stats()
			if not stats:
				continue

			pids_pct = (stats['pids'] / PIDS_LIMIT) * 100

			for msg in (
				check_thresholds(stats['cpu'], 'cpu', '', alerted),
				check_thresholds(stats['mem'], 'memory', f"({stats['mem_usage']})", alerted),
				check_thresholds(stats['disk_pct'], 'disk', f"({stats['disk_used']}/{stats['disk_total']})", alerted),
				check_thresholds(pids_pct, 'pids', f"({stats['pids']}/{PIDS_LIMIT})", alerted),
			):
				if msg:
					logging.warning(msg)
					await say(writer, msg)

			if stats['pids'] >= PIDS_LIMIT - 5:
				await say(writer, f'{RED}process limit critical ({stats["pids"]}/{PIDS_LIMIT}) - self destructing{RESET}')
				logging.warning(f'pids at {stats["pids"]}/{PIDS_LIMIT}, rebuilding container')
				await rebuild_container()
				await say(writer, f'{GREEN}container rebuilt after process limit breach{RESET}')

			if cmd_executed and last_cmd_time and time.time() - last_cmd_time > 86400:
				logging.info('container idle for 24h, recycling')
				await act(writer, f'{PINK}recycling idle container...{RESET}')
				await rebuild_container()
				await act(writer, f'{PINK}container recycled{RESET}')

		except Exception as e:
			logging.error(f'monitor error: {e}')


# --- irc bot ---

async def bot():
	global enabled, stopped, max_lines, max_timeout, flood_time, line_delay

	logging.info(f'connecting to {SERVER}:{PORT} (ssl={SSL})')

	if SSL:
		import ssl as _ssl
		ctx = _ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = _ssl.CERT_NONE
		reader, writer = await asyncio.open_connection(SERVER, PORT, ssl=ctx)
	else:
		reader, writer = await asyncio.open_connection(SERVER, PORT)

	logging.info('connected')
	await send(writer, f'NICK {NICK}')
	await send(writer, f'USER {NICK} 0 * :{NICK}')

	joined = False
	cmd_lock = asyncio.Lock()
	monitor_task = None

	while True:
		try:
			line = await asyncio.wait_for(reader.readline(), timeout=300)
		except asyncio.TimeoutError:
			await send(writer, 'PING :keepalive')
			continue

		if not line:
			break

		line = line.decode(errors='replace').strip()

		parts = line.split()

		if parts[0] == 'PING':
			await send(writer, 'PONG ' + parts[1])
			continue

		if len(parts) >= 2 and parts[1] == '001' and not joined:
			await send(writer, f'MODE {NICK} +BdDg')
			logging.info(f'registered, joining {CHANNEL} in 10s')
			await asyncio.sleep(10)
			await send(writer, f'JOIN {CHANNEL}')
			joined = True
			monitor_task = asyncio.create_task(monitor_loop(writer))
			continue

		if len(parts) >= 4 and parts[1] == 'KICK' and parts[3] == NICK:
			logging.info(f'kicked from {parts[2]}, rejoining in 3s')
			await asyncio.sleep(3)
			await send(writer, f'JOIN {parts[2]}')
			continue

		if len(parts) >= 4 and parts[1] == 'INVITE':
			target = parts[3].lstrip(':')
			if target == CHANNEL:
				logging.info(f'invited to {CHANNEL}, joining')
				await send(writer, f'JOIN {CHANNEL}')
			continue

		if len(parts) < 4:
			continue

		source = parse_source(parts[0])

		# --- admin PM commands ---
		if parts[1] == 'PRIVMSG' and parts[2] == NICK:
			pm = line.split(' :', 1)[1] if ' :' in line else ''

			if is_admin(source) and pm.startswith(f'{PREFIX}raw '):
				raw_line = pm[len(f'{PREFIX}raw '):]
				logging.info(f'admin raw: {raw_line}')
				await send(writer, raw_line)
			continue

		# --- channel commands ---
		if parts[1] != 'PRIVMSG' or parts[2] != CHANNEL:
			continue

		msg = line.split(' :', 1)[1] if ' :' in line else ''

		if not msg.startswith(PREFIX):
			continue

		now = time.time()
		nick = source.split('!')[0]
		last = flood_track.get(nick, 0)
		if now - last < flood_time:
			flood_track[nick] = now
			if not flood_warned.get(nick):
				await say(writer, f'{RED}slow down nerd{RESET}')
				flood_warned[nick] = True
			continue
		flood_track[nick] = now
		flood_warned[nick] = False

		if msg == f'{PREFIX}help':
			help_lines = [
				(f'{PREFIX}<command>',        'run a shell command in the container'),
				(f'{PREFIX}silent <command>', 'run a command with no output'),
				(f'{PREFIX}stop',             'kill the running command'),
				(f'{PREFIX}rebuild',          'destroy and recreate the container'),
				(f'{PREFIX}stats',            'show container resource usage'),
			]
			if is_admin(source):
				help_lines += [
					(f'{PREFIX}on',                     'enable the bot and rebuild container'),
					(f'{PREFIX}off',                    'disable the bot and destroy container'),
					(f'{PREFIX}settings <key> <val>',   'change max_lines/timeout/flood_time/line_delay'),
					(f'{PREFIX}raw <line>',             'send raw irc data (pm only)'),
				]
			for cmd_name, desc in help_lines:
				padded = cmd_name.ljust(25).replace(' ', '\u00a0')
				await say(writer, f'\u00a0\u00a0{GREEN}{padded}{RESET}\u00a0{GREY}{desc}{RESET}')
			await say(writer, f'\u00a0\u00a0{GREY}limits:\u00a0{max_lines}\u00a0max\u00a0lines,\u00a0{max_timeout}s\u00a0timeout{RESET}')
			continue

		# --- admin channel commands ---
		if is_admin(source):
			if msg == f'{PREFIX}off':
				enabled = False
				stopped = True
				if current_proc and current_proc.returncode is None:
					current_proc.kill()
				result = await destroy_container()
				await say(writer, f'{RED}{result} - bot disabled{RESET}')
				logging.info('bot disabled by admin')
				continue

			if msg == f'{PREFIX}on':
				enabled = True
				result = await rebuild_container()
				await say(writer, f'{GREEN}{result} - bot enabled{RESET}')
				logging.info('bot enabled by admin')
				continue

			if msg.startswith(f'{PREFIX}settings'):
				settings_parts = msg.split()
				if len(settings_parts) == 3:
					key, val = settings_parts[1], settings_parts[2]
					try:
						val_float = float(val)
						if val_float < 0:
							raise ValueError
					except ValueError:
						await say(writer, f'{RED}invalid value: must be a non-negative number{RESET}')
						continue
					if key == 'max_lines':
						max_lines = int(val_float)
						await say(writer, f'{GREEN}max_lines set to {max_lines}{RESET}')
						logging.info(f'admin set max_lines to {max_lines}')
					elif key == 'timeout':
						max_timeout = int(val_float)
						await say(writer, f'{GREEN}timeout set to {max_timeout}s{RESET}')
						logging.info(f'admin set timeout to {max_timeout}')
					elif key == 'flood_time':
						flood_time = val_float
						await say(writer, f'{GREEN}flood_time set to {flood_time}s{RESET}')
						logging.info(f'admin set flood_time to {flood_time}')
					elif key == 'line_delay':
						line_delay = val_float
						await say(writer, f'{GREEN}line_delay set to {line_delay}s{RESET}')
						logging.info(f'admin set line_delay to {line_delay}')
					else:
						await say(writer, f'{RED}unknown setting: {key} {GREY}(max_lines, timeout, flood_time, line_delay){RESET}')
				else:
					await say(writer,
						f'{BOLD}settings:{RESET} '
						f'{GREEN}max_lines{RESET}={BOLD}{max_lines}{RESET} {GREY}|{RESET} '
						f'{GREEN}timeout{RESET}={BOLD}{max_timeout}s{RESET} {GREY}|{RESET} '
						f'{GREEN}flood_time{RESET}={BOLD}{flood_time}s{RESET} {GREY}|{RESET} '
						f'{GREEN}line_delay{RESET}={BOLD}{line_delay}s{RESET}'
					)
				continue

		if not enabled:
			await say(writer, f'{GREY}bot is disabled{RESET}')
			continue

		# --- public commands ---
		if msg == f'{PREFIX}stats':
			stats = await get_container_stats()
			if stats:
				uptime = format_duration(time.time() - boot_time)
				hostname = socket.gethostname()
				await say(writer,
					f'{BOLD}host:{RESET} {GREEN}{hostname}{RESET} {GREY}|{RESET} '
					f'{BOLD}uptime:{RESET} {GREEN}{uptime}{RESET} {GREY}|{RESET} '
					f'{BOLD}cpu:{RESET} {GREEN}{stats["cpu"]:.1f}%{RESET} {GREY}|{RESET} '
					f'{BOLD}mem:{RESET} {GREEN}{stats["mem"]:.1f}%{RESET} {GREY}({stats["mem_usage"]}){RESET} {GREY}|{RESET} '
					f'{BOLD}disk:{RESET} {GREEN}{stats["disk_pct"]:.0f}%{RESET} {GREY}({stats["disk_used"]}/{stats["disk_total"]}){RESET} {GREY}|{RESET} '
					f'{BOLD}pids:{RESET} {GREEN}{stats["pids"]}{RESET}{GREY}/{PIDS_LIMIT}{RESET}'
				)
			else:
				await say(writer, f'{RED}container is not running{RESET}')
			continue

		if msg == f'{PREFIX}stop':
			if current_proc and current_proc.returncode is None:
				stopped = True
				current_proc.kill()
				logging.info('process killed by user')
				await say(writer, f'{ORANGE}killed{RESET}')
			else:
				await say(writer, f'{GREY}nothing running{RESET}')
			continue

		if msg == f'{PREFIX}rebuild':
			if cmd_lock.locked():
				stopped = True
				if current_proc and current_proc.returncode is None:
					current_proc.kill()
			result = await rebuild_container()
			await say(writer, f'{GREEN}{result}{RESET}')
			continue

		if msg.startswith(f'{PREFIX}silent '):
			cmd = msg[len(f'{PREFIX}silent '):]
			if cmd.strip():
				if is_booby_trapped(cmd):
					await say(writer, f'{RED}nice try nerd{RESET}')
				elif cmd_lock.locked():
					await say(writer, f'{GREY}busy: use {PREFIX}stop to kill it{RESET}')
				else:
					asyncio.create_task(handle_cmd(cmd, writer, cmd_lock, silent=True))
			continue

		if msg.startswith(PREFIX):
			cmd = msg[len(PREFIX):]
			if cmd.strip():
				if is_booby_trapped(cmd):
					await say(writer, f'{RED}nice try nerd{RESET}')
				elif cmd_lock.locked():
					await say(writer, f'{GREY}busy: use {PREFIX}stop to kill it{RESET}')
				else:
					asyncio.create_task(handle_cmd(cmd, writer, cmd_lock))

	if monitor_task:
		monitor_task.cancel()
	writer.close()


async def main():
	while True:
		try:
			await bot()
		except Exception as e:
			logging.error(f'disconnected: {e}, reconnecting in 15s')
		await asyncio.sleep(15)


if __name__ == '__main__':
	import argparse

	# Parse arguments
	parser = argparse.ArgumentParser(description='Connect to an IRC server.')
	parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode.')
	args = parser.parse_args()

	# Setup logging
	if args.debug:
		apv.setup_logging(level='DEBUG', show_details=True)
		logging.debug('Debug logging enabled')
	else:
		apv.setup_logging(level='INFO', show_details=True)

	asyncio.run(main())
