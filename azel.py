#import datetime

import RPi.GPIO as GPIO
from pcf8574 import *
# import locator.src.maidenhead as mh

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

	def __init__(self, app: Flask, logger, socket_io, hysteresis: int = 10):
		self.app = app
		self.logger=logger
		self.socket_io = socket_io
		self.az_hysteresis = hysteresis
		self.target_stack = TargetStack(self, logger)
		self.azrot_err_count = 0

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
			self.logger.error("I2C port %x not found" % P21_I2C_ADDRESS)
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
			self.logger.error("I2C port %x not found" % P20_I2C_ADDRESS)
			self.p20 = None

		# GPIO Interrupt pin
		self.AZ_INT = 17

		self.AZ_CCW_MECH_STOP: int = 0
		self.AZ_CW_MECH_STOP: int = 734

		self.CCW_BEARING_STOP: int = 291  # 278   273 270
		self.CW_BEARING_STOP: int = 295  # 283   278 273

		self.BEARING_OVERLAP = abs(self.CW_BEARING_STOP - self.CCW_BEARING_STOP)

		bearing_range = self.CW_BEARING_STOP - self.CCW_BEARING_STOP + 360

		self.ticks_per_degree = (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP) / bearing_range

		self.TICKS_OVERLAP = int(self.BEARING_OVERLAP * self.ticks_per_degree)
		self.ticks_per_rev = self.AZ_CW_MECH_STOP - self.TICKS_OVERLAP

		self.seconds_per_rev_cw = 81
		self.seconds_per_rev_ccw = 78

		self.seconds_per_tick_cw = self.seconds_per_rev_cw / (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP)
		self.seconds_per_tick_ccw = self.seconds_per_rev_ccw / (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP)

		self.last_sent_az = None

		self.retriggering = None
		self.rotating_cw = None
		self.rotating_ccw = None

		self.nudge_az = True

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
		self.az_control_active = False
		self.az_control_thread = None

		self.last_status = 0xff
		self.map_mh_length = 6
		self.mhs_on_map = []
		self.distinct_mhs_on_map = False
		# Degrees below, not ticks
		self.az_sectors = [(0, 44), (45, 89), (90, 134), (135, 179), (180, 224), (225, 269), (270, 314), (315, 359)]
		self.az_sector = self.current_az_sector()
		self.notify_stop = True

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

	def az_control_loop(self):
		""" This function runs in an autonomous thread"""
		if self.az_control_active:
			self.logger.info("Azimuth control thread starting")
		while(self.az_control_active):
			if self.az_target is not None:
				diff = self.az - self.az_target
				if diff:
					self.logger.debug("Diff = %s", diff)
					self.notify_stop = True
				rotated_cw = False
				rotated_ccw = False
				if abs(diff) < self.az_hysteresis:
					if self.rotating_ccw or self.rotating_ccw:
						rotated_cw = self.rotating_ccw
						rotated_ccw = self.rotating_ccw
						self.az_stop()
					if self.calibrating:
						time.sleep(1.5)
						continue
					if self.nudge_az:
						if diff < 0:
							self.notify_stop = True
							if rotated_ccw:
								time.sleep(4) # Allow stabilizing before changing direction
							self.nudge_cw(diff)
							time.sleep(2.5)
							continue
						if diff > 0:
							self.notify_stop = True
							if rotated_cw:
								time.sleep(4) # Allow stabilizing before changing direction
							self.nudge_ccw(diff)
							time.sleep(2.1)
							continue
						if self.notify_stop:
							self.az_stop()
							self.notify_stop=False
					time.sleep(2)
				else:
					rotated_cw = self.rotating_ccw
					rotated_ccw = self.rotating_ccw
					if diff < 0:
						self.notify_stop=True
						if not self.rotating_cw:
							if rotated_ccw:
								self.az_stop()
								time.sleep(1.5)  # Allow stabilizing before changing direction
							self.az_cw()
							to_sleep = (abs(diff) - self.az_hysteresis) * self.seconds_per_tick_cw
							if to_sleep > 0:
								time.sleep(to_sleep)
							continue
					if diff > 0:
						self.notify_stop=True
						if rotated_cw:
							self.az_stop()
							time.sleep(1.8)  # Allow stabilizing before changing direction
						if not self.rotating_ccw:
							self.az_ccw()
							to_sleep = (abs(diff) - self.az_hysteresis) * self.seconds_per_tick_cw
							if to_sleep > 0:
								time.sleep(to_sleep)
							continue
					time.sleep(2)
			else:
				if not self.calibrating:
					pass
					# self.logger.info("No Azel target tracked")
				time.sleep(2)
		self.az_control_active = False
		self.logger.info("Azimuth control thread stopping")

	def sweep(self,start,stop,period,sweeps,increment):
		scan = ScanTarget(self, "Scan", start, stop, period, abs(increment), sweeps, 30*60)
		self.target_stack.push(scan)


	def track_wind(self, value=None):
		wind_target = WindTarget(self)
		self.target_stack.push(wind_target)

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

	def ticks2az(self, ticks):
		az = self.CCW_BEARING_STOP + ticks / self.ticks_per_degree
		if az > 360:
			az -= 360
		if az < 0:
			az += 360
		return round(az)

	def az2ticks(self, degrees):
		degs1 = degrees - self.CCW_BEARING_STOP
		ticks = round(self.ticks_per_degree * degs1)
		while ticks < self.AZ_CCW_MECH_STOP:
			ticks += self.ticks_per_rev
		while ticks >= self.AZ_CW_MECH_STOP:
			ticks -= self.ticks_per_rev
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
		self.target_stack.update_ui()

	def el_interrupt(self, last, current):
		pass

	def manual_interrupt(self):
		target = ManualTarget(self)
		self.target_stack.push(target)
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
			self.rotating_cw = self.rotating_ccw = False
			self.az_stop()
		else:
			self.logger.warning("Mechanical stop anticlockwise")
			self.az = self.AZ_CCW_MECH_STOP
			self.rotating_cw = self.rotating_ccw = False
			self.az_stop()

		if self.current_az_sector() != self.az_sector:
			self.az_sector = self.current_az_sector()
			self.app.client_mgr.update_map_center()
		self.logger.info("Az set to %d ticks at %d degrees" % (self.az, self.ticks2az(self.az)))
		self.app.client_mgr.send_azel(azel=(self.ticks2az(self.az), self.el))
		if self.calibrating:
			self.calibrating = False
			self.logger.info("Calibration done")
			self.az_stop()
			self.target_stack.kick_thread()
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
		# self._az_track()

	def check_direction_az(self):
		""" Sometimes the I2C command to rotate gets misinterpreted by the hardware so this function
			checks that we are rotating in the intended direction. If not, we stop and restart whatever was tracked."""

		diff = self.az - self.rotate_start_az
		if (diff > 0  and self.rotating_ccw) or (diff < 0 and self.rotating_cw):
			self.logger.error("Azimuth rotation error")
			self.azrot_err_count += 1
			if self.azrot_err_count > 20:
				self.logger.error("Azimuth going wrong way, stopping.")
				self.az_stop()
				self.az_stop()
				self.az_stop()
				self.azrot_err_count = 0
				self._az_track(self.az_target_degrees)


	def az_track(self, az=None, id=None, classes=None):
		if id is None:
			id="Fixed_"+str(az)
		self.az_target_degrees = az
		target = Target(self, id, az, 0 , 10, 3600)
		if classes:
			target.set_led_classes(classes)
		self.logger.info("az_track %s" % az)
		self.target_stack.push(target)

	def _az_track(self, target=None):
		if target is not None:
			if self.az2ticks(target) != self.az_target:
				self.az_target = self.az2ticks(target)
				self.logger.info("Tracking azimuth %d degrees = %d ticks" % (target, self.az_target))

		if not self.az_control_active:
			self.az_control_thread = threading.Thread(target=self.az_control_loop, args=(), daemon=True)
			self.az_control_active = True
			self.az_control_thread.start()

		# if self.az_target is not None:
		# 	diff = self.az - self.az_target
		# 	# self.logger.debug("Diff = %s", diff)
		# 	if abs(diff) < self.az_hysteresis:
		# 		self.az_stop()
		# 		if self.calibrating:
		# 			return
		# 		if diff < 0:
		# 			self.nudge_cw()
		# 			return
		# 		if diff > 0:
		# 			self.nudge_ccw()
		# 			return
		# 		return
		# 	if diff < 0:
		# 		if not self.rotating_cw:
		# 			self.az_cw()
		# 	else:
		# 		if not self.rotating_ccw:
		# 			self.az_ccw()
		# else:
		# 	if not self.calibrating:
		# 		self.logger.info("No Azel target tracked")

	def az_stop(self):
		self.logger.debug("Stop azimuth rotation")
		self.rotating_ccw = False
		self.rotating_cw = False
		# self.p20.byte_write(0xff, ~self.STOP_AZ)
		# self.p20.bit_write(P20_STOP_AZ, LOW)
		# self.p20.bit_write(P20_ROTATE_CW, HIGH)

		self.p20.byte_write(P20_STOP_AZ  | P20_ROTATE_CW , P20_ROTATE_CW)
		time.sleep(0.4)  # Allow mechanics to settle
		self.logger.debug("Stopped azimuth rotation at %d ticks"% self.az)
		self.store_az()

	def az_ccw(self):
		self.logger.debug("Rotate anticlockwise")
		self.azrot_err_count = 0
		self.rotating_ccw = True
		self.rotating_cw = False
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		self.p20.byte_write(P20_AZ_TIMER  | P20_ROTATE_CW, P20_ROTATE_CW)
		self.rotating_ccw = False
		self.rotating_cw = False

		#self.p20.bit_write(P20_ROTATE_CW, HIGH)
		#self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.logger.debug("Rotating anticlockwise")

	def nudge_ccw(self, diff):
		self.logger.debug("Nudging anticlockwise")
		self.azrot_err_count = 0
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		self.rotating_ccw = True
		self.rotating_cw = False
		nudge_time = float((abs(diff)/3) * self.seconds_per_tick_ccw)
		self.p20.byte_write(P20_AZ_TIMER | P20_ROTATE_CW, P20_ROTATE_CW) # Start ccw
		time.sleep(nudge_time)
		self.p20.byte_write(P20_STOP_AZ | P20_ROTATE_CW, P20_ROTATE_CW) # Stop
		self.rotating_ccw = False
		self.rotating_cw = False

		# self.p20.bit_write(P20_ROTATE_CW, HIGH)
		# self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.logger.debug("Nudged anticlockwise for %f seconds" % nudge_time)


	def az_cw(self):
		self.logger.debug("Rotate clockwise")
		self.azrot_err_count = 0
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


	def nudge_cw(self,diff):
		self.logger.debug("Nudging clockwise")
		self.azrot_err_count = 0
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		#self.p20.bit_write(P20_ROTATE_CW, LOW)
		#self.p20.bit_write(P20_AZ_TIMER, LOW)
		self.rotate_start_az = self.az
		self.rotating_cw = True
		self.rotating_ccw = False
		nudge_time = float((abs(diff)/3) * self.seconds_per_tick_cw + 0.25)
		self.p20.byte_write(P20_AZ_TIMER  | P20_ROTATE_CW, 0)
		time.sleep(nudge_time)
		self.p20.byte_write(P20_STOP_AZ | P20_ROTATE_CW, P20_ROTATE_CW)  # Stop
		self.rotating_ccw = False
		self.rotating_cw = False
		self.logger.debug("Nudged clockwise for %f seconds" % nudge_time)


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
		self.last_sense = self.p21.byte_read(0xff)
		self.az_stop()
		self.logger.debug("Starting interrupt dispatcher")
		GPIO.add_event_detect(self.AZ_INT, GPIO.FALLING, callback=self.interrupt_dispatch)
		self.track_wind()


	def get_azel(self):
		return self.ticks2az(self.az), self.el

	def calibrate(self):
		if self.az < self.AZ_CW_MECH_STOP / 2:
			self.calibrate_ccw()
		else:
			self.calibrate_cw()


	def calibrate_ccw(self):
		self.calibrating = True
		self.target_stack.suspend()
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

	def calibrate_cw(self):
		self.calibrating = True
		self.target_stack.suspend()
		self.az_target = None
		self.az_ccw()
		time.sleep(1)
		self.az_stop()
		self.calibrating = True
		self.az_cw()
		self.logger.warning("Awaiting cw calibration")
		while self.calibrating:
			self.socket_io.sleep(1)
		self.target_stack.resume()

	def set_az(self, az):
		self.az = self.az2ticks(int(az))

	def stop(self):
		self.az_target = self.az
		self.az_scan_sweeps_left=0
		self.az_stop()

	def untrack(self):
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
		self.target_stack.update_ui(force=True)