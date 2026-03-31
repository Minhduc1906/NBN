#!/usr/bin/python3

import os
import sys
import math
import json
import argparse
import signal

# Parameters - make these command-line arguments later
def ranged_type (value_type, min_value, max_value):
	def range_checker(arg: str):
		try:
			f = value_type(arg)
		except ValueError:
			raise argparse.ArgumentTypeError (f'must be a valid {value_type}')

		if f < min_value or f > max_value:
			raise argparse.ArgumentTypeError (f'must be within range [{min_value}, {max_value}]')

		return f

# Return function handle to checking function
	return range_checker

parser = argparse.ArgumentParser ("Collect stats from hosts/interfaces specified in a JSON config file (stats_collection.json by default)")
parser.add_argument ('-t', '--tgconfig', default = "stats_collection.json", help = "Specify JSON config file (see stats_collection.json example)")
parser.add_argument ('-c', '--capconfig', default = "tests.json", help = "Specify JSON config file (see tests.json example)")
parser.add_argument ('-d', '--duration', default = 100, type = ranged_type (int, 0, math.inf), help = "Specify collection duration in seconds")
parser.add_argument ('-i', '--interval', default = 20, type = ranged_type (int, 0, math.inf), help = "Specify collection interval in milliseconds")
parser.add_argument ('-n', '--name', default = "test", help = "Specify name of the test case")

args = parser.parse_args ()

with open (args.capconfig) as f:
	interfaces = json.load (f)

cwd = os.getcwd()

pids = []

def signal_handler(sig, frame):
	print('Interrupted: terminating child processes')
	
	for pid in pids:
		os.kill (pid['pid'], signal.SIGKILL)
		print ('Process [%i] terminated' % pid['pid'])

	sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

for host in interfaces:
	print ('Host: %s' % host['hostname'])

	for iface in host['interfaces']:
		print ('Interface: %s' % iface)

		pid = os.fork()

		if pid:
			pids.append ({
				'pid': pid,
				'host': host,
				'interface': iface,
				'name': 'capture process'
			})

			print ('Started stats collection on host %s interface %s' % (host['hostname'], iface))
		else:
			os.system ('ssh -t -o StrictHostKeyChecking=no root@%s PATH=$PATH:%s collate_stats.py --time %s --device %s --interval %s > %s_%s_%s.log' % (host['hostname'], cwd, args.duration, iface, args.interval, args.name, host['hostname'], iface))
			exit (0)

with open (args.tgconfig) as f:
	tests = json.load (f)

for test in tests:
	print ('Starting test: %s' % test['testname']);

	if 'host1' in test:

# Start host1 process (generally server) first
		pid = os.fork()

		if pid:
			pids.append ({
				'pid': pid,
				'name': 'host1 trafgen process',
				'host': test['host1']['name']
			})
		else:
			os.system ('ssh -t -o StrictHostKeyChecking=no root@%s "PATH=$PATH:%s sleep %i ; %s 2>&1 > /dev/null"' % (test['host1']['name'], cwd, test['host1']['start_time'], test['host1']['cmd']))
			exit (0)

# Start host2 process

	if 'host2' in test:
		pid = os.fork()

		if pid:
			pids.append ({
				'pid': pid,
				'name': 'host2 trafgen process',
				'host': test['host2']['name']
			})
		else:
			os.system ('ssh -t -o StrictHostKeyChecking=no root@%s "PATH=$PATH:%s sleep %i ; %s 2>&1 > /dev/null"' % (test['host2']['name'], cwd, test['host2']['start_time'], test['host2']['cmd']))
			exit (0)

print ('Waiting (approximately %s seconds) for all pending tasks to complete' % args.duration)

#for pid in pids:
while True:
	try:
#		os.waitpid (-1, 0)
		status = os.wait() 
		print ('Completed process with PID %i' % (status[0]), file = sys.stderr)
	except ChildProcessError:
		print ('All done', file = sys.stderr)
		break

