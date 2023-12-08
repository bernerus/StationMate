import time

import locator.src.maidenhead as mh
import threading
import requests
import datetime
import ephem
import math


from geo import sphere

class TargetStack:
	def __init__(self, azel, logger):
		self._target_stack=[]
		self.azel = azel
		self.logger = logger
		self.track_thread = None
		self.track_thread_running = True
		self.suspended_activity = None
		self.suspended_tracking = False

	def suspend(self):
		if self._target_stack:
			self.suspended_activity = self.get_top().active
			self.suspended_tracking = True
			self.update_ui()

	def resume(self):
		if self._target_stack and self.suspended_tracking:
			self.suspended_tracking = False
			if self.suspended_activity:
				self.get_top().activate()
			self.update_ui()

	def get_top(self):
		if not self._target_stack:
			return None
		try:
			ret = self._target_stack[-1]
			return ret
		except IndexError:
			return None

	def get_stack_json(self):
		ret = []
		for item in self.track_thread[::-1]: # type: Target
			r = {"id": item.id, "az":item.az, "el":item.el, "active":item.active, "started":item.start_time, "ttl":item.ttl}
			ret.append(r)
		return ret

	def pop(self):
		if not self._target_stack:
			return None
		top = self._target_stack.pop()
		if top:
			self.logger.info("Popped target %s from stack." % top.id)
		else:
			self.logger.info("Target stack was empty" % top.id)
			return None

		self.update_ui(force=True)
		if not self._target_stack:
			# if self.track_thread:
				# self.azel.track_thread_running = False
				#self.azel.logger.info("Stopping track_thread, no more targets")
				# self.track_thread.join()
			return None  # The stack is empty

		while self._target_stack[-1].seconds_left() <= 0:  # Top element is expired
			self._target_stack.pop()  # Pop away top element
			if not self._target_stack: # Return if stack is empty
				return None

		self._target_stack[-1].restart() # We ahe s valid top element, restart i.
		self.kick_thread()

		return top  # Returns the top element that we wished to pop away.

	def push(self, tracking_object):
		if not tracking_object:
			return
		if not hasattr(tracking_object, "update_in"):
			return
		self.logger.info("Pushing target id %s, az=%s, el=%s" %(tracking_object.id, tracking_object.az, tracking_object.el))
		self._target_stack.append(tracking_object)
		tracking_object.start()
		self.update_ui(force=True)
		self.kick_thread()

	def kick_thread(self):
		if not self.track_thread or not self.track_thread.is_alive():
			self.track_thread = threading.Thread(target=self.track_thread_function, args=(), daemon=True)
			self.track_thread.start()
		else:
			abortable_sleep.abort()

	def update_ui(self, force=False):
		if not force:
			return
		tgts = self._target_stack[::-1]
		self.azel.app.client_mgr.update_target_list(tgts)
		current_tracking_led_classes = None
		if self.get_top():
				current_tracking_led_classes = self.get_top().led_classes
		# self.logger.debug("Pushing class %s to track_led" % (current_tracking_led_classes))
		self.azel.app.client_mgr.push_track_led(current_tracking_led_classes)

	def track_thread_function(self):
		self.track_thread_running = True
		while self.track_thread_running:
			if self.suspended_tracking:
				abortable_sleep(1)
				continue
			target = self.get_top()  # type: Target
			if target is None:
				self.logger.info("No targets to track")
				self.azel.untrack()
				return
			target.trigger_period() # Notify that we have started a new period
			taz=target.az  # target.az is volatile, keep the value fetched once herein
			if target.done() or (taz is None and target.active):
				# self.logger.debug("Popping myself away: Target=%s, done=%s, taz=%s, active=%s" % (target.id, target.done(), taz, target.active))
				self.pop()
				self.update_ui(force=True)
				continue
			if target.active:
				if taz != self.azel.az:
					self.logger.info("Tracking target %s %s°" % (target.id, taz))
					self.azel._az_track(taz)
					self.update_ui(force=True)
			else:
				self.logger.info("Untracking target %s" % target.id)
				self.azel.untrack()
				self.update_ui(force=True)
			sleep = datetime.datetime.now().second + 60 * datetime.datetime.now().minute
			#self.logger.info("Raw sleep: %d seconds" % sleep)
			sleep = target.update_in - (sleep % target.update_in)
			#self.logger.info("Cooked sleep: %d seconds" % sleep)
			abortable_sleep(sleep)

class Target:

	def __init__(self, azel, target_id: str, az: int, el:int, update_in: int = 30, ttl:int = 90):
		self.az = az  # Degrees
		self.el = el # Degrees
		self.id = target_id
		self.update_in = update_in
		self.azel = azel
		self.ttl = ttl
		self.start_time = None
		self.active = True
		self.led_classes = "fas fa-bullseye"

	def start(self):
		self.start_time = time.time()
		abortable_sleep.abort()

	def restart(self):
		abortable_sleep.abort()

	def seconds_left(self):
		return self.start_time + self.ttl - time.time()

	def done(self):
		if self.start_time:
			ret = time.time() > self.start_time + self.ttl
			self.azel.logger.debug("Target %s, done=%s, time=%s, start_time=%s, ttl=%s, tl=%4.0f" %
			                  (self.id, ret, time.time(), self.start_time, self.ttl, self.ttl - (time.time()-self.start_time)))
			return time.time() > self.start_time + self.ttl
		else:
			self.azel.logger.debug("Target %s, done=false, time=%s, start_time=%s, ttl=%s" %
			                  (self.id, time.time(), self.start_time, self.ttl))
			return False

	def set_led_classes(self, classes):
		self.led_classes = classes

	@property
	def active(self):
		try:
			return self._active
		except AttributeError:
			return None

	@active.setter
	def active(self, value):
		self._active = value

	@property
	def ttl(self):
		try:
			return self._ttl
		except AttributeError:
			return None

	@ttl.setter
	def ttl(self, value):
		self._ttl = value

	@property
	def az(self):
		if not self.active:
			return None
		try:
			return self._az
		except AttributeError:
			return None

	@az.setter
	def az(self, value):
		self._az = value

	@property
	def id(self):
		#if not self.active:
			#return None
		try:
			return self._target_id
		except AttributeError:
			return None

	@id.setter
	def id(self, value):
		self._target_id = value

	@property
	def el(self):
		if not self.active:
			return None
		try:
			return self._el
		except AttributeError:
			return None

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

	def trigger_period(self) -> int:
		return 0

	def get_html_row(self):
		az = self.az if self.az is not None else -360
		el = self.el if self.el is not None else -180
		ts = "<td>%s</td><td>%s</td><td>%4.2f/%3.2f</td><td>%s</td><td>%s</td><td>%s</td>" % (self.id, self.active, az, el, self.update_in, int(self.ttl), int(self.seconds_left()))
		return ts

class ManualTarget(Target):
	""" This target is pushed whenever tracking is to be stopped, such as when pushing the manual buttons on the controller box"""
	def __init__(self, azel):
		self.azel = azel
		super().__init__(azel, "Manual", 0, 0, update_in=90, ttl=15*60)  # Manual targets updates every 90 seconds and lives for 15 minutes
		self.deactivate()
		self.led_classes = "fas fa-hand"


class WindTarget(Target):
	""" This target type points in the current wind direction which is taken from yr.no given current location."""
	def __init__(self, azel):
		self.azel = azel
		super().__init__( azel, "YR_wind", self.trigger_period(), 0, update_in=600, ttl=365*86400)  # Wind track lives for a year, updates every 10 minutes
		self.led_classes = "fas fa-wind"

	def trigger_period(self)  -> int:
			mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
			ret = requests.get(
				url="https://api.met.no/weatherapi/nowcast/2.0/complete?altitude=125&lat=%f&lon=%f" % (my_lat, my_lon),
				headers={"User-Agent": "bernerus.se info@bernerus.se"})
			response = ret.json()

			self.details = response["properties"]["timeseries"][0]["data"]["instant"]["details"]
			wfd = self.details["wind_from_direction"] # type: float
			wtd = wfd + 180.0
			wtd = wtd + 360.0 if wtd < 0 else wtd
			wtd = wtd - 360 if wtd > 360 else wtd
			self.az = wtd
			return int(wtd)

	@Target.active.getter
	def active(self):
		if not self.details:
			return False
		if self.details["wind_speed_of_gust"] > 10  or self.details["wind_speed"] > 7:
			return True

		if self.details["air_temperature"] < -4 and time.localtime().tm_hour > 6:
			return True   # Avoid freezing the rotator by moving it around now and then, but not during the night,

		return False # No need for turning around


	def get_html_row(self):
		if self.details:
			wfd = self.details["wind_from_direction"]  # type: float
			wtd = wfd + 180.0
			wtd = wtd + 360.0 if wtd < 0 else wtd
			az = wtd - 360 if wtd > 360 else wtd
			ts = "<td>%s</td><td>%s</td><td>%4.2f/0.00</td><td>%s</td><td>%s</td><td>%s</td><td>speed=%2.1f</td><td>gusts=%2.1f</td>" % (self.id, self.active,az,self.update_in, int(self.ttl), int(self.seconds_left()), self.details["wind_speed"], self.details["wind_speed_of_gust"])
		else:
			ts = "<td>%s</td><td>%s</td><td>None/None</td><td>%s</td><td>%s</td><td>%s</td>" % (self.id, self.active, self.update_in, int(self.ttl), int(self.seconds_left()))

		return ts


class ScanTarget(Target):
	""" This target type generates new directions on every update."""

	def __init__(self, azel, target_id: str, range_start: int, range_stop: int, period: int, step:int, sweeps: int, ttl: int = 3600):
		""" range_start sets one end of an azimuth range
		    to_az sets the other end of the range
		    period is the time in seconds between updates
		    step is number of degrees to change on every update
		    sweeps is the number of half sweeps over the range before stopping the scan
		    """
		self.azel = azel
		self.range_start = azel.az2ticks(range_start)
		self.range_stop = azel.az2ticks(range_stop)
		if self.range_start > self.range_stop:
			tmp = self.range_start
			self.range_start = self.range_stop
			self.range_stop = tmp
		self.step_ticks = azel.ticks_per_degree*step
		self.period = period
		self.sweeps_left = sweeps
		az = azel.get_azel()[0]
		el = azel.get_azel()[1]
		super().__init__(azel, target_id, az, el, update_in=period, ttl=ttl)
		self.az_ticks = azel.az2ticks(az)

		if self.az_ticks > self.range_stop:
			self.step_ticks = -self.step_ticks

		self.led_classes = "fas fa-radar"

		self.intro = (self.az_ticks > self.range_stop or self.az_ticks < self.range_start)  # If we start outside the sweep

	def trigger_period(self):
		new_az_ticks = self.az_ticks + self.step_ticks
		if self.az_ticks >= self.range_stop or self.az_ticks <= self.range_start:
			if not self.intro:
				self.sweeps_left -= 1
				self.step_ticks = -self.step_ticks
				new_az_ticks = self.az_ticks + self.step_ticks
		else:
			self.intro = False
		if self.sweeps_left <= 0:
			return None
		self.az_ticks = new_az_ticks
		self.az = self.azel.ticks2az(new_az_ticks)
		return

	def done(self):
		return self.sweeps_left <= 0 or super().done()

	def get_html_row(self):
		ts = super().get_html_row()
		ts += "<td>sweeps_left=%s</td><td>Chase=%s</td>" % (self.sweeps_left, self.intro)
		return ts

class MoonTarget(Target):

	def done(self):
		return self.el < 0 or super().done()

	def __init__(self, azel):
		self.azel = azel
		self.moon = ephem.Moon()
		self.myqth = ephem.Observer()

		mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
		self.myqth.lon = my_lon * math.pi / 180.0
		self.myqth.lat = my_lat * math.pi / 180.0

		super().__init__(azel, "Moon", 0, 0, update_in=241, ttl=86400)  # Moon track lives for a day and is updated every 4.01 minutes
		self.trigger_period()

		self.led_classes = "fas fa-moon"

	def trigger_period(self)  -> int:
		self.myqth.date = datetime.datetime.utcnow()
		self.moon.compute(self.myqth)
		self.az = self.moon.az * 180.0 / math.pi
		self.el = self.moon.alt * 180.0 / math.pi
		return self.az if self.el >= 0 else None

class SunTarget(Target):

	def done(self):
		return self.el < 0 or super().done()

	def __init__(self, azel):
		self.azel = azel

		self.sun = ephem.Sun()
		self.myqth = ephem.Observer()

		mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
		self.myqth.lon = my_lon * math.pi / 180.0
		self.myqth.lat = my_lat * math.pi / 180.0

		super().__init__(azel, "Sun", 0, 0, update_in=240, ttl=86400)  # Sun track lives for a day and is updated every 4.08 minutes
		self.trigger_period()

		self.led_classes = "fas fa-sun"

	def trigger_period(self)  -> int:
		self.myqth.date = datetime.datetime.utcnow()
		self.sun.compute(self.myqth)
		self.az = self.sun.az * 180.0 / math.pi
		self.el = self.sun.alt * 180.0 / math.pi
		return self.az if self.el >= 0 else None

class PlaneTarget(Target):

	def __init__(self, azel, plane_id):
		self.plane_id = plane_id
		_mn, _ms, _mw, _me, self.my_lat, self.my_lon = mh.to_rect(azel.app.ham_op.my_qth())
		super().__init__(azel, plane_id, 0, 0, update_in=12, ttl=20*60)  # Plane track lives for 20 min and is updated every 12 seconds

		self.led_classes = "fas fa-plane"

	def trigger_period(self) -> int:

		(self.lng, self.lat)  = self.azel.app.aircraft_tracker.get_position(self.plane_id)
		if self.lng is None or self.lat is None:
			return None
		mn, ms, mw, me, mlat, mlon = mh.to_rect(self.azel.app.ham_op.my_qth())
		self.az = sphere.bearing((mlon, mlat), (self.lng, self.lat))
		self.azel.logger.debug("Calculated bearing from %s to %s to be %f" % (self.azel.app.ham_op.my_qth(), self.plane_id, self.az))
		return self.az if self.el >= 0 else None


	def done(self):
		return not self.azel.app.aircraft_tracker.has_plane(self.plane_id) or super().done()

class AzTarget(Target):
	def __init__(self, azel, az):
		super().__init__(azel, "AZ: %d"%az, int(az), 5, ttl=3600)

	def trigger_period(self) -> int:
		return self.az

class MhTarget(Target):
	def __init__(self, azel, what:str):
		self._active=False
		ham_op = azel.app.ham_op
		try:
			(az, _dist) = ham_op.distance_to( what)
			self._active=True
			azel.app.client_mgr.add_mh_on_map(what)
		except (TypeError, ValueError):
			error=True
			return
		super().__init__(azel, what, round(az), 5, ttl=3600)

		self.led_classes = "fas fa-globe"

	def trigger_period(self) -> int:
		return self.az

class StationTarget(Target):
	def __init__(self, azel, who:str, given_loc:str =None):
		self._active=False
		ham_op = azel.app.ham_op
		found_loc = ham_op.lookup_locator(who, given_loc)
		self._active = True
		if found_loc:
			(az, _dist) = ham_op.distance_to(found_loc)
			azel.logger.debug("Tracking Az %s to %s at %s" % (az, who, found_loc))
			super().__init__(azel,who, round(az), 5, ttl=3600)
		self.led_classes = "fas fa-broadcast-tower"


	def trigger_period(self) -> int:
		return self.az


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