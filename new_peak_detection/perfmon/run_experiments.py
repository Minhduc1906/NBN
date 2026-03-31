import os
import subprocess
import time
import shutil
import json
import re
from glob import glob

def extract_command_duration_seconds(cmd):
    """Extract the runtime of iperf3 or D-ITG commands from a test command string."""
    match = re.search(r'(?:^|\s)-t\s+(\d+)(?:\s|$)', cmd)
    if not match:
        return 0

    duration = int(match.group(1))
    if "ITGSend" in cmd:
        return max(1, duration // 1000)
    return duration

def calculate_test_duration(test_file):
    """Estimate the full experiment duration from the scheduled test entries."""
    with open(test_file) as f:
        tests = json.load(f)

    latest_end = 0
    for test in tests:
        for host_key in ("host1", "host2"):
            host = test.get(host_key)
            if not host:
                continue
            start_time = int(host.get("start_time", 0))
            duration = extract_command_duration_seconds(host.get("cmd", ""))
            latest_end = max(latest_end, start_time + duration)

    return max(60, latest_end + 10)
 
def run_experiments(test_configs_dir="test_configs", stats_config="stats_collection.json", completed_dir="completed_experiments"):
    """
    Run experiments for each test configuration file using simultaneous_capture_trafgen.py
    and move completed test files to a separate directory.
 
    Args:
        test_configs_dir (str): Directory containing the test JSON files.
        stats_config (str): Statistics configuration file name.
        completed_dir (str): Directory to move completed test files to.
    """
    # Ensure the completed experiments directory exists
    os.makedirs(completed_dir, exist_ok=True)
    
    # Get all test JSON files
    test_files = glob(os.path.join(test_configs_dir, "*.json"))
    
    # Sort files to run in a predictable order
    test_files.sort()
    
    for test_file in test_files:
        test_name = os.path.splitext(os.path.basename(test_file))[0]
        
        # Calculate appropriate duration for this experiment
        duration = calculate_test_duration(test_file)
        
        cmd = f"./simultaneous_capture_trafgen.py -d {duration} -i 20 -t {test_file} -c {stats_config} -n {test_name}"
        
        print(f"\nRunning experiment for {test_name}")
        print(f"Calculated duration: {duration} seconds")
        print(f"Command: {cmd}")
        
        try:
            # Run the command and capture its output
            result = subprocess.run(cmd.split(), capture_output=True, text=True, check=True)
            
            print(f"Completed experiment: {test_name}")
            print(f"Output:\n{result.stdout}")  # Print standard output
            
            # Move completed test file to the completed directory
            completed_file_path = os.path.join(completed_dir, os.path.basename(test_file))
            shutil.move(test_file, completed_file_path)
            print(f"Moved {test_file} to {completed_file_path}")
            
            # Wait before starting the next experiment
            print("Waiting 20 seconds before next experiment...")
            time.sleep(20)
        
        except subprocess.CalledProcessError as e:
            print(f"Error running experiment {test_name}: {e}")
            print(f"Error Output:\n{e.stderr}")  # Print error output
        except Exception as e:
            print(f"Unexpected error during experiment {test_name}: {e}")
 
        print(f"Finished experiment: {test_name}\n")
        print("-" * 80)
 
if __name__ == "__main__":
    run_experiments()
