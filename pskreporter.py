# from defusedxml import ElementTree as ET
from xml.etree.ElementTree import fromstring, ElementTree, ParseError
import requests
import os
import time
import locator.src.maidenhead as mh

import psycopg2.extras
from typing import TYPE_CHECKING
if TYPE_CHECKING:
	import psycopg2
	from main import MyApp

class Reporter:
	def __init__(self, app:'MyApp', logger, my_qth="JO67BQ68SL", max_distance=4300, min_freq=144000000, max_freq=144500000, max_db_age=3600, max_file_age=300, mode=None):
		self.app = app
		self.logger =  logger
		self.max_distance=max_distance
		self.my_qth=my_qth
		self.server_uri = "report.pskreporter.info"
		self.server_port = 4739
		self.call_signs_to_send = {} # Keyed by call signs to eliminate duplicates.
		self.last_sent_at = None
		self.max_db_age = max_db_age
		self.max_file_age = max_file_age
		self.min_freq = min_freq
		self.max_freq = max_freq

		self.retrieve_uri="https://retrieve.pskreporter.info/query?flowStartSeconds=900&frange=%d-%d" % (min_freq, max_freq)
		if mode:
			self.retrieve_uri += "&mode=%s" % mode
		self.cache_file_name="/tmp/pskreports_%d-%d%s.txt" %  (min_freq, max_freq, mode if mode else "")

		self.db = psycopg2.connect(dbname='ham_station')


	@classmethod
	def file_age_in_seconds(cls, pathname):

		return time.time() - os.path.getmtime(pathname)

	def cache_file_valid(self):
		""" Check if there are data cached, parseable and not older that max_file_age.
		    If so return the parsed element tree, else return False."""
		try:
			# self.logger.debug("Cache file %s time is %d" % (self.cache_file_name, os.path.getmtime(self.cache_file_name)))
			# self.logger.debug("Cache file age is %d seconds" % self.file_age_in_seconds(self.cache_file_name))
			if self.file_age_in_seconds(self.cache_file_name) < self.max_file_age:
				return self.parse_cached_file()
		except FileNotFoundError:
			return False
		except ParseError:
			return False
		return False

	def invalidate_cache_file(self):
		""" Invalidate the cache file by removing it, if it exists"""
		try:
			os.unlink(self.cache_file_name)
		except FileNotFoundError:
			pass

	def truncate(self, max_age = None):
		""" Truncate the reports table, deletes the entries that are older than max_age."""
		cur = self.db.cursor()
		# self.logger.info("Truncating reports table")
		q = "delete from reports where  (extract(epoch from statement_timestamp()) - happened_at) > %s"
		if max_age is None:
			max_age = self.max_db_age
		cur.execute(q,(max_age,))
		self.db.commit()

	def parse_cached_file(self):
		""" Parse the cached file"""
		with open(self.cache_file_name, "r") as fd:
			xml = fd.read()
		et = ElementTree(fromstring(xml))
		return et

	def parse_retrieved_data(self):
		"""Parse the extracted data from pskreporter. In case of a parse error, the extracted data is not cached"""
		self.logger.info("Fetching from pskreporter")
		try:
			res = requests.get(self.retrieve_uri)
			xml = res.text
			# self.logger.info("Parsing element tree")
			et = ElementTree(fromstring(xml))
			with open(self.cache_file_name, "w") as fd:
				fd.write(xml)
			return et
		except Exception as e:
			self.logger.error("Pskreporter fetch failed: %s" % e)
			raise ParseError


	def retrieve(self):
		""" Retrieve data from the PSKreporter. Use cached data in order not to annoy the PSKreporter server """
		et = self.cache_file_valid() # This both tests the age of the cached file and that it can be parsed.
		if not et:
			try:
				et = self.parse_retrieved_data()
			except ParseError:
				self.logger.error("Parse error from pskreporter, using cached file")
				et = self.parse_cached_file()
		root=et.getroot()
		# print(root)
		kids = list(root)
		# print(kids)

		with self.db, self.db.cursor() as cur:

			q0 = """INSERT INTO callbook 
											VALUES (%s, %s, %s, %s)
										   ON CONFLICT ON CONSTRAINT callbook_pk DO UPDATE SET antenna = %s, main_lobe_degrees = %s """
			all_receivers= []

			q1 = """INSERT INTO reports 
								   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
								   ON CONFLICT ON CONSTRAINT reports_pk DO UPDATE SET happened_at = %s, snr = %s, mode = %s
								"""
			all_reports = []

			q2 = """INSERT INTO callbook VALUES (%s, %s, NULL, NULL) ON CONFLICT ON CONSTRAINT callbook_pk DO NOTHING"""
			all_callbooks = []

			#self.logger.debug("Building batch data")
			for kid in kids:
				if kid.tag=="activeReceiver":
					if "callsign" in kid.attrib and "locator" in kid.attrib and len(kid.attrib["locator"]) >= 6:
						# print(kid.attrib["callsign"], kid.attrib["locator"])
						#self.logger.info("Inserting into callbook")
						all_receivers.append([kid.attrib["locator"], kid.attrib["callsign"],
									kid.attrib["antennaInformation"] if  "antennaInformation" in kid.attrib else None,
									30,
									kid.attrib["antennaInformation"] if "antennaInformation" in kid.attrib else None,
									30
						])

				if kid.tag=="receptionReport" and "frequency" in kid.attrib:
					freq = int(kid.attrib["frequency"])
					if "receiverCallsign" in kid.attrib and "receiverLocator" in kid.attrib \
							and "senderCallsign" in kid.attrib and "senderLocator" in kid.attrib \
							and "frequency" in kid.attrib and \
							self.min_freq <= freq <= self.max_freq:

						rx_cs = kid.attrib["receiverCallsign"].upper()
						rx_loc = kid.attrib["receiverLocator"].upper()
						tx_cs = kid.attrib["senderCallsign"].upper()
						tx_loc = kid.attrib["senderLocator"].upper()

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

						if (my_rx_distance[1] < self.max_distance or
								 my_tx_distance[1] < self.max_distance):
							# print(rx_cs, rx_loc, freq, my_rx_distance[1])
							#self.logger.info("Inserting into reports")

							args = [my_rx_distance[1],
									distance_between[0],
									happened_at,
									tx_cs, tx_loc, rx_cs, rx_loc,
									distance_between[0]+180 if distance_between[0] < 180 else distance_between[0]-180,
									freq, my_tx_distance[1], snr, distance_between[1], my_rx_distance[0], my_tx_distance[0], mode,
									happened_at, snr, mode]
							all_reports.append(args)
							#cur.execute(q, args)
							#self.logger.info("Inserting into callbook 2")
							all_callbooks.append([tx_loc, tx_cs])
							all_callbooks.append([rx_loc, rx_cs])

							# try:
							# 	cur.execute(q, [tx_loc, tx_cs])
							# except:
							# 	pass
							# try:
							# 	cur.execute(q, [rx_loc, rx_cs])
							# except:
							# 	pass

			# self.logger.info("Batch insert all %d receivers" % len(all_receivers))
			psycopg2.extras.execute_batch(cur, q0, all_receivers)
			# self.logger.info("Batch insert all %d reports" % len(all_receivers))
			psycopg2.extras.execute_batch(cur, q1, all_reports)
			# self.logger.info("Batch insert all %d callbook updates" % len(all_callbooks))
			psycopg2.extras.execute_batch(cur, q2, all_callbooks)