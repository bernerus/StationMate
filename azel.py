#import datetime

import RPi.GPIO as GPIO
from pcf8574 import *
# import locator.src.maidenhead as mh
# import threading

# import requests
from p21_defs import *
from p20_defs import *
from target_tracking import *
from flask import Flask

def sense2str(value):
	x = 1
	ret = ""
	sense_bits = {1: "A", 2: "B", 4: "E", 8: "C"}
	while x < 16:
		if value & x:
			ret += sense_bits[x]
		else:
			ret += " "
		x = x << 1
	return ret


class AzElControl:

	def __init__(self, app: Flask, logger, socket_io, hysteresis: int = 1):
		self.app = app
		self.logger=logger
		self.socket_io = socket_io
		self.az_hysteresis = hysteresis
		self.target_stack = TargetStack(self, logger)

		try:
			self.p21 = PCF(self.logger, P21_I2C_ADDRESS,
			              {P21_AZ_IND_A: (0, INPUT),
			               P21_AZ_IND_B: (1, INPUT),
			               P21_EL_PULSE: (2, INPUT),
			               P21_AZ_STOP: (3, INPUT),
			               P21_MAN_CW: (4, INPUT),
			               P21_MAN_CCW: (5, INPUT),
			               P21_MAN_UP: (6, INPUT),
			               P21_MAN_DN: (7, INPUT),
			               })
			self.p21.bit_read(P21_AZ_STOP)
			self.logger.info("Found I2C port %x" % P21_I2C_ADDRESS)

		except OSError:
			self.p21 = None

		try:
			self.p20 = PCF(self.logger, P20_I2C_ADDRESS,
			              {P20_AZ_TIMER: (0, OUTPUT),
			               P20_STOP_AZ: (1, OUTPUT),
			               P20_ROTATE_CW: (2, OUTPUT),
			               P20_RUN_EL: (3, OUTPUT),
			               P20_EL_UP: (4, OUTPUT),
			               P20_CW_KEY: (5, OUTPUT),
			               P20_UNUSED_6: (6, INPUT),
			               P20_UNUSED_7: (7, INPUT),
			               })
			self.p20.bit_read(P20_UNUSED_7)
			self.logger.info("Found I2C port %x" % P20_I2C_ADDRESS)

		except OSError:
			self.p20 = None

		# GPIO Interrupt pin
		self.AZ_INT = 17

		self.AZ_CCW_MECH_STOP: int = 0
		self.AZ_CW_MECH_STOP: int = 734

		self.CCW_BEARING_STOP: int = 274  # 278   273
		self.CW_BEARING_STOP: int = 279  # 283   278

		self.BEARING_OVERLAP = abs(self.CW_BEARING_STOP - self.CCW_BEARING_STOP)

		bearing_range = self.CW_BEARING_STOP - self.CCW_BEARING_STOP + 360

		self.ticks_per_degree = (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP) / bearing_range

		self.TICKS_OVERLAP = int(self.BEARING_OVERLAP * self.ticks_per_degree)
		self.ticks_per_rev = self.AZ_CW_MECH_STOP - self.TICKS_OVERLAP

		self.last_sent_az = None

		self.retriggering = None
		self.rotating_cw = None
		self.rotating_ccw = None

		GPIO.setmode(GPIO.BCM)
		GPIO.setup(self.AZ_INT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

		self.calibrating = None

		self.azz2inc = {0b0000: 0,
		                0b0001: 1,
		                0b0010: -1,
		                0b0101: 0,
		                0b0111: 1,
		                0b0100: -1,
		                0b1111: 0,
		                0b1110: 1,
		                0b1101: -1,
		                0b1010: 0,
		                0b1000: 1,
		                0b1011: -1
		                }

		self.last_sense = self.p21.byte_read(0xff)
		self.last_p2_sense = None
		self.az_target = None           # Target in ticks
		self.az_target_degrees = None   # Target in degrees
		self.el = 0
		self.inc = 0
		self.inc = 0
		self.az = 0

		self.az_scan_dir = None
		self.az_scan_start = self.AZ_CCW_MECH_STOP+1
		self.az_scan_period = None
		self.az_scan_stop = self.AZ_CW_MECH_STOP-1
		self.az_scan_increment = self.az2ticks(15)-self.az2ticks(0)
		self.az_scan_sweeps_left = 0
		self.az_scan_intro = False

		self.wind_thread = None
		self.tracking_wind = False
		self.last_tracking_wind = None
		self.last_status = 0xff
		self.map_mh_length = 6
		self.mhs_on_map = []
		self.distinct_mhs_on_map = False
		# Degrees below, not ticks
		self.az_sectors = [(0, 44), (45, 89), (90, 134), (135, 179), (180, 224), (225, 269), (270, 314), (315, 359)]
		self.az_sector = self.current_az_sector()

		test_az2ticks = False
		if test_az2ticks:
			self.az = 400
			ranges = list(range(160, 361)) + list(range(0, 170))

			for deg in ranges:
				self.logger.debug("%d %d %d", deg , self.az, self.az2ticks(deg))

			self.az = 270
			self.logger.debug("")

			for deg in ranges:
				self.logger.debug("%d %d %d", deg, self.az, self.az2ticks(deg))

			self.az = 0

		# self.retrack_wind_countdown = self.reset_wind_track_countdown()

	def sweep(self,start,stop,period,sweeps,increment):
		# self.az_scan_start = self.az2ticks(start)
		# self.az_scan_stop = self.az2ticks(stop)
		#
		# if self.az_scan_start > self.az_scan_stop:
		# 	return "Cannot scan over mech stop"
		#
		# self.az_scan_period = period
		# self.az_scan_increment = abs(increment)*self.ticks_per_degree
		# self.az_scan_sweeps_left = sweeps
		# self.az_scan_dir = self.az
		# self.logger.info("Initialized %d scans between %d and %d ticks, increment %d ticks every %d seconds" % (
		# 	self.az_scan_sweeps_left, self.az_scan_start, self.az_scan_stop, self.az_scan_increment , self.az_scan_period
		# ))
		# if self.az_scan_dir > self.az_scan_stop:
		# 	self.az_scan_increment = -self.az_scan_increment
		#
		# self.az_scan_intro= (self.az_scan_dir > self.az_scan_stop or self.az_scan_dir < self.az_scan_start)
		#
		# self.tracking_wind = False
		# abortable_sleep.abort()
		# # self.untrack_wind()
		# return "Scanning"
		scan = ScanTarget(self, "Scan", start, stop, period, abs(increment), sweeps, 30*60)
		self.target_stack.push(scan)

	# def reset_wind_track_countdown(self):
	# 	self.logger.debug("Resetting wind track countdown to 6")
	# 	self.retrack_wind_countdown = 6

	# def retrack_wind(self):
	# 	self.retrack_wind_countdown -= 1
	# 	self.logger.info("Wind track decremented to to %d", self.retrack_wind_countdown)
	# 	return self.retrack_wind_countdown <= 0

	# def untrack_wind(self):
	# 	self.tracking_wind = False
	# 	# self.reset_wind_track_countdown()

	def track_wind(self, value=None):
		if value is None:
			value = True
		self.tracking_wind = value

		wind_target = WindTarget(self)
		self.target_stack.push(wind_target)

		# if not self.wind_thread:
		# 	self.wind_thread = threading.Thread(target=self.wind_thread_function, args=(self,), daemon=True)
		# 	self.wind_thread.start()
		# else:
		# 	abortable_sleep.abort()
		# self.reset_wind_track_countdown()

	def track_moon(self, value=None):
		if value is None:
			value = True

		moon_target = MoonTarget(self)
		self.target_stack.push(moon_target)

	def pop_target(self):
		self.target_stack.pop()

	def track_sun(self, value=None):
		if value is None:
			value = True

		sun_target = SunTarget(self)
		self.target_stack.push(sun_target)


	def get_az_target(self):
		if self.az_target:
			return self.ticks2az(self.az_target)
		else:
			return None

	# def get_wind_dir_from_yr(self):
	# 	mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.app.ham_op.my_qth())
	# 	ret = requests.get(
	# 		url="https://api.met.no/weatherapi/nowcast/2.0/complete?altitude=125&lat=%f&lon=%f" % (my_lat, my_lon),
	# 		headers={"User-Agent": "bernerus.se info@bernerus.se"})
	# 	response = ret.json()
	#
	# 	details = response["properties"]["timeseries"][0]["data"]["instant"]["details"]
	# 	wfd = details["wind_from_direction"]
	# 	wtd = wfd + 180.0
	# 	wtd = wtd + 360.0 if wtd < 0 else wtd
	# 	wtd = wtd - 360 if wtd > 360 else wtd
	# 	return int(wtd)

	# def get_next_scanning_az(self):
	# 	new_scan_dir = self.az_scan_dir + self.az_scan_increment
	# 	if new_scan_dir >= self.az_scan_stop or new_scan_dir <= self.az_scan_start:
	# 		if not self.az_scan_intro:
	# 			self.az_scan_sweeps_left -= 1
	# 			self.az_scan_increment = -self.az_scan_increment
	# 			new_scan_dir = self.az_scan_dir + self.az_scan_increment
	# 	else:
	# 		self.az_scan_intro = False
	# 	self.az_scan_dir = new_scan_dir
	# 	return new_scan_dir



	# def wind_thread_function(self, azel):
	# 	while True:
	# 		if not azel.tracking_wind:
	# 			if azel.az_scan_sweeps_left:
	# 				self.logger.info("Sweeps left: %d" % azel.az_scan_sweeps_left)
	# 				wtd = azel.get_next_scanning_az()
	# 				self.logger.info("Az scan to %d degrees" % azel.ticks2az(wtd))
	# 				azel._az_track(azel.ticks2az(wtd))
	# 				sleep = datetime.datetime.now().second + 60 * datetime.datetime.now().minute
	# 				self.logger.info("Raw sleep: %d seconds" % sleep)
	# 				sleep = azel.az_scan_period - (sleep % azel.az_scan_period)
	# 				self.logger.info("Sleeping for %d seconds" % sleep)
	# 				abortable_sleep(sleep)
	# 				continue
	# 			if azel.retrack_wind():
	# 				azel.logger.info("Wind tracking restarted")
	# 				azel.track_wind()
	# 			else:
	# 				abortable_sleep(600)
	# 		if azel.tracking_wind:
	# 			wtd = azel.get_wind_dir_from_yr()
	# 			self.logger.info("Tracking current wind direction to %d" % wtd)
	# 			azel._az_track(wtd)
	# 			abortable_sleep(600)


	def ticks2az(self, ticks):
		az = self.CCW_BEARING_STOP + ticks / self.ticks_per_degree
		if az > 360:
			az -= 360
		if az < 0:
			az += 360
		return int(az)

	def az2ticks(self, degrees):
		degs1 = degrees - self.CCW_BEARING_STOP
		ticks = round(self.ticks_per_degree * degs1)
		while ticks < self.AZ_CCW_MECH_STOP:
			ticks += self.ticks_per_rev
		while ticks >= self.AZ_CW_MECH_STOP:
			ticks -= self.ticks_per_degree
		if (ticks - self.AZ_CCW_MECH_STOP > self.ticks_per_rev or
				ticks - self.AZ_CCW_MECH_STOP < self.TICKS_OVERLAP):
			if (ticks + self.ticks_per_rev) > self.AZ_CW_MECH_STOP:
				high_value = ticks
				low_value = ticks - self.ticks_per_rev
			else:
				low_value = ticks
				high_value = ticks + self.ticks_per_rev
			if abs(self.az - high_value) < abs(self.az - low_value):
				ticks = high_value
			else:
				ticks = low_value

		return ticks

	def status_update(self, force=False):
		if self.tracking_wind != self.last_tracking_wind or self.last_tracking_wind is None or force:
			self.app.client_mgr.push_wind_led(self.tracking_wind)
		self.last_tracking_wind = self.tracking_wind

	def el_interrupt(self, last, current):
		pass

	def manual_interrupt(self):
		target = ManualTarget(self)
		self.target_stack.push(target)
		#self.az_target = None
		#self.untrack_wind()
		self.az_stop()

	def stop_interrupt(self, _last, _current):

		if not self.p20.bit_read(P20_STOP_AZ):
			self.logger.warning("Stop interrupt skipped. timer is cleared")
			return  # Timed is cleared
		if self.p20.bit_read(P20_AZ_TIMER) and not self.calibrating and not self.rotating_cw and not self.rotating_ccw:
			self.logger.warning("Stop interrupt skipped. No rotation going on, retrig=%s, cw=%s, ccw=%s, calibrating=%s" %
			      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating))
			return  # We are not rotating
		self.logger.warning("Azel interrupt, retrig=%s, cw=%s, ccw=%s, calibrating=%s" %
		      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating))
		time.sleep(1)
		# We ran into a mech stop

		if not self.p20.bit_read(P20_ROTATE_CW):
			self.logger.warning("Mechanical stop clockwise")
			self.az = self.AZ_CW_MECH_STOP
		else:
			self.logger.warning("Mechanical stop anticlockwise")
			self.az = self.AZ_CCW_MECH_STOP

		if self.current_az_sector() != self.az_sector:
			self.az_sector = self.current_az_sector()
			self.app.client_mgr.update_map_center()
		self.logger.info("Az set to %d ticks at %d degrees" % (self.az, self.ticks2az(self.az)))
		self.app.client_mgr.send_azel(azel=(self.ticks2az(self.az), self.el))
		if self.calibrating:
			self.calibrating = False
			self.logger.info("Calibration done")
			self.az_stop()
		else:
			self._az_track()

	def az_interrupt(self, last_az, current_az):

		# print("Azint; %x %x" % (last_az, current_az))
		try:
			inc = self.azz2inc[last_az << 2 | current_az]
		except KeyError:
			self.logger.error("Key error: index=%s" % bin(last_az << 2 | current_az))
			self._az_track()
			return
		self.az += inc
		if inc:
			self.retrigger_az_timer()

		#            self.logger.debug("Ticks: %d", self.az)
		self.check_direction_az()
		self.app.client_mgr.send_azel(azel=(self.ticks2az(self.az), self.el))
		if self.current_az_sector() != self.az_sector:
			self.az_sector = self.current_az_sector()
			#self.logger.debug("Sector= %s",self.az_sector)
			self.app.client_mgr.update_map_center()
		self._az_track()

	def check_direction_az(self):
		""" Sometimes the I2C command to rotate gets misinterpreted by the hardware so this function
			checks that we are rotating in the intended direction. If not, we stop and restart whatever was tracked."""
		if self.az_target_degrees is None or abs(self.az - self.rotate_start_az) < 10:
			return  # Allow for slight wind turning in the wrong direction

		diff = self.az - self.rotate_start_az
		if (diff > 0  and self.rotating_ccw) or (diff < 0 and self.rotating_cw):
			self.logger.error("Azimuth going wrong way, stopping.")
			self.az_stop()
			self.az_stop()
			self.az_stop()
			self._az_track(self.az_target_degrees)


	def az_track(self, az=None, id=None):
		# self.reset_wind_track_countdown()
		if id is None:
			id="Fixed_"+str(az)
		self.az_target_degrees = az
		target = Target(self, id, az, 0 , 10, 3600)
		self.logger.info("az_track %s" % az)
		self.target_stack.push(target)

	def _az_track(self, target=None):
		if target is not None:
			if self.az2ticks(target) != self.az_target:
				self.az_target = self.az2ticks(target)
				self.logger.info("Tracking azimuth %d degrees = %d ticks" % (target, self.az_target))
		if self.az_target is not None:
			diff = self.az - self.az_target
			# self.logger.debug("Diff = %s", diff)
			if abs(diff) < self.az_hysteresis:
				self.az_stop()
				# self.az_target = None
				return
			if diff < 0:
				if not self.rotating_cw:
					self.az_cw()
			else:
				if not self.rotating_ccw:
					self.az_ccw()

	def az_stop(self):
		self.logger.debug("Stop azimuth rotation")
		self.rotating_ccw = False
		self.rotating_cw = False
		# self.p20.byte_write(0xff, ~self.STOP_AZ)
		# self.p20.bit_write(P20_STOP_AZ, LOW)
		# self.p20.bit_write(P20_ROTATE_CW, HIGH)

		self.p20.byte_write(P20_STOP_AZ  | P20_ROTATE_CW , P20_ROTATE_CW)
		self.logger.debug("Stopped azimuth rotation")
		time.sleep(0.4)  # Allow mechanics to settle
		self.store_az()

	def az_ccw(self):
		self.logger.debug("Rotate anticlockwise")
		self.rotating_ccw = True
		self.rotating_cw = False
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		self.p20.byte_write(P20_AZ_TIMER  | P20_ROTATE_CW, P20_ROTATE_CW)

		#self.p20.bit_write(P20_ROTATE_CW, HIGH)
		#self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.logger.debug("Rotating anticlockwise")

	def az_cw(self):
		self.logger.debug("Rotate clockwise")
		self.rotating_cw = True
		self.rotating_ccw = False
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		#self.p20.bit_write(P20_ROTATE_CW, LOW)
		#self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.rotate_start_az = self.az
		self.p20.byte_write(P20_AZ_TIMER  | P20_ROTATE_CW, 0)
		self.logger.debug("Rotating clockwise")

	def interrupt_dispatch(self, _channel):

		current_sense = self.p21.byte_read(0xff)  # type: int
		# self.logger.debug("Interrupt %s %s" % (self.sense2str(self.last_sense), self.sense2str(current_sense)))

		diff = current_sense ^ self.last_sense

		if diff & AZ_MASK:
			# self.logger.debug("Dispatching to az_interrupt")
			self.az_interrupt(self.last_sense & AZ_MASK, current_sense & AZ_MASK)
		if diff & EL_MASK:
			self.logger.debug("Dispatching to el_interrupt")
			self.el_interrupt(self.last_sense & EL_MASK, current_sense & EL_MASK)
		if diff & STOP_MASK and (current_sense & STOP_MASK == 0):
			self.logger.debug("Dispatching to stop_interrupt, diff=%x, current_sense=%x, last_sense=%x" %
			      (diff, current_sense, self.last_sense))
			self.stop_interrupt(self.last_sense & STOP_MASK, current_sense & STOP_MASK)

		if diff & MANUAL_MASK and (current_sense & MANUAL_MASK != MANUAL_MASK):
			self.logger.warning("Manual intervention detected: diff=%s, current_sense=%s, manual_mask=%s" % (bin(diff), bin(current_sense), bin(MANUAL_MASK)))
			self.manual_interrupt()

		self.last_sense = current_sense
		self.app.ham_op.status_sense()

	def retrigger_az_timer(self):
		self.retriggering = True
		self.p20.bit_write(P20_AZ_TIMER, HIGH)
		self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.retriggering = False

	def restore_az(self):
		cur = self.app.ham_op.db.cursor()
		cur.execute("SELECT az FROM azel_current where ID=0")
		rows = cur.fetchall()
		if rows:
			self.az = rows[0][0]
		else:
			self.az = 0
			cur.execute("INSERT INTO azel_current VALUES(0,0,0)")
			self.app.ham_op.db.commit()
		cur.close()

	def store_az(self):
		cur = self.app.ham_op.db.cursor()
		cur.execute("UPDATE azel_current set az = %s WHERE ID=0", (self.az,))
		cur.close()
		self.app.ham_op.db.commit()
	# self.app.ham_op.db.close()

	def startup(self):

		self.logger.debug("Restoring last saved azimuth")
		self.restore_az()
		self.logger.info("Azimuth restored to %d ticks at %d degrees" % (self.az, self.ticks2az(self.az)))
		self.az_stop()
		self.logger.debug("Starting interrupt dispatcher")
		GPIO.add_event_detect(self.AZ_INT, GPIO.FALLING, callback=self.interrupt_dispatch)
		self.track_wind()


	def get_azel(self):
		return self.ticks2az(self.az), self.el

	def calibrate(self):
		self.calibrating = True
		# tw = self.tracking_wind
		self.target_stack.suspend()
		#self.untrack_wind()
		self.az_target = None
		self.az_cw()
		time.sleep(1)
		self.az_stop()
		self.calibrating = True
		self.az_ccw()
		self.logger.warning("Awaiting calibration")
		while self.calibrating:
			self.socket_io.sleep(1)
		self.target_stack.resume()
		#self.track_wind(tw)

	def set_az(self, az):
		self.az = self.az2ticks(int(az))

	def stop(self):
		self.az_target = self.az
		#self.untrack_wind()
		self.manual_interrupt()
		self.az_scan_sweeps_left=0
		self.az_stop()

	def untrack(self):
		#self.untrack_wind()
		self.manual_interrupt()
		self.az_target = None
		self.az_target_degrees = None
		self.az_scan_sweeps_left=0
		self.az_stop()
		self.logger.info("Stopped tracking at az=%d degrees" % self.ticks2az(self.az))

	def GPIO_cleanup(self):
		GPIO.cleanup()

	def current_az_sector(self):
		az = self.get_azel()[0]
		if az >= 360:
			az -= 360
		from_az = 0
		to_az = 360
		for oct in self.az_sectors:
			if oct[0] <= az <= oct[1]:
				from_az = oct[0]
				to_az = oct[1]
				break
		return from_az, to_az

	def get_az_sector(self):
		return self.az_sector

	def update_target_list(self):
		self.target_stack.update_ui()