import queue
from threading import Lock
import threading

station_thread = None
station_thread_lock = Lock()

import locator.src.maidenhead as mh
from typing import *

from target_tracking import StationTarget


class StationTracker:

	def __init__(self, app, logger, socket_io) -> None:
		self.logger = logger
		self.app = app
		self.azel = app.azel
		self.target_stack = self.azel.target_stack
		self.station_queue = queue.Queue()
		self.station_thread = None
		self.socket_io = socket_io
		self.beaming_stations = {}
		self.other_stations = {}

	def stations_update_thread(self) -> None:
		"""Check available stations and update"""
		self.app.client_mgr.logger.info("Starting stations thread")
		while True:
			self.beaming_stations, self.other_stations = self.get_stations()
			self.app.client_mgr.update_reachable_stations(self.beaming_stations, self.other_stations)
			st_abortable_sleep(300)

	def has_station(self, callsign:str) ->bool:
		return callsign in self.other_stations

	def refresh(self):
		self.logger.info("Aborting station tracker sleep")
		st_abortable_sleep.abort()

	def startup(self) -> None:
		with station_thread_lock:
			if self.station_thread is None:
				self.station_thread = threading.Thread(target=self.stations_update_thread, args=(), daemon=True)
				self.station_thread.start()

	def get_stations(self):
		from pskreporter import Reporter
		self.app.pskreporter = Reporter()
		self.app.pskreporter.truncate()
		self.app.pskreporter.retrieve()
		stns1 = self.app.ham_op.get_reachable_stations()
		self.logger.info("%d stations possibly beaming me" % len(stns1))
		stns2 = self.app.ham_op.get_reachable_stations(max_beamwidth=360)
		self.logger.info("%d stations active" % len(stns2))
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
	def __init__(self):
		import threading
		self._condition = threading.Condition()
		self._aborted = None

	def __call__(self, secs):
		with self._condition:
			self._aborted = False
			self._condition.wait(timeout=secs)
			return not self._aborted

	def abort(self):
		with self._condition:
			self._condition.notify()
			self._aborted = True


st_abortable_sleep = AbortableSleep()