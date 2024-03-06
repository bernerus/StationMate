import time

import locator.src.maidenhead as mh
import threading
import requests
import datetime
import ephem
import math

from typing import *

from geo import sphere
if TYPE_CHECKING:
	from azel import AzelController

from degree import Degree

class Target:
	"""
	A class representing a target.

	:param azel: An instance of AzelController.
	:type azel: AzelController
	:param target_id: The ID of the target.
	:type target_id: str
	:param az: The azimuth angle of the target.
	:type az: Degree
	:param el: The elevation angle of the target.
	:type el: Degree
	:param update_in: The update interval of the target in seconds (default is 30 seconds).
	:type update_in: int
	:param ttl: The time-to-live of the target in seconds (default is 90 seconds).
	:type ttl: int
	"""
	def __init__(self, azel: 'AzelController', target_id: str, az: Degree, el:Degree, distance:float = None, update_in: int = 30, ttl:int = 90):
		self.az:Degree = az  # Degrees
		self.el:Degree = el # Degrees
		self.id = target_id
		self.distance = distance
		self.update_in = update_in
		self.azel = azel
		self.ttl = ttl
		self.start_time = None
		self.active = True
		self.details = None
		self.led_classes = "fas fa-bullseye"

	def start(self):
		self.start_time = time.time()
		abortable_sleep.abort()

	@staticmethod
	def restart():
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
	def az(self)-> Optional[Degree]:
		if not self.active:
			return None
		try:
			return self._az
		except AttributeError:
			return None

	@az.setter
	def az(self, value:Degree):
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
	def el(self)-> Optional[Degree]:
		if not self.active:
			return None
		try:
			return self._el
		except AttributeError:
			return None

	@el.setter
	def el(self, value:Degree):
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

class TargetStack:
	"""
	A class for managing a stack of tracking targets.

	Parameters:
	    azel (AzelController): The AzelController object.
	    logger: The logger object.

	Attributes:
	    _target_stack (list): The stack of tracking targets.
	    azel (AzelController): The AzelController object.
	    logger: The logger object.
	    track_thread (threading.Thread): The thread for tracking targets.
	    track_thread_running (bool): Indicates if the track thread is running.
	    suspended_activity: The activity that is suspended.
	    suspended_tracking (bool): Indicates if tracking is suspended.

	Methods:
	    suspend(): Suspends tracking.
	    resume(): Resumes tracking.
	    get_top(): Returns the top target in the stack.
	    get_stack_json(): Returns the stack of targets in JSON format.
	    pop(): Removes and returns the top target in the stack.
	    push(tracking_object:Target): Adds a new target to the stack.
	    kick_thread(): Kicks off the track thread.
	    update_ui(force=False): Updates the user interface.
	    track_thread_function(): The function run by the track thread.
	"""
	def __init__(self, azel: 'AzelController', logger):
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

	def push(self, tracking_object:Target):
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
			taz:Degree = target.az  # target.az is volatile, keep the value fetched once herein
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


class ManualTarget(Target):
	"""
	Creates a ManualTarget object that represents a manual target for the AzelController.

	:param azel: An instance of AzelController.
	"""
	def __init__(self, azel: 'AzelController'):
		self.azel = azel
		super().__init__(azel, "Manual", Degree(0), Degree(0), update_in=90, ttl=15*60)  # Manual targets updates every 90 seconds and lives for 15 minutes
		self.deactivate()
		self.led_classes = "fas fa-hand"


class WindTarget(Target):
	"""
	:class: WindTarget

	A wind target class that represents a wind direction and speed target.

	Attributes:
	    - azel: An instance of `AzelController` class representing the azimuth and elevation controller.
	    - led_classes: A string representing the CSS classes for the wind target LED indicator.
	    - details: A dictionary representing the details of the wind target.

	Methods:
	    - __init__(self, azel: AzelController): Initializes a new WindTarget instance with the given AzelController instance.
	    - trigger_period(self) -> Degree: Computes the wind direction target by making a request to a weather API.
	    - active(self) -> bool: Determines if the wind target is active based on the wind speed and temperature conditions.
	    - get_html_row(self) -> str: Generates an HTML table row representing the wind target.

	Example:
	    azel_controller = AzelController()
	    wind_target = WindTarget(azel_controller)
	    wind_target.active  # False
	    wind_target.get_html_row()  # Returns an HTML table row string
	"""
	def __init__(self, azel: 'AzelController'):
		self.azel = azel
		super().__init__( azel, "YR_wind", self.trigger_period(), Degree(0), update_in=1800, ttl=365*86400)  # Wind track lives for a year, updates every 10 minutes
		self.led_classes = "fas fa-wind"

	def trigger_period(self)  -> Degree:
			mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
			ret = requests.get(
				url="https://api.met.no/weatherapi/nowcast/2.0/complete?altitude=125&lat=%f&lon=%f" % (my_lat, my_lon),
				headers={"User-Agent": "bernerus.se info@bernerus.se"})
			response = ret.json()

			self.details = response["properties"]["timeseries"][0]["data"]["instant"]["details"]
			wtd = int(self.details["wind_from_direction"] + 180.0)# type: float
			self.az = Degree(wtd)
			return self.az

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


	def __init__(self, azel: 'AzelController', target_id: str, range_start: Degree, range_stop: Degree, period: int, step:Degree, sweeps: int, ttl: int = 3600):
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
		self.step_ticks = azel.ticks_per_degree*float(step)
		self.period = period
		self.sweeps_left = sweeps
		az, el = azel.get_azel()
		super().__init__(azel, target_id, az, Degree(el), update_in=period, ttl=ttl)
		self.az_ticks = azel.az2ticks(az)

		if self.az_ticks > self.range_stop:
			self.step_ticks = -self.step_ticks

		self.led_classes = "fas fa-radar"

		self.intro = (self.az_ticks > self.range_stop or self.az_ticks < self.range_start)  # If we start outside the sweep

	def trigger_period(self)-> None:
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
	"""
	:class: MoonTarget

	This class represents a target following the Moon that can be tracked using an AzelController.

	Methods:
	    - done(): Determines if the moon target is done being tracked.
	    - __init__(azel: 'AzelController'): Initializes a MoonTarget object.
	    - trigger_period() -> Degree: Triggers a period of tracking for the moon target.

	Attributes:
	    - azel: The AzelController object used for tracking.
	    - moon: The ephem.Moon object for computing moon position.
	    - myqth: The ephem.Observer object representing the observer's location.
	    - led_classes: The LED classes used for displaying the moon target.
	    - az: The azimuth position of the moon target.
	    - el: The elevation position of the moon target.

	Example usage::

	    azel_controller = AzelController()
	    moon_target = MoonTarget(azel_controller)
	    moon_target.trigger_period()
	    if moon_target.done():
	        print('Moon target tracking complete.')
	"""
	def done(self):
		""" tracking is considered done when the Moon is below the horizon"""
		return self.el < 0 or super().done()

	def __init__(self, azel: 'AzelController'):
		self.azel = azel
		self.moon = ephem.Moon()
		self.myqth = ephem.Observer()

		mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
		self.myqth.lon = my_lon * math.pi / 180.0
		self.myqth.lat = my_lat * math.pi / 180.0

		super().__init__(azel, "Moon", Degree(0), Degree(0), update_in=241, ttl=86400)  # Moon track lives for a day and is updated every 4.01 minutes
		self.trigger_period()

		self.led_classes = "fas fa-moon"

	def trigger_period(self)  -> Degree:
		self.myqth.date = datetime.datetime.utcnow()
		self.moon.compute(self.myqth)
		self.az = self.moon.az * 180.0 / math.pi
		self.el = self.moon.alt * 180.0 / math.pi
		return self.az if self.el >= 0 else None

class SunTarget(Target):
	"""
	Represent a target for tracking the Sun.

	Attributes:
	    azel (AzelController): The AzelController object.
	    sun (ephem.Sun): The ephem Sun object.
	    myqth (ephem.Observer): The ephem Observer object.
	    led_classes (str): The classes for the LED icon.

	Methods:
	    done(): Check if the target is completed.
	    __init__(azel: AzelController): Initialize a new SunTarget object.
	    trigger_period() -> int: Trigger a period and update the target's position.

	"""
	def done(self):
		""" tracking is considered done when the Sun is below the horizon"""
		return self.el < 0 or super().done()

	def __init__(self, azel: 'AzelController'):
		self.azel = azel

		self.sun = ephem.Sun()
		self.myqth = ephem.Observer()

		mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.azel.app.ham_op.my_qth())
		self.myqth.lon = my_lon * math.pi / 180.0
		self.myqth.lat = my_lat * math.pi / 180.0

		super().__init__(azel, "Sun", Degree(0), Degree(0), update_in=240, ttl=86400)  # Sun track lives for a day and is updated every 4.08 minutes
		self.trigger_period()

		self.led_classes = "fas fa-sun"

	def trigger_period(self)  -> int:
		self.myqth.date = datetime.datetime.utcnow()
		self.sun.compute(self.myqth)
		self.az = self.sun.az * 180.0 / math.pi
		self.el = self.sun.alt * 180.0 / math.pi
		return self.az if self.el >= 0 else None

class PlaneTarget(Target):
	"""
	This class represents a target that tracks a plane using azimuth and elevation coordinates.

	Attributes:
	    azel (AzelController): An instance of the AzelController class.
	    plane_id (str): The unique identifier of the plane being tracked.
	    led_classes (str): The CSS classes for the icon representing the plane target.

	Methods:
	    __init__(azel, plane_id)
	        Initializes a new PlaneTarget object.
	    trigger_period() -> Union[int, None]
	        Returns the azimuth angle between the observer's location and the tracked plane.
	    done() -> bool
	        Checks if the plane being tracked still exists or if the tracking is done.
	"""
	def __init__(self, azel: 'AzelController', plane_id):
		self.plane_id = plane_id
		_mn, _ms, _mw, _me, self.my_lat, self.my_lon = mh.to_rect(azel.app.ham_op.my_qth())
		super().__init__(azel, plane_id, Degree(0), Degree(0), update_in=12, ttl=20*60)  # Plane track lives for 20 min and is updated every 12 seconds

		self.led_classes = "fas fa-plane"

	def trigger_period(self) -> Union[int, None]:

		(self.lng, self.lat, self.alt)  = self.azel.app.aircraft_tracker.get_position(self.plane_id)
		if self.lng is None or self.lat is None:
			return None
		mn, ms, mw, me, mlat, mlon = mh.to_rect(self.azel.app.ham_op.my_qth())
		bearing = sphere.bearing((mlon, mlat), (self.lng, self.lat))
		self.az = bearing
		distance = sphere.distance((mlon, mlat), (self.lng, self.lat)) / 1000.0

		altkm = self.alt*(0.0254*12)/1000

		self.azel.logger.debug("Plane %s: Long=%f, lat=%f, alt=%f(%f km), distance=%f" % (self.plane_id, self.lng, self.lat, self.alt, altkm, distance))

		elevation  = self.calculate_elevation(distance, self.alt*(0.0254*12)/1000, 0.145)
		self.el = elevation
		self.azel.logger.debug("Calculated bearing from %s to %s to be %f, elevation %f" % (self.azel.app.ham_op.my_qth(), self.plane_id, bearing, elevation))
		return self.az if self.el >= 0 else None


	def done(self):
		return not self.azel.app.aircraft_tracker.has_plane(self.plane_id) or super().done()

	def calculate_elevation(self, distance: float, object_altitude: float, observer_altitude: float):
		"""
		Calculate the elevation angle to an object on a certain altitude at a given distance from the observer.
		This function takes the curvature of a spherical Earth into consideration.

		Parameters:
			distance (float): Distance to the object in kilometers.
			object_altitude (float): Altitude of the object in kilometers.
			observer_altitude (float): Altitude of the observer in kilometers.

		Returns:
			elev_angle (float): Elevation angle to the object at the given distance in degrees.
		"""

		import math

		# Radius of Earth in kilometers
		R = 6371.0

		# Adjusted altitudes
		adjusted_observer_altitude = R + observer_altitude
		adjusted_object_altitude = R + object_altitude

		elev_angle = (180/math.pi) * ((object_altitude - observer_altitude)/distance - distance/(2*R))

		# The angle subtended at the centre of the Earth by the imaginary arc
		#earth_angle_rad = math.acos(
			#(math.pow(adjusted_observer_altitude, 2) + math.pow(distance, 2) - math.pow(adjusted_object_altitude, 2)) /
			#(2 * adjusted_observer_altitude * distance))

		# The angle of elevation required is the angle of the triangle at the observer subtended by the imaginary arc.

		#elev_angle_rad = math.pi / 2 - earth_angle_rad

		# Convert to degrees
		# elev_angle = math.degrees(elev_angle_rad)

		return elev_angle

class AzTarget(Target):
	"""
	:class: AzTarget

	Class representing an azimuth target.

	:param azel: An instance of AzelController representing the azimuth-elevation controller.
	:type azel: AzelController
	:param az: The azimuth value of the target.
	:type az: int

	Attributes:
	- ``azel``: An instance of AzelController representing the azimuth-elevation controller.
	- ``az``: The azimuth value of the target.

	Methods:
	- ``__init__(self, azel: AzelController, az: int)``: Initialize a new instance of the AzTarget class.
	- ``trigger_period(self) -> int``: Returns the azimuth value of the target.

	"""
	def __init__(self, azel: 'AzelController', az:Degree):
		super().__init__(azel, "AZ: %d"%az, az, Degree(5), ttl=3600)

	def trigger_period(self) -> int:
		return self.az

class MhTarget(Target):
	"""
	Initialize Maidenhead locator Target object.

	:param azel: AzelController object.
	:param what: Maidenhead locator.
	"""
	def __init__(self, azel: 'AzelController', what:str):
		self._active=False
		ham_op = azel.app.ham_op
		try:
			(az, _dist) = ham_op.distance_to( what)
			self._active=True
			azel.app.client_mgr.add_locator_rect_to_map(what)
		except (TypeError, ValueError):
			error=True
			return
		super().__init__(azel, what, round(az), Degree(5), ttl=3600)

		self.led_classes = "fas fa-globe"

	def trigger_period(self) -> int:
		return self.az

class StationTarget(Target):
	"""
	Represents a station target for tracking.

	:param azel: Instance of AzelController.
	:type azel: AzelController
	:param who: Callsign of the station.
	:type who: str
	:param given_loc: Locator information of the station (optional).
	:type given_loc: str
	"""
	def __init__(self, azel: 'AzelController', who:str, given_loc:str =None):
		self._active=False
		ham_op = azel.app.ham_op
		found_loc = ham_op.lookup_locator(who, given_loc)
		self._active = True
		if found_loc:
			(az, dist) = ham_op.distance_to(found_loc)
			azel.logger.debug("Tracking Az %s to %s at %s" % (az, who, found_loc))
			super().__init__(azel,who, round(az), Degree(5), distance=dist, ttl=3600)
		self.led_classes = "fas fa-broadcast-tower"


	def trigger_period(self) -> int:
		return self.az


class AbortableSleep:
	"""
	A class that provides a sleep function that can be aborted.

	The AbortableSleep class allows for sleeping for a specified number of seconds,
	with the ability to abort the sleep before it completes.

	:ivar _condition: A threading.Condition object used for synchronization.
	:ivar _aborted: A boolean flag indicating whether the sleep was aborted.

	Example usage:

	```python
	abortable_sleep = AbortableSleep()
	if abortable_sleep(5):
	    print("Sleep completed")
	else:
	    print("Sleep aborted")
	```

	"""
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