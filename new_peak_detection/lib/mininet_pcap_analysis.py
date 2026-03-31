import json
from os.path import exists
import os
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import subprocess
import csv

class mininet_pcap_analysis:
    # file = None
    def draw_plots(self, row_data, title, y_axis):
        print('*** Drawing pcap plots...')
        output_dir = self.output_dir
        for fmt in ['.png', '.svg']:
            plt.figure().set_size_inches(10, 5)
            #plt.set_size_inches(10, 5)
            plt.figure(dpi=1200)
            plt.plot(row_data[0], row_data[1], label=y_axis)
            plt.xticks(np.arange(min(row_data[0]), max(row_data[0])+1, 5.0))
            plt.legend()
            plt.xlabel('Time (sec)')
            plt.ylabel(y_axis)
            plt.title(title)
            plt.savefig(output_dir + title + fmt)
            plt.close("all")

    def __init__(self, filename, output_dir, iteration):
        self.file = filename
        self.output_dir = output_dir
        self.iteration = str(iteration)

    def iterate_pcap(self):
        file = self.file
        output_dir = self.output_dir
        if file is None:
            return False

        system_cmd = 'tshark -r ' + file  + ' -Y "(tcp.stream eq 1)" -T fields -e tcp.srcport -e tcp.dstport -e frame.time_relative -e tcp.analysis.bytes_in_flight -e frame.time_delta_displayed -e tcp.seq -e tcp.nxtseq -e tcp.ack -e tcp.window_size -e tcp.options.mss_val -e tcp.analysis.ack_rtt -E header=y -E separator=, -E quote=d -E occurrence=f > ' + output_dir + 'bidir_' + self.iteration + '.csv'
        print(system_cmd)
        os.system(system_cmd)
        forward_list = []
        reverse_list = []
        csv_headers = None
        with open(output_dir + 'bidir_' + self.iteration + '.csv', newline='') as csvfile:
            spamreader = csv.DictReader(csvfile)
            for packet in spamreader:
                if csv_headers == None:
                        csv_headers = list(packet)
                if packet['tcp.dstport'] == "5002":
                    forward_list.append(packet)
                else:
                    reverse_list.append(packet)
        if len(forward_list) == 0 or len(reverse_list) == 0:
            print("Empty PCAP")
            return
        with open(output_dir + 'forward_' + self.iteration + '.csv', 'w', newline='') as csvfile:
            spamwriter = csv.DictWriter(csvfile, fieldnames=csv_headers)
            spamwriter.writeheader()
            for packet in forward_list:
                spamwriter.writerow(packet)
        with open(output_dir + 'reverse_' + self.iteration + '.csv', 'w', newline='') as csvfile:
            spamwriter = csv.DictWriter(csvfile, fieldnames=csv_headers)
            spamwriter.writeheader()
            for packet in reverse_list:
                spamwriter.writerow(packet)

        row_data = [[], []]
        row_data_jitter = [[], []]
        row_data_tcp_stream_graph = [[], []]
        row_data_tcp_bytes_in_flight = [[], []]
        start_time = 0
        with open(output_dir + 'forward_' + self.iteration + '.csv', newline='') as csvfile:
            spamreader = csv.DictReader(csvfile)

            for packet in spamreader:
                # Get minumum timestamp
                if start_time == 0:
                    start_time = float(packet['frame.time_relative'])
                row_data_tcp_stream_graph[0].append(float(packet['frame.time_relative']) - start_time)
                row_data_tcp_stream_graph[1].append(int(packet['tcp.nxtseq']))
                row_data_jitter[0].append(float(packet['frame.time_relative']))
                row_data_jitter[1].append(float(packet['frame.time_delta_displayed']))
                row_data_tcp_bytes_in_flight[0].append(float(packet['frame.time_relative']))
                bif = packet['tcp.analysis.bytes_in_flight']  
                if packet['tcp.analysis.bytes_in_flight'] == '' :
                    bif = 0 
                row_data_tcp_bytes_in_flight[1].append(float(bif))
        with open(output_dir + 'reverse_' + self.iteration + '.csv', newline='') as csvfile:
            spamreader = csv.DictReader(csvfile)

            for packet in spamreader:
                # Get minumum timestamp
                row_data[0].append(float(packet['frame.time_relative']))
                row_data[1].append(int(packet['tcp.window_size']))
        self.draw_plots(row_data, 'receive_window_' + self.iteration, 'Bytes')
        self.draw_plots(row_data_tcp_stream_graph, 'tcp_stream_graph_' + self.iteration, 'Sequence Numbers')
        self.draw_plots(row_data_jitter, 'jitter_' + self.iteration, 'seconds')
        self.draw_plots(row_data_tcp_bytes_in_flight, 'bytes_in_flight_' + self.iteration, 'Bytes')
