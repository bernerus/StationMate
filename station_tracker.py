import queue
from threading import Lock
import threading

station_thread = None
station_thread_lock = Lock()

import locator.src.maidenhead as mh
from typing import *

from target_tracking import StationTarget
from pskreporter import Reporter


class StationTracker:

	def __init__(self, app, logger, socket_io) -> None:
		self.logger = logger
		self.app = app
		self.azel = app.azel
		self.target_stack = self.azel.target_stack
		self.station_queue = queue.Queue()
		self.station_thread = None
		self.thread_loop = True
		self.socket_io = socket_io
		self.beaming_stations = {}
		self.other_stations = {}
		self.pskreporter50 = Reporter(self.app, self.logger, min_freq=50000000, max_freq=52000000, max_distance=10000)
		self.pskreporter50_FT8 = Reporter(self.app, self.logger, min_freq=50300000, max_freq=50400000, max_distance=20000, mode="FT8")
		self.pskreporter144 = Reporter(self.app, self.logger, min_freq=144000000, max_freq=144500000, max_distance=1800)
		self.pskreporter144_FT8 = Reporter(self.app, self.logger, min_freq=144100000, max_freq=144200000, max_distance=1200, mode="FT8")
		self.pskreporter144_MSK = Reporter(self.app, self.logger, min_freq=144310000, max_freq=144400000, max_distance=1800, mode="MSK144")
		self.pskreporter432 = Reporter(self.app, self.logger ,min_freq=430000000, max_freq=432500000, max_distance=800)
		self.pskreporter432_FT8 = Reporter(self.app, self.logger ,min_freq=430000000, max_freq=432500000, max_distance=1200, mode="FT8")
		self.pskreporter1296 = Reporter(self.app, self.logger, min_freq=1296000000, max_freq=1296500000, max_distance=300)
		self.pskreporter = self.pskreporter144
		self.current_band="144"

	def stations_update_thread(self) -> None:
		"""Check available stations and update"""
		self.app.client_mgr.logger.info("Starting stations thread")
		while self.thread_loop:
			try:
				self.beaming_stations, self.other_stations = self.get_stations()
			except Exception as e:
				self.logger.error("Stations update failed while getting stations, exception=%s"% e)

			#try:
			self.app.client_mgr.update_reachable_stations(self.beaming_stations, self.other_stations )  # self.other_stations)
			#except Exception as e:
				#self.logger.error("Stations update failed while updating, exception=%s"% e)
			st_abortable_sleep(300)
			# print("StationThread is awake")

	def set_band(self, band:str):
		if band != self.current_band:
			self.pskreporter.truncate(max_age=0)
			if band=="1296":
				self.pskreporter = self.pskreporter1296
			elif band=="432":
				self.pskreporter = self.pskreporter432
			elif band=="432-FT8":
				self.pskreporter = self.pskreporter432_FT8
			elif band=="144":
				self.pskreporter = self.pskreporter144
			elif band=="144-FT8":
				self.pskreporter = self.pskreporter144_FT8
			elif band=="144-MSK":
				self.pskreporter = self.pskreporter144_MSK
			elif band=="50":
				self.pskreporter = self.pskreporter50
			elif band=="50-FT8":
				self.pskreporter = self.pskreporter50_FT8
			else:
				raise RuntimeError("Invalid band set to station_tracker: %s" % band)
			self.current_band=band
			self.refresh()


	def has_station(self, callsign:str) ->bool:
		return callsign in self.other_stations

	def refresh(self):
		# self.logger.info("Aborting station tracker sleep")
		st_abortable_sleep.abort()

	def shutdown(self):
		if not self.station_thread:
			return
		self.thread_loop=False
		st_abortable_sleep.abort()
		self.station_thread.join()
		self.station_thread=None
		self.beaming_stations=[]
		self.other_stations=[]
		self.app.client_mgr.update_reachable_stations(self.beaming_stations, self.other_stations)

	def startup(self) -> None:
		with station_thread_lock:
			self.thread_loop = True
			if self.station_thread is None:
				self.station_thread = threading.Thread(target=self.stations_update_thread, args=(), daemon=True)
				self.station_thread.start()

	def get_stations(self):
		self.logger.debug("Truncating reports table")
		self.pskreporter.truncate()
		self.logger.debug("Retrieving reports table")
		self.pskreporter.retrieve()
		self.logger.debug("Finding beaming stations")
		stns1 = self.app.ham_op.get_reachable_stations(band=self.current_band)
		# self.logger.info("%d stations possibly beaming me" % len(stns1))
		# self.logger.info("Finding other stations")
		stns2 = self.app.ham_op.get_reachable_stations(max_beamwidth=720, band=self.current_band)
		# self.logger.info("%d stations active" % len(stns2))
		return stns1, stns2

	def get_position(self, callsign:str) -> Tuple[float,float]:
		loc = self.other_stations[callsign]["locator"]
		n, s, w, e, lat, lon = mh.to_rect(loc)
		return lon, lat

	def track_station(self, azel, callsign):
		target = StationTarget(self.azel, callsign)
		if target:
			self.target_stack.push(target)


class AbortableSleep:
	def __init__(self, id="StationThread"):
		import threading
		self._condition = threading.Condition()
		print("AbortableSleep init, id=", id)
		self.id = id
		self._aborted = None

	def __call__(self, secs):
		with self._condition:
			self._aborted = False
			# print("AbortableSleep id=%s, sleeping for %d second, thread=%s" % (self.id, secs, threading.currentThread()))
			self._condition.wait(timeout=secs)
			if self._aborted:
				# print("AbortableSleep id=%s, aborted" % self.id)
				pass
			else:
				# print("AbortableSleep id=%s, wakeup" % self.id)
				pass
			return not self._aborted

	def abort(self):
		with self._condition:
			self._aborted = True
			self._condition.notify()


st_abortable_sleep = AbortableSleep()