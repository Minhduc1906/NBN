#!/usr/bin/python3

import os
import sys
import math
import json
import argparse

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
parser.add_argument ('-c', '--config', default = "stats_collection.json", help = "Specify JSON config file (see stats_collection.json example)")
parser.add_argument ('-d', '--duration', default = 100, type = ranged_type (int, 0, math.inf), help = "Specify collection duration in seconds")
parser.add_argument ('-i', '--interval', default = 20, type = ranged_type (int, 0, math.inf), help = "Specify collection interval in milliseconds")
parser.add_argument ('-n', '--name', default = "test", help = "Specify name of the test case")

args = parser.parse_args ()

with open (args.config) as f:
	interfaces = json.load (f)

cwd = os.getcwd()

pids = []

for host in interfaces:
	print ('Host: %s' % host['hostname'])

	for iface in host['interfaces']:
		print ('Interface: %s' % iface)

		pid = os.fork()

		if pid:
			pids.append ({
				'pid': pid,
				'host': host,
				'interface': iface
			})

			print ('Started stats collection on host %s interface %s' % (host['hostname'], iface))
		else:
			os.system ('ssh -o StrictHostKeyChecking=no root@%s PATH=$PATH:%s collate_stats.py --time %s --device %s --interval %s > %s_%s_%s.log' % (host['hostname'], cwd, args.duration, iface, args.interval, args.name, host['hostname'], iface))
			exit (0)

print ('Waiting (approximately %s seconds) for pending tasks to complete' % args.duration)

for pid in pids:
	try:
		os.waitpid (-1, 0)
		print ('Completed on host %s interface %s' % (pid['host'], pid['interface']), file = sys.stderr)
	except ChildProcessError:
		print ('All done', file = sys.stderr)
