from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from main import MyApp


import RPi.GPIO as GPIO
from pcf8574 import *
# import locator.src.maidenhead as mh
# import requests
from p21_defs import *
from p20_defs import *
from target_tracking import *
import hamop
from degree import Degree

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


class AzelController:

	def __init__(self, app: 'MyApp', logger, socket_io, hysteresis: int = 10):
		self.last_sense = None
		self.app = app
		self.ham_op = self.app.ham_op # type: hamop.HamOp
		self.logger=logger
		self.socket_io = socket_io
		self.az_hysteresis:int = hysteresis
		self.target_stack = TargetStack(self, logger)
		self.az_rotation_err_count:int = 0
		self.disable_tracking:bool = False

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
			              {P20_AZ_TIMER_L: (0, OUTPUT),
			               P20_STOP_AZ_L: (1, OUTPUT),
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

		self.CCW_BEARING_STOP: Degree = Degree(293)  # 278   273 270
		self.CW_BEARING_STOP: Degree = Degree(302)  # 283   278 273

		self.BEARING_OVERLAP:Degree = Degree(self.CW_BEARING_STOP - self.CCW_BEARING_STOP)

		bearing_range:Degree = 360 + self.BEARING_OVERLAP

		self.ticks_per_degree:float = (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP) / bearing_range

		self.TICKS_OVERLAP = int(float(self.BEARING_OVERLAP) * self.ticks_per_degree)
		self.ticks_per_rev:int = self.AZ_CW_MECH_STOP - self.TICKS_OVERLAP

		self.seconds_per_rev_cw:float = 81.0
		self.seconds_per_rev_ccw:float = 78.0

		self.seconds_per_tick_cw:float = self.ham_op.fetch_config_value("float", "az_cw_speed", default=self.seconds_per_rev_cw / (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP))
		self.seconds_per_tick_ccw:float = self.ham_op.fetch_config_value("float", "az_ccw_speed", default=self.seconds_per_rev_ccw / (self.AZ_CW_MECH_STOP - self.AZ_CCW_MECH_STOP))

		self.last_sent_az = None

		self.retriggering:bool = False
		self.rotating_cw:bool = False
		self.rotating_ccw:bool = False
		self.rotated_cw:bool = False
		self.rotated_ccw:bool = False
		self.rotating_manual:bool = False

		self.nudge_az:bool = True

		GPIO.setmode(GPIO.BCM)
		GPIO.setup(self.AZ_INT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

		self.calibrating:bool = False

		""" az2inc converts between reading fork changes to azimuth tick changes to apply.
			The first tw obits signifies the fork code previously known, and the last two bits
			that is currently read. There are combinations that hardware-wise should not occur, 
			like 0011 or 1100, these are deliberately not entered into the table, but should
			generate a KeyException. """
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
		self.az_target:int = 0           # Target in ticks
		self.az_target_degrees:Degree = Degree(None)   # Type: Degree
		self.el:int = 0
		self.az:int = 0
		self.rotate_start_az = self.az

		self.az_control_active = False
		self.az_control_thread = None

		self.last_status = 0xff
		self.stop_count = 0
		self.az_at_stop = 0

		# Degrees below, not ticks. Split circle en 8 slices.
		self.az_sectors:List[Tuple[Degree,Degree]] = [(Degree(0),   Degree(44)),
		                                              (Degree(45),  Degree(89)),
		                                              (Degree(90),  Degree(134)),
		                                              (Degree(135), Degree(179)),
		                                              (Degree(180), Degree(224)),
		                                              (Degree(225), Degree(269)),
		                                              (Degree(270), Degree(314)),
		                                              (Degree(315), Degree(359))
		                                              ]

		self.az_sector:Tuple[Degree,Degree] = self.current_az_sector()
		self.notify_stop:bool = True

		test_az2ticks:bool = False
		if test_az2ticks:
			self.az = 400
			ranges = list(range(160, 361)) + list(range(0, 170))

			for deg in ranges:
				self.logger.debug("%d %d %d", deg , self.az, self.az2ticks(Degree(deg)))

			self.az = 270
			self.logger.debug("")

			for deg in ranges:
				self.logger.debug("%d %d %d", deg, self.az, self.az2ticks(Degree(deg)))

			self.az = 0

	def disable_control(self):
		self.stop_azimuth_control()
		self.az_stop()
		self.disable_tracking = True  # This even disables the azimuth indication tracking

	def enable_control(self):
		self.disable_tracking = False  # This even disables the azimuth indication tracking
		self.start_azimuth_control()

	def az_nudge(self, current_diff)-> bool:
		if current_diff < 0:
			self.notify_stop = True
			if self.rotated_ccw:
				time.sleep(4)  # Allow stabilizing before changing direction
			self.nudge_cw(current_diff)
			time.sleep(2.5)
			return True
		if current_diff > 0:
			self.notify_stop = True
			if self.rotated_cw:
				time.sleep(4)  # Allow stabilizing before changing direction
			self.nudge_ccw(current_diff)
			time.sleep(2.1)
			return True
		if self.notify_stop:
			self.az_stop()
			self.notify_stop = False
		return False

	def az_rotate(self, current_diff)->int:
		if current_diff < 0:
			self.notify_stop = True
			if not self.rotating_cw:
				if self.rotated_ccw:
					self.az_stop()
					time.sleep(1.5)  # Allow stabilizing before changing direction
				self.az_cw()
				self.rotated_cw = True
				to_sleep = (abs(current_diff) - self.az_hysteresis) * self.seconds_per_tick_cw
				self.logger.debug("Sleeping for %s seconds for diff=%s rotating cw" % (to_sleep, current_diff))
				if to_sleep > 0:
					time.sleep(to_sleep)
				return to_sleep
		if current_diff > 0:
			self.notify_stop = True
			if self.rotated_cw:
				self.az_stop()
				time.sleep(1.8)  # Allow stabilizing before changing direction
			if not self.rotating_ccw:
				self.rotated_ccw = True
				self.az_ccw()
				to_sleep = (abs(current_diff) - self.az_hysteresis) * self.seconds_per_tick_cw
				self.logger.debug("Sleeping for %s seconds for diff=%s rotating ccw" % (to_sleep, current_diff))
				if to_sleep > 0:
					time.sleep(to_sleep)
				return to_sleep
		return 0

	def az_control_loop(self)->None:
		""" This function runs in an autonomous thread"""

		self.logger.info("Azimuth control thread starting")
		previous_diff=0
		self.rotated_cw=None
		self.rotated_ccw=None
		slept=0
		while self.az_control_active:
			if self.az_target is not None:
				current_diff = self.az - self.az_target
				if current_diff:
					if previous_diff and slept and previous_diff != current_diff:
						measured_speed = slept / abs(previous_diff - current_diff)
						self.adapt_rotation_speed(measured_speed)
					else:
						self.logger.info("Speed adaption not performed")
					self.logger.debug("New Azimuth diff = %s", current_diff)
					self.notify_stop = True
				#self.rotated_cw = False
				#self.rotated_ccw = False
				if abs(current_diff) < self.az_hysteresis:
					previous_diff = 0
					if self.rotating_ccw or self.rotating_cw:
						#self.rotated_cw = self.rotating_cw
						#self.rotated_ccw = self.rotating_ccw
						self.az_stop()
					if self.calibrating:
						time.sleep(1.5)
						continue
					if self.nudge_az:
						if self.az_nudge(current_diff):
							continue
					time.sleep(2)
				else:
					previous_diff=current_diff
					self.rotated_cw = self.rotating_cw
					self.rotated_ccw = self.rotating_ccw
					slept = self.az_rotate(current_diff)
					if slept:
						continue
					time.sleep(2)
			else:
				if not self.calibrating:
					pass
					# self.logger.info("No Azel target tracked")
				time.sleep(2)
		self.az_control_active = False
		self.logger.info("Azimuth control thread stopping")

	def adapt_rotation_speed(self, measured_speed):
		if self.rotated_cw:
			speed_change = (measured_speed - self.seconds_per_tick_cw) / self.seconds_per_tick_cw
			self.logger.debug("Measured cw speed:%s, anticipated: %f" % (measured_speed, self.seconds_per_tick_cw))
			if 0.01 < abs(speed_change) < 0.1:
				self.seconds_per_tick_cw *= 1 + 0.5 * speed_change
				self.ham_op.set_config_data("float","az_cw_speed",self.seconds_per_tick_cw)
				self.logger.info("CW speed adaption: measured change is %2.2f%%, new speed set to %s" % (speed_change * 100, self.seconds_per_tick_cw))
		elif self.rotated_ccw:
			speed_change = (measured_speed - self.seconds_per_tick_ccw) / self.seconds_per_tick_ccw
			self.logger.debug("Measured ccw speed:%s, anticipated: %f" % (measured_speed, self.seconds_per_tick_cw))
			if 0.01 < abs(speed_change) < 0.1:
				self.seconds_per_tick_ccw *= 1 + 0.5 * speed_change
				self.ham_op.set_config_data("float","az_ccw_speed",self.seconds_per_tick_ccw)
				self.logger.info("CCW speed adaption: measured change is %2.2f%%, new speed set to %s" % (speed_change * 100, self.seconds_per_tick_ccw))
		else:
			self.logger.error("Strange, there was no rotation going on")

	def sweep(self,start,stop,period,sweeps,increment):
		scan = ScanTarget(self, "Scan", start, stop, period, abs(increment), sweeps, 30*60)
		self.target_stack.push(scan)


	def track_wind(self):
		wind_target = WindTarget(self)
		self.target_stack.push(wind_target)

	def track_moon(self):
		moon_target = MoonTarget(self)
		self.target_stack.push(moon_target)

	def pop_target(self):
		self.logger.debug("Popping target stack")
		return self.target_stack.pop()

	def track_sun(self):
		sun_target = SunTarget(self)
		self.target_stack.push(sun_target)

	def get_az_target(self):
		if self.az_target:
			return self.ticks2az(self.az_target)
		else:
			return None

	def ticks2az(self, ticks) -> Degree:
		return Degree(round(self.CCW_BEARING_STOP + ticks / self.ticks_per_degree))

	def az2ticks(self, degrees: Degree):
		degrees_1 = degrees - self.CCW_BEARING_STOP
		ticks = round(self.ticks_per_degree * degrees_1)
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

	def status_update(self):
		self.target_stack.update_ui()

	def el_interrupt(self, last, current):
		pass

	def manual_interrupt(self):
		self.rotate_start_az = self.az
		target = ManualTarget(self)
		self.target_stack.push(target)
		self.az_stop()

	def stop_interrupt(self, _last, _current):

		if not self.p20.bit_read(P20_STOP_AZ_L):
			self.logger.warning("Stop interrupt skipped. timer is cleared")
			return  # Timer is cleared
		if self.p20.bit_read(P20_AZ_TIMER_L) and not self.calibrating and not self.rotating_cw and not self.rotating_ccw:
			self.logger.warning("Stop interrupt skipped. No rotation going on, retriggering=%s, cw=%s, ccw=%s, calibrating=%s" %
			      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating))
			return  # We are not rotating
		self.logger.warning("Azel stop interrupt, retriggering=%s, cw=%s, ccw=%s, calibrating=%s, stop_count=%d" %
		      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating, self.stop_count))
		# time.sleep(1)
		if self.stop_count < 1:
			self.stop_count += 1
			self.az_at_stop = self.az
			self.retrigger_az_timer()
			return # Fake stop?
		# We ran into a mech stop
		self.stop_count=0

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

	def az_interrupt(self, last_code, current_code):
		"""
		This method handles interrupt for azimuth movement.

		:param last_code: The last azimuth code from the reading forks.
		:param current_code: The current azimuth code from the reading forks.
		:return: None

		"""
		# print("Azimuth interrupt; %x %x, %d" % (last_code, current_code, self.stop_count))

		try:
			inc = self.azz2inc[last_code << 2 | current_code]
		except KeyError:
			if self.rotating_cw:
				pass
				# inc = 2
				self.logger.error("Key error rotating cw: index=%s" % bin(last_code << 2 | current_code))
				self._az_track()
				return
			elif self.rotating_ccw:
				pass

				self.logger.error("Key error rotating ccw: index=%s" % bin(last_code << 2 | current_code))
				# inc = -2
				self._az_track()
				return
			else:
				self.logger.error("Key error and no rotation: index=%s" % bin(last_code << 2 | current_code))
				self._az_track()
				return
		self.az += inc

		# self.logger.debug("Ticks: %d, stop_count=%d" % (self.az, self.stop_count))
		if inc:
			self.retrigger_az_timer()
		if self.stop_count and abs(self.az - self.az_at_stop) > 1:
			self.stop_count=0
		# self.logger.debug("Ticks: %d, stop_count=%d"% (self.az, self.stop_count))
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
			self.logger.debug("Azimuth rotation error, diff=%d, ccw=%d, cw=%d" % (diff, self.rotating_ccw, self.rotating_cw))
			self.az_rotation_err_count += 1
			if self.az_rotation_err_count > 20:
				self.logger.error("Azimuth going wrong way, stopping.")
				self.az_stop()
				self.az_stop()
				self.az_stop()
				self.az_rotation_err_count = 0
				self._az_track(self.az_target_degrees)

	def az_track_bearing(self, bearing:Degree) -> None:
		target = AzTarget(self, bearing)
		self.target_stack.push(target)

	def az_track_loc(self, loc:str, auto=False) -> None:
		target = MhTarget(self, loc)
		if auto and target.distance < 100.0:
				self.logger.warning("Distance to %s is too close for auto-tracking" % loc)
				return
		self.target_stack.push(target)

	def az_track_station(self, who:str, auto=False) -> None:
		target = StationTarget(self, who)
		if auto and target.distance < 100.0:
				self.logger.warning("Distance to %s is too close for auto-tracking" % who)
				return
		self.target_stack.push(target)


	def az_track(self, az=None, what=None, classes=None):
		if what is None:
			what="Fixed_"+str(az)
		self.az_target_degrees = az
		target = Target(self, what, az, Degree(0) , 10, 3600)
		if classes:
			target.set_led_classes(classes)
		self.logger.info("az_track %s" % az)
		self.target_stack.push(target)

	def _az_track(self, target:Degree=None):
		if target is not None:
			if self.az2ticks(target) != self.az_target:
				self.az_target = self.az2ticks(target)
				self.logger.info("Tracking azimuth %d degrees = %d ticks" % (target, self.az_target))

		self.start_azimuth_control()

	def start_azimuth_control(self):
		if not self.az_control_active:
			self.az_control_thread = threading.Thread(target=self.az_control_loop, args=(), daemon=True)
			self.az_control_active = True
			self.az_control_thread.start()

	def stop_azimuth_control(self):
		self.az_control_active = False  # This makes the tracking thread quit.

	def az_stop(self):
		self.logger.debug("Stop azimuth rotation")
		self.rotate_stop()
		time.sleep(0.4)  # Allow mechanics to settle
		self.logger.debug("Stopped azimuth rotation at %d ticks"% self.az)
		self.store_az()

	def az_ccw(self):
		self.logger.debug("Rotate anticlockwise")
		self.az_rotation_err_count = 0
		self.p20.bit_write(P20_STOP_AZ_L, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		self.rotate_ccw()
		self.logger.debug("Rotating anticlockwise")

	def nudge_ccw(self, diff):
		self.logger.debug("Nudging anticlockwise")
		self.az_rotation_err_count = 0
		self.p20.bit_write(P20_STOP_AZ_L, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		nudge_time = float((abs(diff)/3) * self.seconds_per_tick_ccw)
		self.rotate_ccw()
		time.sleep(nudge_time)
		self.rotate_stop()
		self.logger.debug("Nudged anticlockwise for %f seconds" % nudge_time)


	def az_cw(self):
		self.logger.debug("Rotate clockwise")
		self.az_rotation_err_count = 0
		self.rotating_cw = True
		self.p20.bit_write(P20_STOP_AZ_L, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		self.rotate_cw()
		self.logger.debug("Rotating clockwise")


	def nudge_cw(self,diff):
		self.logger.debug("Nudging clockwise")
		self.az_rotation_err_count = 0
		self.p20.bit_write(P20_STOP_AZ_L, HIGH)
		time.sleep(0.1)
		self.rotate_start_az = self.az
		nudge_time = float((abs(diff)/3) * self.seconds_per_tick_cw + 0.2)
		self.rotate_cw()
		time.sleep(nudge_time)
		self.rotate_stop()
		self.logger.debug("Nudged clockwise for %f seconds" % nudge_time)

	def rotate_cw(self):
		self.logger.debug("Rotate_cw")
		self.rotating_cw = True
		self.rotating_ccw = False
		self.p20.byte_write(P20_ROTATE_CW, 0)  # Select CW
		time.sleep(0.2)
		self.p20.byte_write(P20_AZ_TIMER_L | P20_ROTATE_CW, 0)  # Start

	def rotate_ccw(self):
		self.logger.debug("Rotate_ccw")
		self.rotating_ccw = True
		self.rotating_cw = False
		self.p20.byte_write(P20_ROTATE_CW, P20_ROTATE_CW)  # Select ccw
		time.sleep(0.2)
		self.p20.byte_write(P20_AZ_TIMER_L | P20_ROTATE_CW, P20_ROTATE_CW)  # Start

	def rotate_stop(self):
		self.logger.debug("Rotate_stop")
		self.p20.byte_write(P20_STOP_AZ_L, P20_ROTATE_CW)
		self.rotating_ccw = False
		self.rotating_cw = False
	def interrupt_dispatch(self, _channel):
		current_sense = self.p21.byte_read(0xff)  # type: int
		# self.logger.debug("Interrupt %s %s" % (sense2str(self.last_sense), sense2str(current_sense)))

		diff = current_sense ^ self.last_sense

		if diff & AZ_MASK:
			# self.logger.debug("Dispatching to az_interrupt")
			if not self.disable_tracking:
				self.az_interrupt(self.last_sense & AZ_MASK, current_sense & AZ_MASK)
		if diff & EL_MASK:
			if not self.disable_tracking:
				self.logger.debug("Dispatching to el_interrupt")
				self.el_interrupt(self.last_sense & EL_MASK, current_sense & EL_MASK)
		if diff & STOP_MASK and (current_sense & STOP_MASK == 0):
			if not self.disable_tracking:
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
		self.p20.bit_write(P20_AZ_TIMER_L, HIGH)
		self.p20.bit_write(P20_AZ_TIMER_L, LOW)
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
		self.rotate_start_az = self.az
		cur.close()

	def store_az(self):
		cur = self.ham_op.db.cursor()
		cur.execute("UPDATE azel_current set az = %s WHERE ID=0", (self.az,))
		cur.close()
		self.ham_op.db.commit()

	def startup(self):
		"""
		Method to start up the az/en controller.

		:return: None
		"""
		self.logger.debug("Restoring at last saved azimuth")
		self.restore_az()
		self.logger.info("Azimuth restored to %d ticks at %d degrees" % (self.az, self.ticks2az(self.az)))
		self.last_sense = self.p21.byte_read(0xff)
		self.az_stop()
		self.logger.debug("Starting interrupt dispatcher")
		GPIO.add_event_detect(self.AZ_INT, GPIO.FALLING, callback=self.interrupt_dispatch)
		self.track_wind()


	def get_azel(self)-> Tuple[Degree, int]:
		return self.ticks2az(self.az), self.el

	def calibrate(self):
		"""
		Calibrates the azimuth.

		The method checks the current azimuth value and calibrates the system accordingly.
		If the current azimuth is less than half of the clockwise mechanical stop value, it calls the calibrate_ccw() method.
		Otherwise, it calls the calibrate_cw() method.

		:return: None
		"""
		if self.az < self.AZ_CW_MECH_STOP / 2:
			self.calibrate_ccw()
		else:
			self.calibrate_cw()


	def calibrate_ccw(self):
		"""
		Calibrates the rotation of the device in a counter-clockwise direction.

		This method sets the `calibrating` flag to True, suspends the target stack, and initializes the `az_target`
		variable to None. It then initiates clockwise rotation, pauses for 1 second, and stops the rotation. Next,
		it sets `calibrating` to True again and starts counter-clockwise rotation. The method logs a warning message
		"Awaiting calibration" and enters a loop until `calibrating` is set to False. Finally, it resumes tracking from
		the target stack.

		:return: None
		"""
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
		"""
		Calibrates the clockwise (cw) rotation of the target.

		The method sets the calibrating flag to True and suspends the target stack. It then starts rotating the target in
		the counterclockwise (ccw) direction until it reaches its maximum position. After a short delay, it stops the
		rotation. It then sets the calibrating flag to True and starts rotating the target in the clockwise (cw) direction.
		It logs a warning message indicating that it is awaiting cw calibration. It waits until the calibrating flag is
		set to False by another process. Finally, it resumes tracking from the target stack.

		:return: None

		"""
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

	def set_az(self, az:Degree):
		"""
		Set the internal representation of the current azimuth angle
		:param az: The azimuth value in degrees to set.
		:return: None
		"""
		self.az = self.az2ticks(az)

	def add_az(self, diff):
		if self.az_target:
			self.az_target += diff
			self._az_track(self.ticks2az(self.az_target) + diff)
		else:
			self._az_track(self.ticks2az(self.az)+diff)


	def stop(self):
		self.az_target = self.az
		self.az_stop()

	def untrack(self):
		self.az_target = None
		self.az_target_degrees = None
		self.az_stop()
		self.logger.info("Stopped tracking at az=%d degrees" % self.ticks2az(self.az))

	@staticmethod
	def GPIO_cleanup():
		GPIO.cleanup()

	def current_az_sector(self)-> Tuple[Degree, Degree]:
		az:Degree = self.get_azel()[0]
		from_az = 0
		to_az = 360
		for sector in self.az_sectors:
			if sector[0] <= az <= sector[1]:
				from_az = sector[0]
				to_az = sector[1]
				break
		return from_az, to_az

	def get_az_sector(self) -> Tuple[Degree, Degree]:
		return self.az_sector

	def update_target_list(self):
		self.target_stack.update_ui(force=True)

	from typing import NoReturn

	def manual(self, what: str) -> NoReturn:
		"""
		Function to handle manual azimuth rotation of the antenna.

		:param what: (str) The manual request. Should be "stop", "ccw", or "cw".
		:return: None
		"""
		if what != "stop":
			self.rotate_start_az = self.az
			current_target=self.target_stack.get_top()
			if type(current_target) is not ManualTarget:
				target = ManualTarget(self)
				self.target_stack.push(target)
			self.target_stack.suspend()
			if what=="ccw":
				self.p20.bit_write(P20_STOP_AZ_L, HIGH)
				time.sleep(0.1)
				self.logger.info("Starting manual CCW rotation")
				self.rotating_manual = True
				self.rotate_ccw()
				self.logger.info("Started manual CCW rotation")
			elif what=="cw":
				self.p20.bit_write(P20_STOP_AZ_L, HIGH)
				time.sleep(0.1)
				self.logger.info("Starting manual CW rotation")
				self.rotating_manual = True
				self.rotate_cw()
				self.logger.info("Started manual CW rotation")
			else:
				self.logger.error("Invalid manual request: %s" % what)
				self.az_stop()
		else:
			self.target_stack.resume()
			if self.rotating_manual:
				self.rotating_manual = False
				self.az_stop()



