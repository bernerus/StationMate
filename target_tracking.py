import time

import locator.src.maidenhead as mh
import threading
import requests
import datetime

class TargetStack:

	def __init__(self, azel, logger):
		self._target_stack=[]
		self.azel = azel
		self.logger = logger
		self.track_thread = None
		self.track_thread_running = True
		self.suspended_activity = None

	def suspend(self):
		if self._target_stack:
			self.suspended_activity = self.get_top().active

	def resume(self):
		if self._target_stack and self.suspended_activity:
			self.get_top().activate()

	def get_top(self):
		if not self._target_stack:
			return None
		ret = self._target_stack[-1]
		return ret

	def pop(self):
		if not self._target_stack:
			return None
		ret = self._target_stack.pop()
		if ret is None:
			if self.track_thread:
				self.azel.track_thread_running = False
				abortable_sleep.abort()
				self.track_thread.join()
				self.azel.logger.info("Tracking thread stopped, no more targets")
		return ret

	def push(self, tracking_object):
		if not tracking_object:
			return
		self._target_stack.append(tracking_object)
		tracking_object.start()
		self.kick_thread()

	def kick_thread(self):
		if not self.track_thread or not self.track_thread.is_alive():
			self.track_thread = threading.Thread(target=self.track_thread_function, args=(), daemon=True)
			self.track_thread.start()
		else:
			abortable_sleep.abort()

	def track_thread_function(self):
		self.track_thread_running = True
		while self.track_thread_running:
			target = self.get_top()  # type: Target
			if target is None:
				self.logger.info("No targets to track")
				self.azel.untrack()
				return
			if target.timed_out() or target.az is None:
				self.pop()
				continue
			if target.active:
				self.logger.info("Tracking target %s %d" % (target.id, target.az))
				self.azel._az_track(target.az)
			else:
				self.logger.info("Untracking target %s" % target.id)
				self.azel.untrack()

			sleep = datetime.datetime.now().second + 60 * datetime.datetime.now().minute
			#self.logger.info("Raw sleep: %d seconds" % sleep)
			sleep = target.update_in - (sleep % target.update_in)

			abortable_sleep(sleep)



class Target:

	def __init__(self, azel, target_id: str, az: int, el:int, update_in: int = 30, ttl:int =90):
		self.az = az
		self.el = el
		self.id = target_id
		self.update_in = update_in
		self.azel = azel
		self.ttl = ttl
		self.start_time = None
		self.active = True

	def start(self):
		self.start_time = time.time()

	def timed_out(self):
		return time.time() > self.start_time + self.ttl

	@property
	def az(self):
		if not self.active:
			return None
		return self._az

	@az.setter
	def az(self, value):
		self._az = value

	@property
	def id(self):
		if not self.active:
			return None
		return self._target_id

	@id.setter
	def id(self, value):
		self._target_id = value

	@property
	def el(self):
		if not self.active:
			return None

		return self._el

	@el.setter
	def el(self, value):
		self._el = value

	@property
	def update_in(self):
		return self._update_in

	@update_in.setter
	def update_in(self, value):
		self._update_in = value

	def activate(self):
		self.active = True

	def deactivate(self):
		self.active = False

class ManualTarget(Target):
	""" This target is oushed whenever tracking is to be stopped, such as when pushing the manual buttons och the controller box"""
	def __init__(self, azel):
		self.azel = azel
		super().__init__(azel, "Manual", 0, 0, 90, 15*60)  # Manual targets updates every 90 seconds and lives for 15 minutes
		self.deactivate()

class WindTarget(Target):
	""" This target type points in the current wind direction which is taken from yr.no given current location."""
	def __init__(self, azel):
		self.azel = azel
		super().__init__( azel, "YR_wind", self.get_wind_dir_from_yr(), 0, 600, 365*86400)  # Wind track lives for a year, updates every 10 minutes

	@property
	def az(self):
		if not self.active:
			return None
		return self.get_wind_dir_from_yr()

	@az.setter
	def az(self, value):
		self._az = value

	def get_wind_dir_from_yr(self):
		mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
		ret = requests.get(
			url="https://api.met.no/weatherapi/nowcast/2.0/complete?altitude=125&lat=%f&lon=%f" % (my_lat, my_lon),
			headers={"User-Agent": "bernerus.se info@bernerus.se"})
		response = ret.json()

		details = response["properties"]["timeseries"][0]["data"]["instant"]["details"]
		wfd = details["wind_from_direction"] # type: float
		wtd = wfd + 180.0
		wtd = wtd + 360.0 if wtd < 0 else wtd
		wtd = wtd - 360 if wtd > 360 else wtd
		return int(wtd)

class ScanTarget(Target):
	""" Yjis target type generates new directions on every update."""

	def __init__(self, azel, target_id: str, range_start: int, range_stop: int, period: int, step:int, sweeps: int, ttl: int = 3600):
		""" range_start sets one end of an azimuth range
		    to_az sets the other end of the range
		    period is the time in seconds between updates
		    step is number of degrees to change on every update
		    sweeps is the number of half sweeps over the range before stopping the scan
		    """
		self.range_start = azel.az2ticks(range_start)
		self.range_stop = azel.az2ticks(range_stop)
		if self.range_start > self.range_stop:
			tmp = self.range_start
			self.range_start = self.range_stop
			self.range_stop = tmp
		self.step = azel.ticks_per_degree*step
		self.period = period
		self.sweeps_left = sweeps
		az = azel.get_azel()[0]
		el = azel.get_azel()[1]
		super().__init__(azel, target_id, az, el, period, ttl)
		self.ant_direction = azel.az2ticks(az)

		if self.ant_direction > self.range_stop:
			self.step = -self.step

		self.intro = (self.ant_direction > self.range_stop or self.ant_direction < self.range_start)  # If we start outside the sweep

	def get_next_scanning_az(self):
		new_ant_direction = self.ant_direction + self.step
		if self.ant_direction >= self.range_stop or self.ant_direction <= self.range_start:
			if not self.intro:
				self.sweeps_left -= 1
				self.step = -self.step
				new_ant_direction = self.ant_direction + self.step
		else:
			self.intro = False
		if self.sweeps_left <= 0:
			return None
		self.ant_direction = new_ant_direction
		return new_ant_direction

	@property
	def az(self):
		if not self.active:
			return None
		next = self.get_next_scanning_az()
		if next is None:
			return None
		return self.azel.ticks2az(next)

	@az.setter
	def az(self, value):
		self._az = value

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