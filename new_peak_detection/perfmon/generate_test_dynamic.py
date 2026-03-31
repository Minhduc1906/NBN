import pandas as pd
import json
import os
import random
import argparse
from typing import List, Dict, Any, Union, Tuple

def parse_traffic_config(value: str) -> Tuple[List[Union[int, float]], str, float]:
    """Parse traffic configuration strings into flow counts and rates."""
    if pd.isna(value) or value == '-':
        return [], '', 0.0
    
    if '@' in value:  # TCP flows with rate limit
        flows_str, rate_str = value.split('@')
        flows = [int(x.strip()) for x in flows_str.split(',')]
        rate = float(rate_str.split()[0])
        return flows, 'tcp', rate
    elif 'CBR UDP' in value:  # CBR traffic
        rates_str = value.split('Mb/s')[0]
        rates = [float(x.strip()) for x in rates_str.split(',')]
        return rates, 'cbr', 0.0
    elif 'TCP flows' in value:  # Unlimited TCP flows
        flows_str = value.split('TCP')[0]
        flows = [int(x.strip()) for x in flows_str.split(',')]
        return flows, 'tcp_unlimited', float('inf')
    
    return [], '', 0.0

def parse_stochastic_config(value: str) -> List[Dict[str, Any]]:
    """Parse stochastic traffic configuration strings."""
    if pd.isna(value) or value == '-':
        return []
    
    stochastic_flows = []
    flow_configs = value.split('+')
    
    for flow in flow_configs:
        if 'VoIP' in flow:
            params = flow[flow.index('(')+1:flow.index(')')].split(';')
            stochastic_flows.append({
                'type': 'VoIP',
                'min_size': int(params[0]),
                'max_size': int(params[1]),
                'variance': float(params[2])
            })
        elif 'Gaming' in flow:
            params = flow[flow.index('(')+1:flow.index(')')].split(';')
            stochastic_flows.append({
                'type': 'Gaming',
                'min_size': int(params[0]),
                'max_size': int(params[1]),
                'variance': float(params[2])
            })
        elif 'Video' in flow:
            params = flow[flow.index('(')+1:flow.index(')')].split(';')
            stochastic_flows.append({
                'type': 'Video',
                'min_size': int(params[0]),
                'max_size': int(params[1]),
                'distribution': params[2],
                'variance': float(params[3])
            })
    
    return stochastic_flows

def generate_download_segments(total_duration: int, min_segment: int = 10, max_segment: int = 60, 
                              min_pause: int = 5, max_pause: int = 30) -> List[Dict[str, int]]:
    """
    Generate random download segments with pauses that sum up to the total_duration.
    
    Args:
        total_duration: Total download duration in seconds
        min_segment: Minimum download segment duration in seconds
        max_segment: Maximum download segment duration in seconds
        min_pause: Minimum pause duration in seconds
        max_pause: Maximum pause duration in seconds
        
    Returns:
        List of dicts with 'type' (download/pause), 'duration', and 'start_time' keys
    """
    segments = []
    remaining_duration = total_duration
    current_time = 0
    
    # Ensure we have at least one download segment
    if remaining_duration < min_segment:
        return [{'type': 'download', 'duration': remaining_duration, 'start_time': 0}]
    
    while remaining_duration > 0:
        # If we're getting close to the end, just use the remaining time
        if remaining_duration < min_segment + min_pause:
            segments.append({'type': 'download', 'duration': remaining_duration, 'start_time': current_time})
            break
            
        # Calculate download duration for this segment
        segment_duration = min(random.randint(min_segment, max_segment), remaining_duration)
        segments.append({'type': 'download', 'duration': segment_duration, 'start_time': current_time})
        
        remaining_duration -= segment_duration
        current_time += segment_duration
        
        # Add a pause if we still have time left
        if remaining_duration > min_segment:
            pause_duration = min(random.randint(min_pause, max_pause), remaining_duration - min_segment)
            segments.append({'type': 'pause', 'duration': pause_duration, 'start_time': current_time})
            remaining_duration -= pause_duration
            current_time += pause_duration
    
    return segments

def create_tcp_config_with_segments(index: int, rate: float, start_time: int, segments: List[Dict[str, int]]) -> List[Dict[str, Any]]:
    """Create multiple TCP test configurations for each segment with pauses in between."""
    configs = []
    segment_index = 1
    
    for segment in segments:
        if segment['type'] == 'download':
            # For TCP downloads, create a new test for each segment
            cmd = f"iperf3 -c server{index} -C reno -R -t {segment['duration']}"
            if rate != float('inf'):
                cmd = f"iperf3 -c server{index} -C reno -R -b {rate}M -t {segment['duration']}"
                
            configs.append({
                "testname": f"iperf TCP-reno {'rate-limited' if rate != float('inf') else 'unlimited'} download #{index}-{segment_index}",
                "host1": {
                    "name": f"client{index}-mgmt",
                    "cmd": cmd,
                    "persist": False,
                    "start_time": start_time + segment['start_time']
                }
            })
            segment_index += 1
    
    return configs

def create_udp_config_with_segments(index: int, rate: float, start_time: int, segments: List[Dict[str, int]]) -> List[Dict[str, Any]]:
    """Create multiple UDP test configurations for each segment with pauses in between."""
    configs = []
    segment_index = 1
    
    for segment in segments:
        if segment['type'] == 'download':
            configs.append({
                "testname": f"iperf UDP download #{index}-{segment_index}",
                "host1": {
                    "name": f"client{index}-mgmt",
                    "cmd": f"iperf3 -c server{index} -R -u -b {rate}M -t {segment['duration']}",
                    "persist": False,
                    "start_time": start_time + segment['start_time']
                }
            })
            segment_index += 1
    
    return configs

def create_stochastic_config(index: int, flow: Dict[str, Any], start_time: int, duration_seconds: int = 300) -> Dict[str, Any]:
    """Create a stochastic traffic configuration with an adjustable duration (default 5 minutes)."""
    # Convert seconds to milliseconds for D-ITG
    duration_ms = duration_seconds * 1000
    
    base_config = {
        "testname": f"{flow['type']} Traffic Simulation #{index}",
        "host1": {
            "name": f"server{index}-mgmt",
            "cmd": "ITGRecv",
            "persist": True,
            "start_time": 0
        },
        "host2": {
            "name": f"client{index}-mgmt",
            "persist": False,
            "start_time": start_time
        }
    }
    
    if flow['type'] == 'VoIP':
        base_config["host2"]["cmd"] = (
            f"ITGSend -T UDP -a server{index} "
            f"-C {flow['max_size']} -c {flow['min_size']} "
            f"-t {duration_ms} -x voip_recv_log_{index} -l voip_send_log_{index} "
            f"-e 100 -E 100 -k 20 -K 20 -v {flow['variance']}"
        )
    elif flow['type'] == 'Gaming':
        base_config["host2"]["cmd"] = (
            f"ITGSend -T UDP -a server{index} "
            f"-C {flow['max_size']} -c {flow['min_size']} "
            f"-t {duration_ms} -x game_recv_log_{index} -l game_send_log_{index} "
            f"-e 50 -E 50 -k 10 -K 10 -v {flow['variance']}"
        )
    elif flow['type'] == 'Video':
        base_config["host2"]["cmd"] = (
            f"ITGSend -T UDP -a server{index} "
            f"-C {flow['max_size']} -c {flow['min_size']} "
            f"-t {duration_ms} -x video_recv_log_{index} -l video_send_log_{index} "
            f"-e 1000 -E 1000 -k 30 -K 30 -d {flow['distribution']} -v {flow['variance']}"
        )
    
    return base_config

def calculate_total_bandwidth(limited_flows, limited_rate, unlimited_flows, cbr_rates):
    """Calculate total bandwidth required for a scenario."""
    total = 0
    
    # Rate-limited TCP flows
    if limited_flows and limited_rate != float('inf'):
        total += limited_flows * limited_rate
    
    # Unlimited TCP flows (assume 80 Mbps each as an estimate)
    if unlimited_flows:
        total += unlimited_flows * 80
    
    # CBR traffic
    if cbr_rates:
        total += sum(cbr_rates)
    
    return total

def generate_household_tests(row: pd.Series, output_dir: str, randomize: bool,
                             total_experiment_duration: int) -> int:
    """Generate a single test file for a staged household downstream scenario."""
    scenario = row['Scenario']
    base_scenario_name = scenario.replace(" ", "_").replace(",", "").lower()
    households = int(row.get('Households', 8))
    clients_per_household = int(row.get('Clients per household', 2))
    first_start = int(row.get('First household start (s)', 5))
    start_interval = int(row.get('Household start interval (s)', 5))
    tcp_rate = float(row.get('TCP per household (Mb/s)', 75))
    udp_rate = float(row.get('UDP per household (Mb/s)', 75))

    tests = []
    last_household_start = first_start + ((households - 1) * start_interval)
    total_test_duration = max(total_experiment_duration, last_household_start + 60)

    for household_index in range(households):
        house_start = first_start + (household_index * start_interval)
        flow_duration = total_test_duration - house_start
        tcp_client = (household_index * clients_per_household) + 1
        udp_client = tcp_client + 1

        if randomize:
            tcp_segments = generate_download_segments(flow_duration)
            udp_segments = generate_download_segments(flow_duration)
            tests.extend(create_tcp_config_with_segments(tcp_client, tcp_rate, house_start, tcp_segments))
            tests.extend(create_udp_config_with_segments(udp_client, udp_rate, house_start, udp_segments))
        else:
            tests.append(create_tcp_config(tcp_client, tcp_rate, house_start, flow_duration))
            tests.append(create_udp_config(udp_client, udp_rate, house_start, flow_duration))

    filename = os.path.join(
        output_dir,
        f"test_{base_scenario_name}_{households}houses_{int(tcp_rate)}tcp_{int(udp_rate)}udp.json"
    )
    with open(filename, 'w') as f:
        json.dump(tests, f, indent=2)

    print(f"Generated {filename}")
    return 1

def generate_test_files(csv_file: str, output_dir: str = "test_configs", randomize: bool = True, 
                   total_experiment_duration: int = 600):
    """
    Generate test.json files for all scenarios including stochastic traffic with randomized downloads.
    
    Args:
        csv_file: Path to the CSV file with experiment specifications
        output_dir: Directory to save the generated JSON files
        randomize: Whether to randomize download patterns
        total_experiment_duration: Target duration for the entire experiment in seconds (default: 600s = 10 minutes)
    """
    df = pd.read_csv(csv_file)
    os.makedirs(output_dir, exist_ok=True)
    
    # Set random seed for reproducibility if needed
    random.seed(42)
    
    for idx, row in df.iterrows():
        mode = str(row.get('Mode', '')).strip().lower()
        if mode == 'households':
            generated = generate_household_tests(
                row,
                output_dir=output_dir,
                randomize=randomize,
                total_experiment_duration=total_experiment_duration
            )
            print(f"Generated {generated} sub-configurations for scenario: {row['Scenario']}")
            continue

        scenario = row['Scenario']
        base_scenario_name = scenario.replace(" ", "_").replace(",", "").lower()
        
        # Parse all traffic types
        limited_flows_list, limited_type, limited_rate = parse_traffic_config(row['TCP flows (rate limited)'])
        unlimited_flows_list, unlimited_type, _ = parse_traffic_config(row['TCP flows (unlimited)'])
        cbr_rates, cbr_type, _ = parse_traffic_config(row['CBR traffic'])
        stochastic_flows = parse_stochastic_config(row['Stochastic traffic'])
        
        sub_scenario_count = 0
        
        # Generate configurations for all possible combinations
        for limited_flows in (limited_flows_list or [0]):
            for unlimited_flows in (unlimited_flows_list or [0]):
                # If there are CBR rates, create a config for each rate
                if cbr_rates:
                    for rate in cbr_rates:
                        # Plan the test timeline
                        client_index = 1
                        start_time = 0
                        start_times = []
                        
                        # Add random offset to start times if randomizing
                        if randomize:
                            # Add rate-limited TCP flows
                            if limited_flows > 0:
                                for i in range(limited_flows):
                                    random_offset = random.randint(0, 5)  # Random offset between 0-5 seconds
                                    start_times.append(start_time + random_offset)
                                    client_index += 1
                                    start_time += 10  # Base spacing of 10 seconds
                            
                            # Add unlimited TCP flows
                            if unlimited_flows > 0:
                                for i in range(unlimited_flows):
                                    random_offset = random.randint(0, 5)  # Random offset between 0-5 seconds
                                    start_times.append(start_time + random_offset)
                                    client_index += 1
                                    start_time += 10  # Base spacing of 10 seconds
                            
                            # Add CBR UDP traffic
                            random_offset = random.randint(0, 5)
                            start_times.append(start_time + random_offset)
                            client_index += 1
                            start_time += 10
                        else:
                            # Original non-randomized start times
                            if limited_flows > 0:
                                for i in range(limited_flows):
                                    start_times.append(start_time)
                                    client_index += 1
                                    start_time += 10
                            
                            if unlimited_flows > 0:
                                for i in range(unlimited_flows):
                                    start_times.append(start_time)
                                    client_index += 1
                                    start_time += 10
                            
                            start_times.append(start_time)
                            client_index += 1
                            start_time += 10
                        
                        # Add stochastic traffic with fixed start times
                        for flow in stochastic_flows:
                            start_times.append(start_time)
                            client_index += 1
                            start_time += 10
                        
                        # Calculate the total test duration based on target experiment duration
                        # Instead of just adding 60 seconds to the last start time, extend to meet the target duration
                        total_test_duration = 0
                        if start_times:
                            min_required_duration = max(start_times) + 60  # Minimum required duration
                            total_test_duration = max(min_required_duration, total_experiment_duration)
                        
                        # Now create the actual tests with randomized segments
                        tests = []
                        client_index = 1
                        
                        # Calculate total bandwidth
                        total_bw = calculate_total_bandwidth(limited_flows, limited_rate, unlimited_flows, [rate])
                        bw_category = "high_load" if total_bw > 90 else "normal_load"
                        
                        # Add rate-limited TCP flows with randomized segments
                        if limited_flows > 0:
                            for i in range(limited_flows):
                                flow_start = start_times[i]
                                flow_duration = total_test_duration - flow_start
                                
                                if randomize:
                                    # Generate segments with random pauses
                                    segments = generate_download_segments(flow_duration)
                                    test_configs = create_tcp_config_with_segments(client_index, limited_rate, flow_start, segments)
                                    tests.extend(test_configs)
                                else:
                                    # Original continuous download
                                    tests.append(create_tcp_config(client_index, limited_rate, flow_start, flow_duration))
                                
                                client_index += 1
                        
                        # Add unlimited TCP flows with randomized segments
                        if unlimited_flows > 0:
                            for i in range(unlimited_flows):
                                flow_start = start_times[limited_flows + i]
                                flow_duration = total_test_duration - flow_start
                                
                                if randomize:
                                    # Generate segments with random pauses
                                    segments = generate_download_segments(flow_duration)
                                    test_configs = create_tcp_config_with_segments(client_index, float('inf'), flow_start, segments)
                                    tests.extend(test_configs)
                                else:
                                    # Original continuous download
                                    tests.append(create_tcp_config(client_index, float('inf'), flow_start, flow_duration))
                                
                                client_index += 1
                        
                        # Add CBR UDP traffic with randomized segments
                        flow_start = start_times[limited_flows + unlimited_flows]
                        flow_duration = total_test_duration - flow_start
                        
                        if randomize:
                            # Generate segments with random pauses
                            segments = generate_download_segments(flow_duration)
                            test_configs = create_udp_config_with_segments(client_index, rate, flow_start, segments)
                            tests.extend(test_configs)
                        else:
                            # Original continuous stream
                            tests.append(create_udp_config(client_index, rate, flow_start, flow_duration))
                        
                        client_index += 1
                        
                        # Add stochastic traffic with longer duration (5 minutes = 300 seconds)
                        for j, flow in enumerate(stochastic_flows):
                            flow_start = start_times[limited_flows + unlimited_flows + 1 + j]
                            tests.append(create_stochastic_config(client_index, flow, flow_start, duration_seconds=300))
                            client_index += 1
                        
                        # Save the configuration
                        sub_scenario_count += 1
                        rand_suffix = "_randomized" if randomize else ""
                        filename = os.path.join(
                            output_dir, 
                            f"test_{base_scenario_name}_{limited_flows}limited_{unlimited_flows}unlimited_{int(rate)}mbps_{bw_category}{rand_suffix}.json"
                        )
                        with open(filename, 'w') as f:
                            json.dump(tests, f, indent=2)
                        
                        print(f"Generated {filename}")
                else:
                    # Scenarios without CBR
                    client_index = 1
                    start_time = 0
                    start_times = []
                    
                    # Add random offset to start times if randomizing
                    if randomize:
                        # Add rate-limited TCP flows
                        if limited_flows > 0:
                            for i in range(limited_flows):
                                random_offset = random.randint(0, 5)  # Random offset between 0-5 seconds
                                start_times.append(start_time + random_offset)
                                client_index += 1
                                start_time += 10  # Base spacing of 10 seconds
                        
                        # Add unlimited TCP flows
                        if unlimited_flows > 0:
                            for i in range(unlimited_flows):
                                random_offset = random.randint(0, 5)  # Random offset between 0-5 seconds
                                start_times.append(start_time + random_offset)
                                client_index += 1
                                start_time += 10  # Base spacing of 10 seconds
                    else:
                        # Original non-randomized start times
                        if limited_flows > 0:
                            for i in range(limited_flows):
                                start_times.append(start_time)
                                client_index += 1
                                start_time += 10
                        
                        if unlimited_flows > 0:
                            for i in range(unlimited_flows):
                                start_times.append(start_time)
                                client_index += 1
                                start_time += 10
                    
                    # Add stochastic traffic
                    for flow in stochastic_flows:
                        start_times.append(start_time)
                        client_index += 1
                        start_time += 10
                    
                    # Calculate the total test duration based on target experiment duration
                    total_test_duration = 0
                    if start_times:
                        min_required_duration = max(start_times) + 60  # Minimum required duration
                        total_test_duration = max(min_required_duration, total_experiment_duration)
                    
                    # Now create the actual tests with randomized segments
                    tests = []
                    client_index = 1
                    
                    # Calculate total bandwidth
                    total_bw = calculate_total_bandwidth(limited_flows, limited_rate, unlimited_flows, [])
                    bw_category = "high_load" if total_bw > 90 else "normal_load"
                    
                    # Add rate-limited TCP flows with randomized segments
                    if limited_flows > 0:
                        for i in range(limited_flows):
                            flow_start = start_times[i]
                            flow_duration = total_test_duration - flow_start
                            
                            if randomize:
                                # Generate segments with random pauses
                                segments = generate_download_segments(flow_duration)
                                test_configs = create_tcp_config_with_segments(client_index, limited_rate, flow_start, segments)
                                tests.extend(test_configs)
                            else:
                                # Original continuous download
                                tests.append(create_tcp_config(client_index, limited_rate, flow_start, flow_duration))
                            
                            client_index += 1
                    
                    # Add unlimited TCP flows with randomized segments
                    if unlimited_flows > 0:
                        for i in range(unlimited_flows):
                            flow_start = start_times[limited_flows + i]
                            flow_duration = total_test_duration - flow_start
                            
                            if randomize:
                                # Generate segments with random pauses
                                segments = generate_download_segments(flow_duration)
                                test_configs = create_tcp_config_with_segments(client_index, float('inf'), flow_start, segments)
                                tests.extend(test_configs)
                            else:
                                # Original continuous download
                                tests.append(create_tcp_config(client_index, float('inf'), flow_start, flow_duration))
                            
                            client_index += 1
                    
                    # Add stochastic traffic with longer duration (5 minutes = 300 seconds)
                    for j, flow in enumerate(stochastic_flows):
                        flow_start = start_times[limited_flows + unlimited_flows + j]
                        tests.append(create_stochastic_config(client_index, flow, flow_start, duration_seconds=300))
                        client_index += 1
                    
                    # Only save if there are any tests to run
                    if tests:
                        sub_scenario_count += 1
                        rand_suffix = "_randomized" if randomize else ""
                        filename = os.path.join(
                            output_dir, 
                            f"test_{base_scenario_name}_{limited_flows}limited_{unlimited_flows}unlimited_{bw_category}{rand_suffix}.json"
                        )
                        with open(filename, 'w') as f:
                            json.dump(tests, f, indent=2)
                        
                        print(f"Generated {filename}")
        
        print(f"Generated {sub_scenario_count} sub-configurations for scenario: {scenario}")

# Keep the original create_tcp_config and create_udp_config functions for non-randomized mode
def create_tcp_config(index: int, rate: float, start_time: int, duration: int) -> Dict[str, Any]:
    """Create a TCP test configuration with specified duration."""
    cmd = f"iperf3 -c server{index} -C reno -R -t {duration}"
    if rate != float('inf'):
        cmd = f"iperf3 -c server{index} -C reno -R -b {rate}M -t {duration}"
        
    return {
        "testname": f"iperf TCP-reno {'rate-limited' if rate != float('inf') else 'unlimited'} download #{index}",
        "host1": {
            "name": f"client{index}-mgmt",
            "cmd": cmd,
            "persist": False,
            "start_time": start_time
        }
    }

def create_udp_config(index: int, rate: float, start_time: int, duration: int) -> Dict[str, Any]:
    """Create a UDP test configuration with specified duration."""
    return {
        "testname": f"iperf UDP download #{index}",
        "host1": {
            "name": f"client{index}-mgmt",
            "cmd": f"iperf3 -c server{index} -R -u -b {rate}M -t {duration}",
            "persist": False,
            "start_time": start_time
        }
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dynamic traffic test configurations.")
    parser.add_argument("--csv", default="Experiments_dynamic_v1.csv", help="CSV file describing the test scenarios")
    parser.add_argument("--output-dir", default="test_configs", help="Directory to store generated JSON tests")
    parser.add_argument("--duration", default=600, type=int, help="Target experiment duration in seconds")
    parser.add_argument("--no-randomize", action="store_true", help="Disable randomized download segments")
    args = parser.parse_args()

    generate_test_files(
        args.csv,
        output_dir=args.output_dir,
        randomize=not args.no_randomize,
        total_experiment_duration=args.duration
    )
