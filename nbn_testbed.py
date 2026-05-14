#!/usr/bin/env python3
#
# Code based on i2rs-wg by Edwin Cordeiro. See https://github.com/i2rs-wg for the original script.
#
# Extensively modified by Daniel R. Franklin for UTS 49202 Communication Protocols labs.
#
# Report bugs to Daniel.Franklin@uts.edu.au
#

import argparse
import atexit
import math
import os
import re
import signal
import subprocess
import sys
from termcolor import cprint

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.nodelib import LinuxBridge
from mininet.node import Switch
from mininet.topo import Topo

from lib import config
from lib import mininet_utils

server_processes = []

FIRST_CLIENT_SUBNET = 101
IPERF_PORTS_PER_SERVER = 8
MGMT_PREFIX = "10.10"
MGMT_NETMASK = 16
MGMT_DNS_IP = "10.10.10.254"

setLogLevel("info")


def ranged_type(value_type, min_value, max_value):
    def range_checker(arg: str):
        try:
            value = value_type(arg)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"must be a valid {value_type}") from exc

        if value < min_value or value > max_value:
            raise argparse.ArgumentTypeError(f"must be within range [{min_value}, {max_value}]")

        return value

    return range_checker


parser = argparse.ArgumentParser("Create a scalable model of an NBN service")
parser.add_argument("--sleep", default=3, type=int)
parser.add_argument("-d", "--downstream", default=400, type=ranged_type(float, 0, math.inf), help="Legacy alias for aggregation downstream bandwidth (Mb/s)")
parser.add_argument("-u", "--upstream", default=200, type=ranged_type(float, 0, math.inf), help="Legacy alias for aggregation upstream bandwidth (Mb/s)")
parser.add_argument("--aggregation-downstream", default=None, type=ranged_type(float, 0, math.inf), help="Shared r2-s2 downstream limit (Mb/s)")
parser.add_argument("--aggregation-upstream", default=None, type=ranged_type(float, 0, math.inf), help="Shared s2-r2 upstream limit (Mb/s)")
parser.add_argument("--household-downstream", default=150, type=ranged_type(float, 0, math.inf), help="Per-household downstream access limit (Mb/s)")
parser.add_argument("--household-upstream", default=40, type=ranged_type(float, 0, math.inf), help="Per-household upstream access limit (Mb/s)")
parser.add_argument("-s", "--servers", default=16, type=ranged_type(int, 1, math.inf), help="Number of servers")
parser.add_argument("-c", "--clients", default=None, type=ranged_type(int, 1, math.inf), help="Legacy total client count. Must match houses * clients-per-house if supplied")
parser.add_argument("--houses", default=8, type=ranged_type(int, 1, math.inf), help="Number of households")
parser.add_argument("--clients-per-house", default=2, type=ranged_type(int, 1, math.inf), help="Number of clients per household")
parser.add_argument("--traffic-mode", choices=["fixed-stagger", "realistic-timeseries"], default="fixed-stagger", help="Traffic scheduling mode")
parser.add_argument("--first-house-start", default=5, type=ranged_type(int, 0, math.inf), help="Start time of the first household in fixed-stagger mode")
parser.add_argument("--house-stagger", default=5, type=ranged_type(int, 0, math.inf), help="Household start interval in fixed-stagger mode")
parser.add_argument("--capture-houses", default="", help="Comma-separated household numbers to capture on the s2-facing side")
parser.add_argument("--profile-csv", default="perfmon/Experiments_dynamic_household_profiles.csv", help="Household profile catalog CSV")
parser.add_argument("--scenario-csv", default="perfmon/Experiments_dynamic_v1.csv", help="Scenario source CSV")
parser.add_argument("--generate-profiles", action="store_true", help="Regenerate the household profile catalog from the scenario CSV")
parser.add_argument("--seed", default=42, type=int, help="Seed for profile assignment and realistic scheduling")
parser.add_argument("--duration", default=180, type=ranged_type(int, 30, math.inf), help="Total experiment duration in seconds")
parser.add_argument("--peak-start", default="18:00", help="Simulated daily peak window start label (HH:MM)")
parser.add_argument("--peak-end", default="21:00", help="Simulated daily peak window end label (HH:MM)")
parser.add_argument("--test-name", default="", help="Optional explicit name for the generated test")
args = parser.parse_args()


def log(message, colour="green"):
    cprint(message, colour)


def parse_capture_houses(value: str, max_house: int) -> list[int]:
    if not value:
        return []
    houses = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        house = int(item)
        if house < 1 or house > max_house:
            raise argparse.ArgumentTypeError(f"capture house {house} is outside the valid range 1..{max_house}")
        houses.append(house)
    return sorted(dict.fromkeys(houses))


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "nbn_test"


def indexed_mgmt_ip(base_third_octet: int, index: int) -> str:
    third_octet = base_third_octet + ((index - 1) // 250)
    fourth_octet = ((index - 1) % 250) + 1
    if third_octet > 254:
        raise ValueError("Management address space exhausted for this topology size")
    return f"{MGMT_PREFIX}.{third_octet}.{fourth_octet}"


def household_switch_mgmt_ip(household: int) -> str:
    return indexed_mgmt_ip(20, household)


def household_router_mgmt_ip(household: int) -> str:
    return indexed_mgmt_ip(30, household)


def client_mgmt_ip(client_index: int) -> str:
    return indexed_mgmt_ip(40, client_index)


def server_mgmt_ip(server_index: int) -> str:
    return indexed_mgmt_ip(60, server_index)


def client_data_ip(subnet_octet: int, host_index: int) -> str:
    return f"192.168.{subnet_octet}.{host_index}"


def build_test_name() -> str:
    if args.test_name:
        return slugify(args.test_name)
    return slugify(f"nbn_{args.houses}h_{args.clients_per_house}cph_{args.traffic_mode}_seed{args.seed}")


def aggregation_downstream_limit() -> float:
    return args.aggregation_downstream if args.aggregation_downstream is not None else args.downstream


def aggregation_upstream_limit() -> float:
    return args.aggregation_upstream if args.aggregation_upstream is not None else args.upstream


class Router(Switch):
    """Defines a router inside a network namespace so routes do not collide."""

    ID = 0

    def __init__(self, name, **kwargs):
        kwargs["inNamespace"] = True
        Switch.__init__(self, name, **kwargs)
        Router.ID += 1
        self.switch_id = Router.ID

    @staticmethod
    def setup():
        return

    def start(self, controllers):
        return

    def stop(self):
        self.deleteIntfs()


class NBNTopo(Topo):
    def __init__(self, household_count: int, clients_per_household: int, server_count: int):
        super().__init__()

        mgmt_switch = self.addSwitch("sm", dpid="0000000000000008", inNamespace=True, cls=LinuxBridge)
        s2 = self.addSwitch("s2", dpid="0000000000000003", inNamespace=True, cls=LinuxBridge)
        r2 = self.addSwitch("r2", dpid="0000000000000004", inNamespace=True)
        s3 = self.addSwitch("s3", dpid="0000000000000005", inNamespace=True, cls=LinuxBridge)
        r3 = self.addSwitch("r3", dpid="0000000000000006", inNamespace=True)
        s4 = self.addSwitch("s4", dpid="0000000000000007", inNamespace=True, cls=LinuxBridge)

        client_index = 1
        for household in range(1, household_count + 1):
            lan_switch = self.addSwitch(f"s1h{household}", dpid=f"00000000000001{household:02d}", inNamespace=True, cls=LinuxBridge)
            lan_router = self.addSwitch(f"hr{household}", dpid=f"00000000000002{household:02d}", inNamespace=True)

            subnet_octet = FIRST_CLIENT_SUBNET + household - 1
            self.addLink(
                lan_switch,
                lan_router,
                intfName1=f"s1h{household}-hr{household}",
                intfName2=f"hr{household}-s1h{household}",
                params2={"ip": f"192.168.{subnet_octet}.254/24"},
            )
            self.addLink(
                lan_router,
                s2,
                intfName1=f"hr{household}-s2",
                intfName2=f"s2-hr{household}",
                params1={"ip": f"10.1.{household}.1/30"},
            )
            self.addLink(
                lan_router,
                mgmt_switch,
                intfName1="mgmt0",
                params1={"ip": f"{household_router_mgmt_ip(household)}/{MGMT_NETMASK}"},
                intfName2=f"sm-hr{household}",
            )
            self.addLink(
                lan_switch,
                mgmt_switch,
                intfName1="mgmt0",
                params1={"ip": f"{household_switch_mgmt_ip(household)}/{MGMT_NETMASK}"},
                intfName2=f"sm-s1h{household}",
            )

            for host_index in range(1, clients_per_household + 1):
                host = self.addHost(
                    f"client{client_index}",
                    ip=f"{client_data_ip(subnet_octet, host_index)}/24",
                    defaultRoute=f"via 192.168.{subnet_octet}.254",
                )
                self.addLink(
                    host,
                    lan_switch,
                    intfName1=f"client{client_index}-s1h{household}",
                    intfName2=f"s1h{household}-client{client_index}",
                    params1={"ip": f"{client_data_ip(subnet_octet, host_index)}/24"},
                )
                self.addLink(
                    host,
                    mgmt_switch,
                    intfName1="mgmt0",
                    intfName2=f"sm-client{client_index}",
                    params1={"ip": f"{client_mgmt_ip(client_index)}/{MGMT_NETMASK}"},
                )
                client_index += 1

        for server_index in range(1, server_count + 1):
            host = self.addHost(
                f"server{server_index}",
                ip=f"172.20.1.{server_index}/24",
                defaultRoute="via 172.20.1.254",
            )
            self.addLink(
                host,
                s4,
                intfName1=f"server{server_index}-s4",
                intfName2=f"s4-server{server_index}",
                params1={"ip": f"172.20.1.{server_index}/24"},
            )
            self.addLink(
                host,
                mgmt_switch,
                intfName1="mgmt0",
                intfName2=f"sm-server{server_index}",
                params1={"ip": f"{server_mgmt_ip(server_index)}/{MGMT_NETMASK}"},
            )

        self.addLink(s2, r2, intfName1="s2-r2", intfName2="r2-s2", params2={"ip": "10.1.1.2/30"})
        self.addLink(r2, s3, intfName1="r2-s3", intfName2="s3-r2", params1={"ip": "172.16.1.1/24"})
        self.addLink(s3, r3, intfName1="s3-r3", intfName2="r3-s3", params2={"ip": "172.16.1.254/24"})
        self.addLink(r3, s4, intfName1="r3-s4", intfName2="s4-r3", params1={"ip": "172.20.1.254/24"})

        dns = self.addHost("dns", ip=f"{MGMT_DNS_IP}/{MGMT_NETMASK}")
        self.addLink(r2, mgmt_switch, intfName1="mgmt0", params1={"ip": f"10.10.10.2/{MGMT_NETMASK}"}, intfName2="sm-r2")
        self.addLink(r3, mgmt_switch, intfName1="mgmt0", params1={"ip": f"10.10.10.3/{MGMT_NETMASK}"}, intfName2="sm-r3")
        self.addLink(s2, mgmt_switch, intfName1="mgmt0", params1={"ip": f"10.10.10.12/{MGMT_NETMASK}"}, intfName2="sm-s2")
        self.addLink(s3, mgmt_switch, intfName1="mgmt0", params1={"ip": f"10.10.10.13/{MGMT_NETMASK}"}, intfName2="sm-s3")
        self.addLink(s4, mgmt_switch, intfName1="mgmt0", params1={"ip": f"10.10.10.14/{MGMT_NETMASK}"}, intfName2="sm-s4")
        self.addLink(dns, mgmt_switch, intfName1="dns-sm", intfName2="sm-dns")


def startBindMount(node):
    node.cmd(f"/bin/rm -rf /tmp/run-{node.name} && /bin/mkdir -p /tmp/run-{node.name} && /bin/mount --bind /tmp/run-{node.name} /run")
    node.waitOutput()


def disabletso(node):
    node.cmd("for iface in `/bin/ip link | /bin/grep -- -eth | /usr/bin/cut -f 2 -d ' ' | /usr/bin/cut -f 1  -d '@'` ; do /sbin/ethtool -K $iface tso off ; done")


def setupDNS(node):
    node.cmd(f"/bin/mkdir -p /run/resolvconf && /bin/mkdir -p /tmp/resolvconf-{node.name} && /bin/mount --bind /tmp/resolvconf-{node.name} /etc/resolvconf")
    node.waitOutput()
    node.cmd(
        f"/bin/ln -sf /run/resolvconf /etc/resolvconf && "
        f"echo 'nameserver {MGMT_DNS_IP}' > /run/resolvconf/resolv.conf && "
        "echo 'search home.net nbn.net rsp.net cdn.net mgmt.net' >> /run/resolvconf/resolv.conf"
    )
    node.waitOutput()


def terminate_process(proc_list):
    for proc in proc_list:
        if proc and proc.poll() is None:
            print(f"Terminating process {proc.pid}")
            os.kill(proc.pid, signal.SIGTERM)


def startserver(node, server_cmd):
    log(f"Starting service '{' '.join(server_cmd)}' on {node.name}")
    return subprocess.Popen(["mnexec", "-a", str(node.pid), "--"] + server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def set_interface_bw(node, interface, bandwidth):
    rate_mbit = int(round(bandwidth))
    burst_bytes = max(65536, int((bandwidth * 1000 * 1000 / 8) * 0.05))
    log(f"Setting egress bandwidth on {node.name}:{interface} to {rate_mbit}Mb/s (burst {burst_bytes} bytes)")
    node.cmd(f"/sbin/tc qdisc replace dev {interface} root handle 1: tbf rate {rate_mbit}mbit burst {burst_bytes}b latency 50ms")


def generate_dynamic_test_assets(test_name: str) -> str:
    generator = os.path.join(os.getcwd(), "perfmon", "generate_test_dynamic.py")
    profile_csv = args.profile_csv if os.path.isabs(args.profile_csv) else os.path.join(os.getcwd(), args.profile_csv)
    scenario_csv = args.scenario_csv if os.path.isabs(args.scenario_csv) else os.path.join(os.getcwd(), args.scenario_csv)
    output_dir = os.path.join(os.getcwd(), "perfmon", "test_configs")
    os.makedirs(output_dir, exist_ok=True)

    command = [
        sys.executable,
        generator,
        "--scenario-csv",
        scenario_csv,
        "--profile-csv",
        profile_csv,
        "--output-dir",
        output_dir,
        "--duration",
        str(args.duration),
        "--houses",
        str(args.houses),
        "--clients-per-house",
        str(args.clients_per_house),
        "--first-house-start",
        str(args.first_house_start),
        "--house-stagger",
        str(args.house_stagger),
        "--traffic-mode",
        args.traffic_mode,
        "--peak-start",
        args.peak_start,
        "--peak-end",
        args.peak_end,
        "--capture-houses",
        args.capture_houses,
        "--server-pool-size",
        str(args.servers),
        "--iperf-ports-per-server",
        str(IPERF_PORTS_PER_SERVER),
        "--test-name",
        test_name,
        "--seed",
        str(args.seed),
    ]

    if args.generate_profiles:
        command.append("--generate-profiles")

    log("Generating household profiles, schedules, and capture configs", "cyan")
    subprocess.run(command, check=True)
    return os.path.join("test_configs", f"{test_name}.json")


def validate_args():
    required_clients = args.houses * args.clients_per_house
    if args.clients is not None and args.clients != required_clients:
        parser.error(f"This scenario requires exactly {required_clients} clients when --clients is supplied")
    if args.servers < required_clients:
        parser.error(f"This scenario requires at least {required_clients} servers")
    try:
        parse_capture_houses(args.capture_houses, args.houses)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))


def main():
    validate_args()

    os.system("/bin/rm -f /tmp/r*.log /tmp/r*.pid logs/*")
    os.system("/bin/killall -9 named > /dev/null 2>&1")

    test_name = build_test_name()
    traffic_config_rel = generate_dynamic_test_assets(test_name)
    capture_houses = parse_capture_houses(args.capture_houses, args.houses)

    topo = NBNTopo(args.houses, args.clients_per_house, args.servers)
    mutils = mininet_utils.mininet_utils(config.config["output_dir"], test_name)
    mutils.create_directories()
    mutils.create_topology_diagram(topo)

    net = Mininet(topo=topo, switch=Router, link=TCLink)
    net.start()

    for node in net.switches:
        startBindMount(node)
        node.cmd("/sbin/sysctl -w net.ipv4.ip_forward=1")
        node.cmd("/sbin/ifup lo")
        node.waitOutput()
        setupDNS(node)
        node.cmd("mkdir -p /run/sshd")
        server_processes.append(startserver(node, ["/sbin/sshd", "-D"]))
        disabletso(node)

    s2 = net.get("s2")
    r2 = net.get("r2")
    r3 = net.get("r3")
    dns = net.get("dns")

    for household in range(1, args.houses + 1):
        subnet_octet = FIRST_CLIENT_SUBNET + household - 1
        household_router = net.get(f"hr{household}")

        if household > 1:
            r2.cmd(f"/sbin/ip addr add 10.1.{household}.2/30 dev r2-s2")

        household_router.cmd(f"/sbin/ip route add default via 10.1.{household}.2")
        household_router.cmd(f"/sbin/ip route add 172.16.1.0/24 via 10.1.{household}.2")
        household_router.cmd(f"/sbin/ip route add 172.20.1.0/24 via 10.1.{household}.2")
        r2.cmd(f"/sbin/ip route add 192.168.{subnet_octet}.0/24 via 10.1.{household}.1 dev r2-s2")

    r2.cmd("/sbin/ip route add 172.20.1.0/24 via 172.16.1.254")
    r3.cmd("/sbin/ip route add 10.1.0.0/16 via 172.16.1.1")
    for household in range(1, args.houses + 1):
        subnet_octet = FIRST_CLIENT_SUBNET + household - 1
        r3.cmd(f"/sbin/ip route add 192.168.{subnet_octet}.0/24 via 172.16.1.1")

    for household in range(1, args.houses + 1):
        household_router = net.get(f"hr{household}")
        set_interface_bw(s2, f"s2-hr{household}", args.household_downstream)
        set_interface_bw(household_router, f"hr{household}-s2", args.household_upstream)

    set_interface_bw(r2, "r2-s2", aggregation_downstream_limit())
    set_interface_bw(s2, "s2-r2", aggregation_upstream_limit())

    for host in net.hosts:
        startBindMount(host)
        disabletso(host)
        host.cmd("mkdir -p /run/sshd")
        server_processes.append(startserver(host, ["/sbin/sshd", "-D"]))
        server_processes.append(startserver(host, ["/usr/bin/nginx", "-g", "daemon off;"]))
        server_processes.append(startserver(host, ["/usr/bin/ITGRecv"]))
        setupDNS(host)

        if host.name.startswith("server"):
            for port in range(5201, 5201 + IPERF_PORTS_PER_SERVER):
                server_processes.append(startserver(host, ["/usr/bin/iperf3", "-s", "-p", str(port), "-f", "K"]))
        else:
            server_processes.append(startserver(host, ["/usr/bin/iperf3", "-s", "-f", "K"]))

        if host.name == "dns":
            host.cmd("/bin/mount --bind bind /etc/bind && /bin/mkdir -p /run/named && /bin/chown bind.bind /run/named && named -u bind -4 -L /tmp/bind.log")

    atexit.register(terminate_process, server_processes)

    log(f"Running generated experiment '{test_name}'", "cyan")
    log(f"Capture houses: {capture_houses if capture_houses else 'aggregation only'}", "cyan")
    dns.cmd(
        "cd perfmon ; "
        f"/usr/bin/python3 ./run_experiments.py --test-file {traffic_config_rel} "
        "--test-configs-dir test_configs --completed-dir completed_experiments "
        "&> /tmp/experiment.log"
    )

    net.stop()
    os.system("/usr/bin/killall -9 named > /dev/null 2>&1")


if __name__ == "__main__":
    setLogLevel("info")
    main()
