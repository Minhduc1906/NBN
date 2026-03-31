import sys
import socket
import selectors
import types
import numpy as np
from datetime import datetime
from threading import Thread


def start_connection(host, port, jobsize):
	try:
		s_t = datetime.now()
		server_addr = (host, port)
		send_data = np.random.bytes(jobsize)
		connid = datetime.now()
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.setblocking(False)
		sock.connect_ex(server_addr)
	
		events = selectors.EVENT_READ | selectors.EVENT_WRITE
		data = types.SimpleNamespace(
			connid=connid,		   
			recv_total=0,		
			outb = send_data,
		)
	
		sel.register(sock, events, data=data)
		e_t = datetime.now()
		print(f'Arrival took: {(e_t - s_t).total_seconds()}')
	except:
		print ('Arrival Failed...')


def service_connection(key, mask):
	sock = key.fileobj
	data = key.data
	if mask & selectors.EVENT_READ:
		recv_data = sock.recv(1024)  # Should be ready to read
	 
	if mask & selectors.EVENT_WRITE:				
		if len(data.outb) > 0:
			try:
				sent = sock.send(data.outb)			 
				data.outb = data.outb[sent:]  
			except:
				sent = 0
		else:   
			sel.unregister(sock)
			sock.close()
		
if len(sys.argv) != 7:
	print(f"Usage: {sys.argv[0]} <host> <port> <max_events> <arrival_rate jobs/sec> <job_size Mbits> <timeout_seconds>")
	sys.exit(1)

host, port, max_events, arrival_rate, job_size,time_out = sys.argv[1:7]

time_out = int(time_out)
AR = int(arrival_rate)
JOB = float(job_size)

sel = selectors.DefaultSelector()

start = datetime.now()
next_event = np.random.exponential(scale=1/AR)
max_events = int(max_events)
event_count = 0
arrivals = 0
data_len = 0
finished = False
loop = 0
try:
	while True:	
		if (datetime.now() - start).total_seconds() > time_out:
			end = datetime.now()
			break
		if (datetime.now() - start).total_seconds() > next_event:		
			next_event += np.random.exponential(scale=1/AR)		
			if event_count <= max_events:
				jobsize = int(np.random.exponential(scale=(JOB/8)*1000*1000))
				data_len+=jobsize
				Thread(target=start_connection,args=(host,int(port),jobsize)).start()			
				arrivals +=1			
				event_count +=1   
			else:
				if not finished:
					end = datetime.now()
					finished = True
			
		if not sel.get_map():		
			if event_count > max_events:
				if not finished:				
					end = datetime.now()
					finished = True
				break
		
		else:		
			events = sel.select(timeout=None)
			if events:
				for key, mask in events:				
					Thread(target=service_connection, args=(key,mask)).start()
		loop+=1
	
except KeyboardInterrupt:
	print("Caught keyboard interrupt, exiting")
finally:
	sel.close()

t_s = (end - start).total_seconds()
t_d = (datetime.now() - start).total_seconds()
print(f'Offered Load {round(data_len*8/(t_s*1000*1000*1000),2)} Gbps (target={round(JOB*AR/1000,2)} Gbps), Cell Thp {round(data_len*8/(t_d*1000*1000*1000),2)} Gbps, Arrival Rate {round(arrivals/t_s,2)} jobs/sec (target={AR} jobs/sec), Itts {loop} ({round(loop/t_d,1)} itts/sec)')

