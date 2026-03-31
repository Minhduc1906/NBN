import json
from os.path import exists
import os
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

class iperf():

    def __init__(self, alg, delay, host_addrs, base_dir, streams, iteration, offset):
        self.alg = alg
        self.delay = delay
        self.host_addrs = host_addrs
        self.base_dir = base_dir
        self.streams = streams
        self.iteration = iteration
        self.offset = offset

    def parse_all(self):
        allplots = []
        p = 0
        iteration = self.iteration
        while p < iteration:
            self.iteration = p
            try:
                j = self.parse_json()
                allplots.append(j)
            except Exception as err:
                print(f"Unexpected {err=}, {type(err)=}")
            p += 1
        # fix off by one error
        self.iteration += 1
        self.allplots = allplots
        bits_array = {"h1" : [], "h3" : []}
        for data_fairness in allplots:
            bits_array["h1"].append(data_fairness['h1']["sum_received"])
            bits_array["h3"].append(data_fairness['h3']["sum_received"])
        self.compute_fairness_index(bits_array)

    def compute_fairness_index(self, bits_array):
        base_dir = self.base_dir
        fairness = ((sum(bits_array["h1"]) + sum(bits_array["h3"])) ** 2) / (2 * ((sum(bits_array["h1"]) ** 2) + (sum(bits_array["h3"]) ** 2))) 
        with open(base_dir + "fairness.txt", "x") as f:
            f.write(str(fairness))
        print(fairness)

    def parse_json(self):
        alg = self.alg
        delay = self.delay
        host_addrs = self.host_addrs
        base_dir = self.base_dir
        streams = self.streams
        iteration = self.iteration
        offset = self.offset
        return_data = {}
        count = 0
        for host in host_addrs.keys():
            return_data[host] = {'cwnd' : list(), 'time' : list(), 'Mbps' : list(), 'rtt' : list()}
        filenames = ['{2}iperf_{0}_h1-h2_{1}ms_{3}.json'.format(alg, delay, base_dir, iteration), '{2}iperf_{0}_h3-h4_{1}ms_{3}.json'.format(alg, delay, base_dir, iteration)]
        if streams == 1:
            filenames = [filenames[0]]
        for filename in filenames:
            with open(filename) as f:
                data = json.load(f)
                start_time = data['start']['timestamp']['timesecs']
                local_host = data['start']['connected'][0]['local_host']

                short_hostname = 'Blank'
                for k,v in host_addrs.items():
                    if v == local_host:
                        short_hostname = k
                #print('local_host: ' + data['start']['connected'][0]['local_host'])
                #print('time start: ' + str(data['start']['timestamp']['timesecs']))
                off = 0
                if(count > 0):
                    off = offset
                for stream in data['intervals']:
                    return_data[short_hostname]["time"].append(round(stream['streams'][0]['start'] + off, 2))
                    return_data[short_hostname]["cwnd"].append(stream['streams'][0]['snd_cwnd'])
                    return_data[short_hostname]["rtt"].append(stream['streams'][0]['rtt'])
                    return_data[short_hostname]["Mbps"].append(stream['streams'][0]['bits_per_second'] / 1000000)
                print(data["end"])
                print("BPS: " + str(data["end"]["sum_received"]["bits_per_second"]))
                return_data[short_hostname]["sum_received"] =  data["end"]["sum_received"]["bits_per_second"]
            count += 1
        #print(return_data)
        #exit()
        self.data_fairness = return_data
        return return_data

    def draw_plots(self):
        print('*** Drawing plots...')
        data_fairness = self.data_fairness
        alg = self.alg
        delay = self.delay
        host_addrs = self.host_addrs
        base_dir = self.base_dir
        streams = self.streams
        iteration = self.iteration
        offset = self.offset
        plots = [
{'title' : "Cwnd vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "CWND (bytes)", 'save' : base_dir + 'cwnd_vs_time_{0}_{1}ms_{2}', 'metric' : 'cwnd'},
{'title' : "TCP Fairness Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "Bandwidth (Mbps)", 'save' : base_dir + 'mbps_vs_time_{0}_{1}ms_{2}', 'metric' : 'Mbps' },
{'title' : "RTT vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y': "RTT (us)", 'save' : base_dir +  'rtt_vs_time_{0}_{1}ms_{2}', 'metric' : 'rtt' }
		]
        for p in plots:
            for fmt in ['.png', '.svg']:
                h1 = data_fairness['h1']
                plt.plot(h1['time'], h1[p['metric']], label='Source Host 1 (h1)')
                if streams > 1:
                    h3 = data_fairness['h3']
                    plt.plot(h3['time'], h3[p['metric']], label='Source Host 2 (h3)')
                plt.xlabel('Time (sec)')
                plt.ylabel(p['y'])
                plt.title(p['title'].format(alg.capitalize(), delay))
                plt.legend()
                plt.savefig(p['save'].format(alg, delay, str(iteration)) + fmt)
                plt.close("all")

    def draw_all_plots(self):
        print('*** Drawing all plots...')
        alg = self.alg
        delay = self.delay
        host_addrs = self.host_addrs
        base_dir = self.base_dir
        streams = self.streams
        iteration = self.iteration
        offset = self.offset
        plots = [
{'title' : "Cwnd vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "CWND (bytes)", 'save' : base_dir + 'all_cwnd_vs_time_{0}_{1}ms_{2}', 'metric' : 'cwnd'},
{'title' : "TCP Fairness Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "Bandwidth (Mbps)", 'save' : base_dir + 'all_mbps_vs_time_{0}_{1}ms_{2}', 'metric' : 'Mbps' },
{'title' : "RTT vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y': "RTT (us)", 'save' : base_dir +  'all_rtt_vs_time_{0}_{1}ms_{2}', 'metric' : 'rtt' }
		]
        for p in plots:
            for fmt in ['.png', '.svg']:
                h1_time_dict = []
                h1_metric_dict = []
                h3_time_dict = []
                h3_metric_dict = []
                for data_fairness in self.allplots:
                    h1 = data_fairness['h1']
                    h1_time_dict.append(h1['time'])
                    h1_metric_dict.append(h1[p['metric']])
                    if streams > 1:
                        h3 = data_fairness['h3']
                        h3_time_dict.append(h3['time'])
                        h3_metric_dict.append(h3[p['metric']])
                plt.scatter(h1_time_dict, h1_metric_dict, label='Source Host 1 (h1)')
                plt.scatter(h3_time_dict, h3_metric_dict, label='Source Host 2 (h3)')
                plt.xlabel('Time (sec)')
                plt.ylabel(p['y'])
                plt.title(p['title'].format(alg.capitalize(), delay))
                plt.legend()
                plt.savefig(p['save'].format(alg, delay, str(iteration)) + fmt)
                plt.close("all")

    def draw_all_boxplots(self):
        print('*** Drawing all boxplots...')
        alg = self.alg
        delay = self.delay
        host_addrs = self.host_addrs
        base_dir = self.base_dir
        streams = self.streams
        iteration = self.iteration
        offset = self.offset
        plots = [
{'title' : "Cwnd vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "CWND (bytes)", 'save' : base_dir + 'all_box_cwnd_vs_time_{0}_{1}ms_{2}', 'metric' : 'cwnd'},
{'title' : "TCP Fairness Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y' : "Bandwidth (Mbps)", 'save' : base_dir + 'all_box_mbps_vs_time_{0}_{1}ms_{2}', 'metric' : 'Mbps' },
{'title' : "RTT vs. Time Graph\n{0} TCP Congestion Control Algorithm Delay={1}ms", 'y': "RTT (us)", 'save' : base_dir +  'all_box_rtt_vs_time_{0}_{1}ms_{2}', 'metric' : 'rtt' }
		]
        try:
            for p in plots:
                for fmt in ['.png', '.svg']:
                    h1_time_dict = []
                    h1_metric_dict = []
                    h3_time_dict = []
                    h3_metric_dict = []
                    xticks_names = []
                    time_count = None
                    for data_fairness in self.allplots:
                        h1 = data_fairness['h1']
                        if time_count == None:
                            time_count = len(h1['time'])
                            i = 0
                            while i < time_count:
                                h1_metric_dict.append(list())
                                xticks_names.append(str(h1['time'][i]))
                                i += 1
                        ix = 0
                        try:
                            while ix < time_count:
                                h1_metric_dict[ix].append(h1[p['metric']][ix])
                                ix += 1
                                if streams > 1:
                                    h3 = data_fairness['h3']
                                    #h3_time_dict.append(h3['time'])
                                    #h3_metric_dict.append(h3[p['metric']])
                        except Exception as error2:
                            print(self.allplots)
                            print("An exception occurred:", error) # An exception occurred: division by zero

                    plt.figure(figsize=(30,12))
                    plt.boxplot(h1_metric_dict)
                    plt.xticks(range(0, time_count)[0::10],xticks_names[0::10])
                    #plt.scatter(h3_time_dict, h3_metric_dict, label='Source Host 2 (h3)')
                    plt.xlabel('Time (sec)')
                    plt.ylabel(p['y'])
                    plt.title(p['title'].format(alg.capitalize(), delay))
                    plt.savefig(p['save'].format(alg, delay, str(iteration)) + fmt)
                    plt.close("all")
        except Exception as error:
                print("An exception occurred:", error) # An exception occurred: division by zero
