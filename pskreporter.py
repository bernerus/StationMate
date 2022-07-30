# from defusedxml import ElementTree as ET
from xml.etree.ElementTree import fromstring, ElementTree
import requests
import os
import time
import maidenhead as mh

import psycopg2.extras
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import psycopg2

class Reporter:
	def __init__(self, my_qth="JO67BQ68SL",max_distance=4300):
		self.max_distance=max_distance
		self.my_qth=my_qth
		self.server_uri = "report.pskreporter.info"
		self.server_port = 4739
		self.call_signs_to_send = {} # Keyed by call signs to eliminate duplicates.
		self.last_sent_at = None

		self.retrieve_uri="https://retrieve.pskreporter.info/query?flowStartSeconds=900&frange=144000000-144500000"
		self.cache_file_name="/tmp/pskreports.txt"

		self.db = psycopg2.connect(dbname='ham_station')


	@classmethod
	def file_age_in_seconds(cls, pathname):
		return time.time() - os.path.getmtime(pathname)

	def cache_file_valid(self):
		try:
			if self.file_age_in_seconds(self.cache_file_name) < 600:
				return True
		except FileNotFoundError:
			return False
		return False

	def truncate(self):
		cur = self.db.cursor()
		q = "truncate table reports"
		cur.execute(q)
		self.db.commit()



	def retrieve(self):

		if self.cache_file_valid():
			fd= open(self.cache_file_name, "r")
			xml = fd.read()
			fd.close()
		else:
			res = requests.get(self.retrieve_uri)
			fd = open(self.cache_file_name, "w")
			xml = res.text
			fd.write(xml)
			fd.close()


		et = ElementTree(fromstring(xml))
		root=et.getroot()
		# print(root)
		kids = list(root)
		# print(kids)
		cur = self.db.cursor()
		for kid in kids:
			if kid.tag=="activeReceiver":
				if "callsign" in kid.attrib and "locator" in kid.attrib and len(kid.attrib["locator"]) >= 6:
					# print(kid.attrib["callsign"], kid.attrib["locator"])
					q = """INSERT INTO callbook 
							VALUES (%s, %s, %s, %s)
											       ON CONFLICT ON CONSTRAINT callbook_pk DO UPDATE SET antenna = %s, main_lobe_degrees = %s
											    """
					cur.execute(q, [kid.attrib["locator"], kid.attrib["callsign"],
					            kid.attrib["antennaInformation"] if  "antennaInformation" in kid.attrib else None,
					            30,
					            kid.attrib["antennaInformation"] if "antennaInformation" in kid.attrib else None,
					            30
					])

			if kid.tag=="receptionReport":
				if "receiverCallsign" in kid.attrib and "receiverLocator" in kid.attrib \
						and "senderCallsign" in kid.attrib and "senderLocator" in kid.attrib \
						and "frequency" in kid.attrib and int(kid.attrib["frequency"]) > 144000000:

					rx_cs = kid.attrib["receiverCallsign"].upper()
					rx_loc = kid.attrib["receiverLocator"].upper()
					tx_cs = kid.attrib["senderCallsign"].upper()
					tx_loc = kid.attrib["senderLocator"].upper()
					freq = int(kid.attrib["frequency"])
					mode = kid.attrib["mode"]
					snr = int(kid.attrib["sNR"])
					happened_at = int(kid.attrib['flowStartSeconds'])


					my_rx_distance = mh.distance_between(self.my_qth, rx_loc)
					try:
						my_tx_distance = mh.distance_between(self.my_qth, tx_loc)
						distance_between =  mh.distance_between(rx_loc, tx_loc)
					except ValueError:
						my_tx_distance = (0,0)
						distance_between = (0,0)

					if freq > 144000000 and \
							(my_rx_distance[1] < self.max_distance or
							 my_tx_distance[1] < self.max_distance):
						# print(rx_cs, rx_loc, freq, my_rx_distance[1])
						q = """INSERT INTO reports 
							   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
						       ON CONFLICT ON CONSTRAINT reports_pk DO UPDATE SET happened_at = %s, snr = %s, mode = %s
						    """
						args = [my_rx_distance[1],
						        distance_between[0],
						        happened_at,
						        tx_cs,
						        tx_loc, rx_cs, rx_loc,
						        distance_between[0]+180 if distance_between[0] < 180 else distance_between[0]-180,
						        freq, my_tx_distance[1], snr, distance_between[1], my_rx_distance[0], my_tx_distance[0], mode,
						        happened_at, snr, mode]
						cur.execute(q, args)
						q = """INSERT INTO callbook VALUES (%s, %s, NULL, NULL) ON CONFLICT ON CONSTRAINT callbook_pk DO NOTHING"""
						try:
							cur.execute(q, [tx_loc, tx_cs])
						except:
							pass
						try:
							cur.execute(q, [rx_loc, rx_cs])
						except:
							pass

		self.db.commit()

