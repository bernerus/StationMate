import queue
from threading import Lock
from flask import current_app
import requests
import threading

aircraft_thread = None
aircraft_thread_lock = Lock()


from target_tracking import PlaneTarget


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


abortable_sleep = AbortableSleep()

class AircraftTracker:

	def __init__(self, app, logger, socket_io, url: str):
		self.logger = logger
		self.app = app
		self.azel = app.azel
		self.target_stack = self.azel.target_stack
		self.aircraft_queue = queue.Queue()
		self.aircraft_thread = None
		self.socket_io = socket_io
		self.url = url
		self.current_planes = {}
		self.thread_loop = True
		self.sleeper = None

	def planes_update_thread(self):
		"""Check aircraft and update"""
		self.app.client_mgr.logger.info("Starting planes thread")
		while self.thread_loop:
			try:
				self.current_planes = self.get_planes()
				self.app.client_mgr.update_planes(self.current_planes)
			except Exception as e:
				self.logger.error("Airctaft update failed, exception=%s" % e)
			abortable_sleep(12)

	def has_plane(self, plane_id):
		return plane_id in self.current_planes

	def startup(self):
		with aircraft_thread_lock:
			self.thread_loop = True
			if self.aircraft_thread is None:
				self.aircraft_thread = threading.Thread(target=self.planes_update_thread, args=(), daemon=True)
				self.aircraft_thread.start()

	def shutdown(self):
		if not self.aircraft_thread:
			return
		self.thread_loop=False
		abortable_sleep.abort()
		self.aircraft_thread.join()
		self.aircraft_thread=None
		self.current_planes={}
		self.app.client_mgr.update_planes(self.current_planes)

	def get_planes(self):
		ret = requests.get(url=self.url+"/flights.json")
		response = ret.json()
		planes = {}
		for pid in response:
			data = response[pid]
			entry={"lat": data[1], "lng": data[2], "alt": data[4], "id":data[16], "direction": data[3], "gndspeed": data[5], "reg": data[7], "airframe": data[8], "from": data[11], "to":data[12] }
			if data[1] > 0.01 or data[2] > 0.01:
				planes[data[16]] = entry
		return planes

	def get_position(self, plane_id):
		if plane_id in self.current_planes:
			plane = self.current_planes[plane_id]
			return plane['lng'], plane['lat']
		return None, None


	def track_plane(self, azel, plane_id):
		target = PlaneTarget(self.azel, plane_id)
		self.target_stack.push(target)
