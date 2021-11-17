import RPi.GPIO as GPIO
from pcf8574 import *
import locator.src.maidenhead as mh
import threading

import requests
from p21_defs import *
from p20_defs import *


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


class AzElControl:

	def __init__(self, app, socket_io, hysteresis: int = 1):
		self.app = app
		self.socket_io = socket_io
		self.az_hysteresis = hysteresis

		self.p21 = PCF(P21_I2C_ADDRESS,
		              {P21_AZ_IND_A: (0, INPUT),
		               P21_AZ_IND_B: (1, INPUT),
		               P21_EL_PULSE: (2, INPUT),
		               P21_AZ_STOP: (3, INPUT),
		               P21_MAN_CW: (4, INPUT),
		               P21_MAN_CCW: (5, INPUT),
		               P21_MAN_UP: (6, INPUT),
		               P21_MAN_DN: (7, INPUT),
		               })
		self.p20 = PCF(P20_I2C_ADDRESS,
		              {P20_AZ_TIMER: (0, OUTPUT),
		               P20_STOP_AZ: (1, OUTPUT),
		               P20_ROTATE_CW: (2, OUTPUT),
		               P20_RUN_EL: (3, OUTPUT),
		               P20_EL_UP: (4, OUTPUT),
		               P20_CW_KEY: (5, OUTPUT),
		               P20_UNUSED_6: (6, INPUT),
		               P20_UNUSED_7: (7, INPUT),
		               })

		# GPIO Interrupt pin
		self.AZ_INT = 17

		self.AZ_CCW_MECH_STOP: int = 0
		self.AZ_CW_MECH_STOP: int = 734

		self.CCW_BEARING_STOP: int = 273  # 278   273
		self.CW_BEARING_STOP: int = 278  # 283   278

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
		self.az_target = None
		self.el = 0
		self.inc = 0
		self.inc = 0
		self.az = 0
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
				print(deg, self.az, self.az2ticks(deg))

			self.az = 270
			print()

			for deg in ranges:
				print(deg, self.az, self.az2ticks(deg))

			self.az = 0

	def untrack_wind(self):
		self.tracking_wind = False

	def track_wind(self, value=None):
		if value is None:
			value = True
		self.tracking_wind = value

		if not self.wind_thread:
			self.wind_thread = threading.Thread(target=self.wind_thread_function, args=(self,), daemon=True)
			self.wind_thread.start()
		else:
			abortable_sleep.abort()

	def get_az_target(self):
		if self.az_target:
			return self.ticks2az(self.az_target)
		else:
			return None


	def wind_thread_function(self, azel):
		while True:
			if azel.tracking_wind:
				mn, ms, mw, me, my_lat, my_lon = mh.to_rect(self.app.ham_op.my_qth())
				ret = requests.get(
					url="https://api.met.no/weatherapi/nowcast/2.0/complete?altitude=125&lat=%f&lon=%f" % (my_lat, my_lon),
					headers={"User-Agent": "bernerus.se info@bernerus.se"})
				response = ret.json()

				details = response["properties"]["timeseries"][0]["data"]["instant"]["details"]
				wfd = details["wind_from_direction"]
				wtd = wfd + 180.0
				wtd = wtd + 360.0 if wtd < 0 else wtd
				wtd = wtd - 360 if wtd > 360 else wtd
				print("Tracking current wind direction to %d" % int(wtd))
				azel.az_track(int(wtd))
			abortable_sleep(600)

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
		if ticks < self.AZ_CCW_MECH_STOP:
			ticks += self.ticks_per_rev
		if ticks >= self.AZ_CW_MECH_STOP:
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

	def update_status(self, force=False):
		if self.tracking_wind != self.last_tracking_wind or self.last_tracking_wind is None or force:
			self.app.client_mgr.push_wind_led(self.tracking_wind)
		self.last_tracking_wind = self.tracking_wind

	def el_interrupt(self, last, current):
		pass

	def manual_interrupt(self, _last, _current):
		self.az_target = None
		self.untrack_wind()
		self.az_stop()

	def stop_interrupt(self, _last, _current):

		if not self.p20.bit_read(P20_STOP_AZ):
			print("Stop interrupt skipped. timer is cleared")
			return  # Timed is cleared
		if self.p20.bit_read(P20_AZ_TIMER) and not self.calibrating and not self.rotating_cw and not self.rotating_ccw:
			print("Stop interrupt skipped. No rotation going on, retrig=%s, cw=%s, ccw=%s, calibrating=%s" %
			      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating))
			return  # We are not rotating
		print("Azel interrupt, retrig=%s, cw=%s, ccw=%s, calibrating=%s" %
		      (self.retriggering, self.rotating_cw, self.rotating_ccw, self.calibrating))
		# time.sleep(1)
		# We ran into a mech stop

		if not self.p20.bit_read(P20_ROTATE_CW):
			# print("Mechanical stop clockwise")
			self.az = self.AZ_CW_MECH_STOP
		else:
			# print("Mechanical stop anticlockwise")
			self.az = self.AZ_CCW_MECH_STOP

		if self.current_az_sector() != self.az_sector:
			self.az_sector = self.current_az_sector()
			self.app.client_mgr.update_map_center()
		print("Az set to %d ticks" % self.az)
		self.app.client_mgr.send_azel()
		if self.calibrating:
			self.calibrating = False
			print("Calibration done")
			self.az_stop()
		else:
			self.az_track()

	def az_interrupt(self, last_az, current_az):

		# print("Azint; %x %x" % (last_az, current_az))
		try:
			inc = self.azz2inc[last_az << 2 | current_az]
		except KeyError:
			print("Key error: index=%s" % bin(last_az << 2 | current_az))
			self.az_track()
			return
		self.az += inc
		if inc:
			self.retrigger_az_timer()

		#            print("Ticks:", self.az)
		self.app.client_mgr.send_azel()
		if self.current_az_sector() != self.az_sector:
			self.az_sector = self.current_az_sector()
			#print("Sector=",self.az_sector)
			self.app.client_mgr.update_map_center()
		self.az_track()

	def az_track(self, target=None):
		if target is not None:
			if self.az2ticks(target) != self.az_target:
				self.az_target = self.az2ticks(target)
				print("Tracking azimuth %d degrees = %d ticks" % (target, self.az_target))
		if self.az_target is not None:
			diff = self.az - self.az_target
			# print("Diff = ", diff)
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
		# print("Stop azimuth rotation")
		self.rotating_ccw = False
		self.rotating_cw = False
		# self.p20.byte_write(0xff, ~self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, LOW)
		self.p20.bit_write(P20_ROTATE_CW, HIGH)
		# print("Stopped azimuth rotation")
		time.sleep(0.4)  # Allow mechanics to settle
		self.store_az()

	def az_ccw(self):
		# print("Rotate anticlockwise")
		self.rotating_ccw = True
		self.rotating_cw = False
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		# self.p20.byte_write(0xff, ~self.AZ_TIMER)
		self.p20.bit_write(P20_ROTATE_CW, HIGH)
		self.p20.bit_write(P20_AZ_TIMER, LOW)
		print("Rotating anticlockwise")

	def az_cw(self):
		# print("Rotate clockwise")
		self.rotating_cw = True
		self.rotating_ccw = False
		# self.p20.byte_write(0xff, self.STOP_AZ)
		self.p20.bit_write(P20_STOP_AZ, HIGH)
		time.sleep(0.1)
		self.p20.bit_write(P20_ROTATE_CW, LOW)
		self.p20.bit_write(P20_AZ_TIMER, LOW)
		# self.p20.byte_write(0xFF, ~(self.AZ_TIMER | self.ROTATE_CW))
		print("Rotating clockwise")

	def interrupt_dispatch(self, _channel):

		current_sense = self.p21.byte_read(0xff)
		# print("Interrupt %s %s" % (self.sense2str(self.last_sense), self.sense2str(current_sense)))

		diff = current_sense ^ self.last_sense

		az_mask = 0x03
		el_mask = 0x04
		stop_mask = 0x08
		manual_mask = 0xf0

		if diff & az_mask:
			# print("Dispatching to az_interrupt")
			self.az_interrupt(self.last_sense & az_mask, current_sense & az_mask)
		if diff & el_mask:
			# print("Dispatching to el_interrupt")
			self.el_interrupt(self.last_sense & el_mask, current_sense & el_mask)
		if diff & stop_mask and (current_sense & stop_mask == 0):
			print("Dispatching to stop_interrupt, diff=%x, current_sense=%x, last_sense=%x" %
			      (diff, current_sense, self.last_sense))
			self.stop_interrupt(self.last_sense & stop_mask, current_sense & stop_mask)

		if diff & manual_mask and (current_sense & manual_mask != manual_mask):
			print("Manual intervention detected")
			self.manual_interrupt(self.last_sense & manual_mask, current_sense & manual_mask)

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

		# print("Restoring current azimuth")
		self.restore_az()
		# print("Az restored to %d" % self.az)
		self.az_stop()
		# print("Starting interrupt dispatcher")
		GPIO.add_event_detect(self.AZ_INT, GPIO.FALLING, callback=self.interrupt_dispatch)

		self.tracking_wind = True

	def get_azel(self):
		return self.ticks2az(self.az), self.el

	def calibrate(self):
		self.calibrating = True
		tw = self.tracking_wind
		self.untrack_wind()
		self.az_target = None
		self.az_cw()
		time.sleep(1)
		self.az_stop()
		self.calibrating = True
		self.az_ccw()
		print("Awaiting calibration")
		while self.calibrating:
			self.socket_io.sleep(1)
		self.track_wind(tw)

	def set_az(self, az):
		self.az = self.az2ticks(int(az))

	def stop(self):
		self.az_target = self.az
		self.untrack_wind()
		self.az_stop()

	def untrack(self):
		self.untrack_wind()
		self.az_target = None
		self.az_stop()
		print("Stopped tracking at az=%d degrees" % self.ticks2az(self.az))

	def GPIO_cleanup(self):
		GPIO.cleanup()

	def current_az_sector(self):
		az = self.get_azel()[0]
		if az >= 360:
			az -= 360
		from_az = 0
		to_az = 360
		for oct in self.az_sectors:
			if az >= oct[0] and az <= oct[1]:
				from_az = oct[0]
				to_az = oct[1]
				break
		return from_az, to_az

	def get_az_sector(self):
		return self.az_sector