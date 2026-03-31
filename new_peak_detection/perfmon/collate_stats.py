#!/usr/bin/python3

from argparse import ArgumentParser
import threading, time
import re
from pyroute2 import IPRoute

def periodic_task ():
	global prev_packets_rx
	global prev_packets_tx
	global prev_bytes_rx
	global prev_bytes_tx
	global ipr
	global iface_idx

# Get link statistics - packets sent/recieved, bytes sent/recieved

	link_info = ipr.get_links(index=iface_idx)[0]
	
	stats = link_info.get ('stats64', link_info.get('stats', {}))
	
	packets_tx = stats.get('tx_packets', 0)
	packets_rx = stats.get('rx_packets', 0)
	bytes_tx = stats.get('tx_bytes', 0)
	bytes_rx = stats.get('rx_bytes', 0)

	print ("%f %i %i %i %i" % (time.time (), packets_rx - prev_packets_rx, bytes_rx - prev_bytes_rx, packets_tx - prev_packets_tx, bytes_tx - prev_bytes_tx), end='')

	prev_packets_rx = packets_rx
	prev_bytes_rx = bytes_rx
	prev_packets_tx = packets_tx
	prev_bytes_tx = bytes_tx

# Retrieve qdisc information for the interface so we can get queue occupancy info for the specified device

	qdisc_info = []
	
	for msg in ipr.get_qdiscs (index=iface_idx):
		# Extract relevant qdisc stats
		if 'attrs' in msg:
			attrs = dict (msg ['attrs'])
			qdisc_type = attrs.get ('TCA_KIND', 'Unknown')
			
			if qdisc_type != 'Unknown':
				stats = attrs.get ('TCA_STATS', None)
			
				if stats:
					qdisc_info.append ({
						'qdisc_type': qdisc_type,
						'bytes': stats.get ('bytes', 0),
						'packets': stats.get ('packets', 0),
						'drops': stats.get ('drops', 0),
						'overlimits': stats.get ('overlimits', 0),
						'backlog': stats.get ('backlog', 0)
					})

	if qdisc_info:
		for qdisc in qdisc_info:
			print (" %s %i %i %i %i %i" % (qdisc['qdisc_type'], qdisc['backlog'], qdisc['bytes'], qdisc['packets'], qdisc['drops'], qdisc['overlimits']), end='')
#			print (f"Qdisc Type: {qdisc['qdisc_type']}")
#			print (f"  Bytes: {qdisc['bytes']}")
#			print (f"  Packets: {qdisc['packets']}")
#			print (f"  Drops: {qdisc['drops']}")
#			print (f"  Overlimits: {qdisc['overlimits']}")
#			print (f"  Backlog: {qdisc['backlog']}")
	else:
		print (f"No qdisc info available for {interface}.")
		
	print ('')

parser = ArgumentParser ("Periodically extract packet stats from /proc/net/dev on specified interface")
parser.add_argument ('-d', '--device', help = "Specify network interface")
parser.add_argument ('-i', '--interval', default = 20, type = int, help = "Sampling interval in milliseconds")
parser.add_argument ('-t', '--time', default = 60, type = int, help = "Total run time in seconds")
args = parser.parse_args ()

ipr = IPRoute ()

# Find the index of the interface (e.g. eth0)
try:
	iface_idx = ipr.link_lookup (ifname=args.device)[0]
except IndexError:
	print (f"Error: interface {interface} not found.")
	exit (-1)

prev_packets_rx = 0
prev_packets_tx = 0
prev_bytes_rx = 0
prev_bytes_tx = 0

print ('# time, rx_packets, rx_bytes, tx_packets, tx_bytes, qdisc, bytes, packets, drops, overlimits, BACKLOG (queue depth), repeat...')

ticker = threading.Event()

WAIT_TIME_SECONDS = args.interval / 1000

t0 = time.time()

while not ticker.wait (WAIT_TIME_SECONDS):
	periodic_task ()
	
	if (time.time() - t0) > args.time:
		break
