# multiconn-server.py

import sys
import socket
import selectors
import types
from datetime import datetime
from threading import Thread
import time

def accept_wrapper(sock):
	conn = None
	while conn == None:
		try:
			conn, addr = sock.accept()  # Should be ready to read
		except:
			time.sleep(0.01)


	data = types.SimpleNamespace(addr=addr, data_len=0, start = datetime.now(), end = datetime.now(),started=False)
	events = selectors.EVENT_READ | selectors.EVENT_WRITE
	sel.register(conn, events, data=data)

def service_connection(key, mask):
	sock = key.fileobj
	data = key.data

	if mask & selectors.EVENT_READ:
		if not data.started:
			data.start = datetime.now()
			data.started = True
		try:
			recv_data = sock.recv(8*4096)  # Adjusted buffer size
			if recv_data:
				data.data_len += len(recv_data)
				data.end = datetime.now()
			else:
				# Connection closed by the client
				t = (data.end - data.start).total_seconds()
				vol = data.data_len * 8 / (1000 * 1000)

				#if t > 0:
				#	print(f'{t} seconds, {vol} Mbits, Rate {vol / (t * 1000)} Gbps')
				#else: 
				#	print(f'NaN seconds, {vol} Mbits, Rate NaN Gbps')

				sel.unregister(sock)
				sock.close()
				return vol
		except (BlockingIOError, ConnectionResetError, TimeoutError) as e:
			print(f"Socket error: {str(e)}")
			return 0
	return 0

if len(sys.argv) != 4:
	print(f"Usage: {sys.argv[0]} <host> <port> <time_out>")
	sys.exit(1)

host, port,time_out = sys.argv[1:4]
time_out = int(time_out)

sel = selectors.DefaultSelector()
lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
lsock.bind((host, int(port)))
lsock.listen(100)
lsock.setblocking(False)
sel.register(lsock, selectors.EVENT_READ, data=None)

start_time = datetime.now()
report_time = start_time
reporting_period = 2
num_conns = 0
num_conns_report = 0
vol = 0
vol_report = 0
reports = reporting_period
print("Interval		 Transfer		Bitrate			 Avg Bitrate		 Arrival Rate		Avg Arrival Rate		Arrivals")
try:
	while True:
		events = sel.select(timeout=5)
		for key, mask in events:
			if key.data is None:
				Thread(target=accept_wrapper,args=(key.fileobj,)).start()				 
				num_conns+=1
				num_conns_report+=1
			else:
				x = service_connection(key, mask)
				vol += x
				vol_report += x
				if (datetime.now() - report_time).total_seconds() > reporting_period:
				   t = (datetime.now() - start_time).total_seconds()
				   t_report = (datetime.now() - report_time).total_seconds()
				   #print(f"""[{reports - reporting_period}, {reports}] Average Rate {round(vol / (t * 1000),2)} Gbps, Instantaneous Rate {round(vol_report / (t_report * 1000),2)}""")
				   print(f"""{reports - reporting_period}-{reports} sec		 {round(vol_report/8,1)} MBytes	  {round(vol_report / (t_report),2)} Mbits/sec		 {round(vol / (t),2)} Mbits/sec	   {round(num_conns_report/t_report,1)} jobs/sec	   {round(num_conns/t,1)} jobs/sec		 {round(num_conns,1)} jobs			""")


				   reports += reporting_period
				   report_time = datetime.now()
				   vol_report = 0
				   num_conns_report = 0

#		if (datetime.now() - start_time).total_seconds() > time_out:
#			break;
except KeyboardInterrupt:
	print("Caught keyboard interrupt, exiting")

finally:
	sel.close()
	print(f"We saw {num_conns} connections in {(datetime.now() - start_time).total_seconds()} secs")
