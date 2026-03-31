#!/usr/bin/env python3
#
# Code based on i2rs-wg by Edwin Cordeiro. See https://github.com/i2rs-wg for he original script.
#
# Extensively modified by Daniel R. Franklin for UTS 49202 Communication Protocols labs.
#
# Report bugs to Daniel.Franklin@uts.edu.au
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#
# On Debian systems, the full text of the GNU General Public License version
# 2 can be found in the file
#
# /usr/share/common-licenses/GPL-2'.

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.log import lg, info, setLogLevel
from mininet.util import dumpNodeConnections, quietRun, moveIntf
from mininet.cli import CLI
from mininet.node import Switch, OVSKernelSwitch
from mininet.nodelib import NAT, LinuxBridge
from mininet.link import TCLink
from mininet.link import Intf

from subprocess import Popen, PIPE, check_output
from time import sleep, time
from multiprocessing import Process
import argparse
import atexit
import math

import sys
import signal
import os
from termcolor import cprint
import time
import re
import subprocess

from lib import config
from lib import mininet_utils

server_processes = []

setLogLevel ('info')

parser = argparse.ArgumentParser ("Create a simple model of an NBN service")

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

parser.add_argument ('--sleep', default = 3, type = int)
parser.add_argument ('-d', '--downstream', default = 500, type = ranged_type (float, 0, math.inf), help = 'Aggregation downstream bandwidth (Mb/s)')
parser.add_argument ('-u', '--upstream', default = 200, type = ranged_type (float, 0, math.inf), help = 'Aggregation upstream bandwidth (Mb/s)')
parser.add_argument ('-s', '--servers', default = 16, type = ranged_type (int, 1, 20), help = 'Number of servers (1-20 inclusive)')
parser.add_argument ('-c', '--clients', default = 16, type = ranged_type (int, 1, 20), help = 'Number of clients (1-20 inclusive)')
args = parser.parse_args ()

HOUSEHOLD_COUNT = 8
CLIENTS_PER_HOUSEHOLD = 2
HOUSEHOLD_DOWNSTREAM = 150
HOUSEHOLD_UPSTREAM = 40
FIRST_CLIENT_SUBNET = 101

def log (s, col = "green"):
	cprint (s, col)

class Router (Switch):
	"""Defines a new router that is inside a network namespace so that the
	individual routing entries don't collide.

	"""
	ID = 0
	def __init__(self, name, **kwargs):
		kwargs['inNamespace'] = True
		Switch.__init__(self, name, **kwargs)
		Router.ID += 1
		self.switch_id = Router.ID

	@staticmethod
	def setup ():
		return

	def start (self, controllers):
		pass

	def stop (self):
		self.deleteIntfs()

	def log (self, s, col="magenta"):
		cprint (s, col)

class GenericSwitch (Switch):
	"""Defines a new gateway that is NOT inside a network namespace.
	"""
	ID = 0
	def __init__(self, name, **kwargs):
		kwargs['inNamespace'] = False
		Switch.__init__(self, name, **kwargs)
		GenericSwitch.ID += 1
		self.switch_id = GenericSwitch.ID

	@staticmethod
	def setup ():
		return

	def start (self, controllers):
		pass

	def stop (self):
		self.deleteIntfs()

	def log (self, s, col="magenta"):
		cprint (s, col)

class NBNTopo (Topo):
	def __init__ (self):
# Add default members to class.
		super (NBNTopo, self).__init__ ()
# Control
#		s1 = self.addSwitch ('s1', cls=LinuxBridge, dpid='0000000000000001', inNamespace=True)
# Servers

# Customer LAN switch (customer L2/L3 network), 192.168.100.0/24

		routers = []
		switches = []
		clients = []
		servers = []

		household_switches = []
		household_routers = []
		mgmt_switch = self.addSwitch ('sm', dpid='0000000000000008', inNamespace=True, cls=LinuxBridge)
		switches.append (mgmt_switch)

# Switch representing NBN L2 service between customer and RSP - there might be a bunch of others following this one, but for now just the one.
		s2 = self.addSwitch ('s2', dpid='0000000000000003', inNamespace=True, cls=LinuxBridge)
		switches.append (s2)

# Router representing RSP-to-customer interface, 10.1.1.2/30 external, 172.16.1.1/24 internal
		r2 = self.addSwitch ('r2', dpid='0000000000000004', inNamespace=True)
		routers.append (r2)

# RSP internal network
		s3 = self.addSwitch ('s3', dpid='0000000000000005', inNamespace=True, cls=LinuxBridge)
		switches.append (s3)

# RSP to internet connection, 172.16.1.254/24 internal, 172.20.1.1/24 external
		r3 = self.addSwitch ('r3', dpid='0000000000000006', inNamespace=True)
		routers.append (r3)

# Content servers in 172.20.1.0/24 connected to RSP via s3
		s4 = self.addSwitch ('s4', dpid='0000000000000007', inNamespace=True, cls=LinuxBridge)
		switches.append (s4)

		client_index = 1
		for household in range (1, HOUSEHOLD_COUNT + 1):
			lan_switch = self.addSwitch ('s1h%i' % household, dpid='00000000000001%02i' % household, inNamespace=True, cls=LinuxBridge)
			lan_router = self.addSwitch ('hr%i' % household, dpid='00000000000002%02i' % household, inNamespace=True)
			household_switches.append (lan_switch)
			household_routers.append (lan_router)
			switches.append (lan_switch)
			routers.append (lan_router)

			subnet_octet = FIRST_CLIENT_SUBNET + household - 1
			self.addLink (lan_switch, lan_router, intfName1='s1h%i-hr%i' % (household, household), intfName2='hr%i-s1h%i' % (household, household), params2={'ip':'192.168.%i.254/24' % subnet_octet})
			self.addLink (lan_router, s2, intfName1='hr%i-s2' % household, intfName2='s2-hr%i' % household, params1={'ip':'10.1.%i.1/30' % household})
			self.addLink (lan_router, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.%i/24' % (80 + household)}, intfName2='sm-hr%i' % household)
			self.addLink (lan_switch, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.%i/24' % (70 + household)}, intfName2='sm-s1h%i' % household)

			for household_client in range (1, CLIENTS_PER_HOUSEHOLD + 1):
				host = self.addHost ('client%i' % client_index, ip='192.168.%i.%i/24' % (subnet_octet, household_client), defaultRoute='via 192.168.%i.254' % subnet_octet)
				clients.append (host)
				self.addLink (host, lan_switch, intfName1=('client%i-s1h%i' % (client_index, household)), intfName2=('s1h%i-client%i' % (household, client_index)), params1={'ip':('192.168.%i.%i/24' % (subnet_octet, household_client))})
				self.addLink (host, mgmt_switch, intfName1='mgmt0', intfName2=('sm-client%i' % client_index), params1={'ip':('10.10.10.%i/24' % (client_index + 20))})
				client_index += 1

		for n in range (1, args.servers + 1):
			host = self.addHost ('server%i' % n, ip='172.20.1.%i/24' % n, defaultRoute='via 172.20.1.254')
			servers.append (host)
			self.addLink (servers[n - 1], s4, intfName1=('server%i-s4' % n), intfName2=('s4-server%i' % n), params1={'ip':('172.20.1.%i/24' % n)})
			self.addLink (servers[n - 1], mgmt_switch, intfName1='mgmt0', intfName2=('sm-server%i' % n), params1={'ip':('10.10.10.%i/24' % (n + 40))})

# Inter switch/router links
		self.addLink (s2, r2, intfName1='s2-r2', intfName2='r2-s2', params2={'ip':'10.1.1.2/30'})
		self.addLink (r2, s3, intfName1='r2-s3', intfName2='s3-r2', params1={'ip':'172.16.1.1/24'})
		self.addLink (s3, r3, intfName1='s3-r3', intfName2='r3-s3', params2={'ip':'172.16.1.254/24'})
		self.addLink (r3, s4, intfName1='r3-s4', intfName2='s4-r3', params1={'ip':'172.20.1.254/24'})

# Management links to everything
		dns = self.addHost ('dns', ip='10.10.10.254/24')

# Routers to mgmt
		self.addLink (r2, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.2/24'}, intfName2='sm-r2')
		self.addLink (r3, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.3/24'}, intfName2='sm-r3')

# Switches to mgmt
		self.addLink (s2, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.12/24'}, intfName2='sm-s2')
		self.addLink (s3, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.13/24'}, intfName2='sm-s3')
		self.addLink (s4, mgmt_switch, intfName1='mgmt0', params1={'ip':'10.10.10.14/24'}, intfName2='sm-s4')

		self.addLink (dns, mgmt_switch, intfName1='dns-sm', intfName2='sm-dns')

def startBindMount (node):
	node.cmd ("/bin/rm -rf /tmp/run-%s && /bin/mkdir -p /tmp/run-%s && /bin/mount --bind /tmp/run-%s /run" % (node.name, node.name, node.name))
	node.waitOutput ()

	return

def disabletso (node):
# Apply ethtool to turn off TCP Segmentation Offload
	node.cmd ("for iface in `/bin/ip link | /bin/grep -- -eth | /usr/bin/cut -f 2 -d ' ' | /usr/bin/cut -f 1  -d '@'` ; do /sbin/ethtool -K $iface tso off ; done")
	return

def setupDNS (node):
	node.cmd ("/bin/mkdir -p /run/resolvconf && /bin/mkdir -p /tmp/resolvconf-%s && /bin/mount --bind /tmp/resolvconf-%s /etc/resolvconf" % (node.name, node.name))
	node.waitOutput ()
	node.cmd ("/bin/ln -sf /run/resolvconf /etc/resolvconf && echo 'nameserver 10.10.10.254' > /run/resolvconf/resolv.conf && echo 'search home.net nbn.net rsp.net cdn.net mgmt.net' >> /run/resolvconf/resolv.conf")
	node.waitOutput ()

	return

def terminate_process (proc_list):
	for proc in proc_list:
		if proc and proc.poll() is None:  # Check if the process is running
			print ("Terminating process %i" % proc.pid)
			os.kill (proc.pid, signal.SIGTERM)  # Terminate the process

def startserver (node, server_cmd):
	log ("Starting service '%s' on %s" % (server_cmd, node.name))
	server_proc = subprocess.Popen (['mnexec', '-a', str (node.pid), '--'] + server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	return server_proc

def set_interface_bw (node, interface, bandwidth):
# Use a burst sized for high-rate links; a single-MTU burst heavily throttles TBF in practice.
	rate_mbit = int (round (bandwidth))
	burst_bytes = max (65536, int ((bandwidth * 1000 * 1000 / 8) * 0.05))

	print ('Bandwidth = %s Mb/s' % rate_mbit)
	log ("Setting egress bandwidth on %s:%s to %iMb/s (burst %i bytes)" % (node.name, interface, rate_mbit, burst_bytes))
	node.cmd ("/sbin/tc qdisc replace dev %s root handle 1: tbf rate %smbit burst %ib latency 50ms" % (interface, rate_mbit, burst_bytes))

def set_interface_latency_loss (node, interface, latency, jitter, correlation, loss):
	log ("Setting latency on %s:%s to %i ms with %i ms jitter and %i%% correlation (Pareto distribution)" % (node.name, interface, latency, jitter, correlation))
	node.cmd ("/sbin/tc qdisc add dev %s root netem delay %ims %ims %i%% distribution pareto" % (interface, latency, jitter, correlation))

def main ():
	os.system ("/bin/rm -f /tmp/r*.log /tmp/r*.pid logs/*")
	os.system ("/bin/killall -9 named > /dev/null 2>&1")

	required_clients = HOUSEHOLD_COUNT * CLIENTS_PER_HOUSEHOLD
	if args.clients != required_clients:
		parser.error ("This household scenario requires exactly %i clients" % required_clients)
	if args.servers < required_clients:
		parser.error ("This household scenario requires at least %i servers" % required_clients)

	topo = NBNTopo()

	test_name = "visualisation"
	mutils = mininet_utils.mininet_utils(config.config['output_dir'], test_name)
	base_dir = config.config['output_dir'] + test_name + '/'
	mutils.create_directories ()
	mutils.create_topology_diagram (topo)

	net = Mininet (topo = topo, switch = Router)

	net.start ()

#	startBridge(net.switches[0])

	for node in net.switches:
		startBindMount (node)
		node.cmd ("/sbin/sysctl -w net.ipv4.ip_forward=1")
		node.cmd ("/sbin/ifup lo") # why this doesn't happen by default is beyond my comprehension
		node.waitOutput ()
		setupDNS (node)
		node.cmd ("mkdir -p /run/sshd")
		server_processes.append (startserver (node, ["/sbin/sshd", "-D"]))
		disabletso (node)

	s2 = net.get ('s2')
	r2 = net.get ('r2')
	r3 = net.get ('r3')

	for household in range (1, HOUSEHOLD_COUNT + 1):
		subnet_octet = FIRST_CLIENT_SUBNET + household - 1
		household_router = net.get ('hr%i' % household)

		if household > 1:
			r2.cmd ('/sbin/ip addr add 10.1.%i.2/30 dev r2-s2' % household)

		household_router.cmd ('/sbin/ip route add default via 10.1.%i.2' % household)
		household_router.cmd ('/sbin/ip route add 172.16.1.0/24 via 10.1.%i.2' % household)
		household_router.cmd ('/sbin/ip route add 172.20.1.0/24 via 10.1.%i.2' % household)
		r2.cmd ('/sbin/ip route add 192.168.%i.0/24 via 10.1.%i.1 dev r2-s2' % (subnet_octet, household))

# This is r2 - the rsp-residential gateway
	r2.cmd ('/sbin/ip route add 172.20.1.0/24 via 172.16.1.254');

# This is r3 - the rsp-csp gateway
	r3.cmd ('/sbin/ip route add 10.1.0.0/16 via 172.16.1.1');
	for household in range (1, HOUSEHOLD_COUNT + 1):
		subnet_octet = FIRST_CLIENT_SUBNET + household - 1
		r3.cmd ('/sbin/ip route add 192.168.%i.0/24 via 172.16.1.1' % subnet_octet);

# For now:
	latency = 2
	jitter = 2
	correlation = 50
	loss = 0

# Apply household service rates and shared aggregation bottleneck
	for household in range (1, HOUSEHOLD_COUNT + 1):
		household_router = net.get ('hr%i' % household)
		set_interface_bw (s2, 's2-hr%i' % household, HOUSEHOLD_DOWNSTREAM)
		set_interface_bw (household_router, 'hr%i-s2' % household, HOUSEHOLD_UPSTREAM)

	set_interface_bw (r2, 'r2-s2', args.downstream)
	set_interface_bw (s2, 's2-r2', args.upstream)

# This looks confusing; it is saying do a bind mount of the folder ../bind to /etc/bind (bind = berkely internet name daemon aka DNS server)
#	log ("Performing bind mount for bind configuration folder, and starting BIND daemon")

#	startBindMount (net.switches[-1])
#	net.switches[-1].cmd ('/sbin/brctl delif s1 s1-sm')
#	net.switches[-1].cmd ('/sbin/ifup lo')
#	setupDNS (net.switches[-1])

	for host in net.hosts:
		startBindMount (host)
		disabletso (host)
		host.cmd ("mkdir -p /run/sshd")
		server_processes.append (startserver (host, ["/sbin/sshd", "-D"]))
		server_processes.append (startserver (host, ["/sbin/nginx", "-g", "daemon off;"]))
		server_processes.append (startserver (host, ["/usr/bin/iperf3", "-s", "-f", "K"]))
		server_processes.append (startserver (host, ["/usr/bin/ITGRecv"]))
		setupDNS (host)

		if host.name == 'dns':
			host.cmd ('/bin/mount --bind bind /etc/bind && /bin/mkdir -p /run/named && /bin/chown bind.bind /run/named && named -u bind -4 -L /tmp/bind.log')

	atexit.register (terminate_process, server_processes)
	
#	CLI (net)
	net.hosts[-1].cmd ("cd perfmon ; /usr/bin/python3 ./run_experiments.py &> /tmp/experiment.log")

	net.stop ()
	os.system ("/usr/bin/killall -9 named > /dev/null 2>&1")

if __name__ == "__main__":
	setLogLevel ('info')
	main ()
