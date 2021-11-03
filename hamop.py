from pcf8574 import *

from p27_defs import *
from contest_log import *

import psycopg2.extras
from datetime import datetime
import locator.src.maidenhead as mh
from geo import sphere
import math


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import psycopg2

class HamOp:
    """ Handles all data and functions pertaining to the ham operator and station"""

    def __init__(self, app, db: psycopg2):
        self.app = app
        self.db = db

        try:
            self.p27 = PCF(P27_I2C_ADDRESS, {P27_PA_OFF_L: (0, OUTPUT),
                                                     P27_PA_READY: (1, INPUT),
                                                     P27_PA_ON_L: (2, OUTPUT),
                                                     P27_UNUSED_3: (3, INPUT),
                                                     P27_RX_432_L: (4, OUTPUT),
                                                     P27_TX_432_L: (5, OUTPUT),
                                                     P27_TRX_RX_ACTIVE_L: (6, INPUT),
                                                     P27_TRX_TX_ACTIVE_L: (7, INPUT),
                                                     })
            self.p27.bit_write(P27_PA_OFF_L, HIGH)
            self.p27.bit_write(P27_PA_ON_L, HIGH)
            self.p27.bit_write(P27_RX_432_L, HIGH)
            self.p27.bit_write(P27_TX_432_L, HIGH)

        except OSError:
            self.p27 = None


        self.last_p27_sense = None
        self.pa_running = None
        self.last_status = 0xff
        self.tracking_wind = False
        self.azel = None # Type: "AzElControl"

        pass

    def status_sense(self):
        if not self.p27:
            return
        current_p2_sense = self.p27.byte_read(0xff)

        if current_p2_sense != self.last_p27_sense or self.last_p27_sense is None:
            self.app.client_mgr.status_push(current_p2_sense)

        self.last_p27_sense = current_p2_sense

    def get_mydata(self):
        cur = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        ts = datetime.now().isoformat()[:10]
        cur.execute("""SELECT * FROM config_str 
                        WHERE (time_start IS NULL OR time_start <= %s ) AND 
                               (time_stop IS NULL OR time_stop >= %s) AND
                               (band IS NULL OR band = %s) 
                               ORDER BY key""",
                    (ts, ts, self.app.client_mgr.current_band)
                    )
        rows = cur.fetchall()

        msg = {}
        for row in rows:
            k = row["key"]
            v = row["value"]
            msg[k] = v
        return msg

    def get_status(self):
        if not self.p27:
            return
        current_p2_sense = self.p27.byte_read(0xff)
        return current_p2_sense

    def my_status(self):
        if self.p27:
            pa_rdy = self.p27.bit_read(P27_PA_READY)
            trx_tx = not self.p27.bit_read(P27_TRX_TX_ACTIVE_L)
            trx_rx = not self.p27.bit_read(P27_TRX_RX_ACTIVE_L)
            pa_active = not self.p27.bit_read(P27_PA_ON_L)
            rx70 = not self.p27.bit_read(P27_RX_432_L)
            tx70 = not self.p27.bit_read(P27_TX_432_L)
            s = ""
            s += "Transceiver is receiving<br/>" if trx_rx else "Transceiver is not receiving.<br/>"
            s += "Transceiver is transmitting<br/>" if trx_tx else "Transceiver is not transmitting.<br/>"
            s += "Power accelerator ready<br/>" if pa_rdy else "Power accelerator is not ready<br/>"
            s += "Power accelerator active<br/>" if pa_active else "Power accelerator is inactive.<br/>"
            s += "RX 70cm active<br/>" if rx70 else "RX 70cm is inactive.<br/>"
            s += "TX 70cm active<br/>" if tx70 else "TX 70cm is inactive.<br/>"
        else:
            s = "Core station info is not available<br/>"

        s += "Antenna is tracking the current wind<br/>" if self.app.azel.tracking_wind else "Antenna is not tracking the current wind.<br/>"
        s += "Antenna is targeted at azimuth %d degrees<br/>" % self.app.azel.get_az_target() if self.app.azel.get_az_target() else "Antenna has no azimuth target<br/>"

        return s

    def fetch_my_current_data(self, band="144"):
        cur = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        ts = datetime.now().isoformat()[:10]
        cur.execute("""SELECT * FROM config_str 
                                    WHERE (time_start IS NULL OR time_start <= %s ) AND 
                                           (time_stop IS NULL OR time_stop >= %s) AND
                                           (band IS NULL OR band = %s) 
                                           ORDER BY key""",
                    (ts, ts, band)
                    )
        rows = cur.fetchall()
        return rows


    def get_log_rows(self):
        cur = self.db.cursor()
        cur.execute("""SELECT qsoid, date, time, callsign, tx, rx, locator, distance, square, points, complete, mode, accumulated_sqn, band 
                                FROM nac_log_new  ORDER BY date, time""")
        rows = cur.fetchall()
        return rows

    def distance_to(self, other_loc, qso_date=None, qso_time=None):
        # print()
        mn, ms, mw, me, mlat, mlon = mh.to_rect(self.my_qth()[:6])

        n, s, w, e, lat, lon = mh.to_rect(other_loc)

        bearing = sphere.bearing((mlon, mlat), (lon, lat))
        distance = sphere.distance((mlon, mlat), (lon, lat)) / 1000.0 * 0.9989265959409077
        points = math.ceil(distance)

        if qso_date and qso_time:
            cur = self.db.cursor()
            cur.execute("SELECT DISTINCT substr(locator, 1, 4) from nac_log_new where date=%s and time < %s",
                        (qso_date, qso_time))
            rows = cur.fetchall()
            squares = {x[0] for x in rows}
            # print(squares)
            square_count = len(squares)

            if other_loc[:4] not in squares:
                squares.add(other_loc[:4])
                square_count += 1
                if "1700" <= qso_time < "2200":
                    points += 500
        else:
            return bearing, distance

        # print(distance);
        return bearing, distance, points, square_count

    def do_commit_qso(self, qso):
        cur = self.db.cursor()
        if "square" not in qso or not qso["square"]:
            qso["square"] = None
        if "band" not in qso or not qso["band"]:
            qso["band"] = self.app.client_mgr.current_band
        if "transmit_mode" in qso and qso["transmit_mode"]:
            transmit_mode = qso["transmit_mode"]
        else:
            if len(qso["tx"]) == 3:
                transmit_mode = "CW"
            else:
                if "-" in qso["band"]:
                    transmit_mode = qso["band"].split('-')[1]
                else:
                    transmit_mode = "SSB"
        if "mode" in qso and qso["mode"]:
            propagation_mode = qso["mode"]
        else:
            propagation_mode = "T"

            if qso["tx"].upper().endswith('A') or qso["rx"].upper().endswith('A'):
                propagation_mode = "A"

            if "MS" in transmit_mode.upper() and float(qso["distance"]) > 500.0:
                propagation_mode = "MS"

            if float(qso["distance"]) > 3000:
                propagation_mode = "EME"
        accumulated_square = None
        if "locator" in qso and qso["locator"]:
            cur.execute(
                """SELECT DISTINCT upper(substr(locator, 1, 4)) FROM nac_log_new WHERE split_part(split_part(band,'-',1), '.',1) = %s""",
                (qso["band"].split('-')[0],))

            rows = cur.fetchall()

            for row in rows:
                if row[0] == qso["locator"][:4].upper():
                    break
            else:
                accumulated_square = str(len(rows) + 1)
        else:
            qso["locator"] = None

        band_or_fq = qso["band"]
        if "frequency" in qso and qso["frequency"]:
            band_or_fq = qso["frequency"]

        cur.execute("""INSERT INTO nac_log_new (date, time, callsign, tx , rx , locator, distance, square, points, complete, band, accumulated_sqn, transmit_mode, mode) 
                      values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,%s) RETURNING qsoid""",
                    (qso["date"], qso["time"], qso["callsign"], qso["tx"], qso["rx"], qso["locator"],
                     qso["distance"], qso["square"], qso["points"], qso["complete"], band_or_fq, accumulated_square,
                     transmit_mode, propagation_mode))
        new_qso_id = cur.fetchone()[0]
        self.db.commit()
        cur.close()
        return new_qso_id


    def my_qth(self):
        rows = self.fetch_my_current_data()
        my_data = {x["key"]: x["value"] for x in rows}
        myqth = my_data["my_locator"]
        return myqth

    def my_pa_on(self):
        if not self.p27:
            return "Core station out of control"

        pa_rdy = self.p27.bit_read(P27_PA_READY)
        if not pa_rdy:
            print("Igniting booster")
            self.p27.bit_write(P27_PA_ON_L, LOW)
            time.sleep(0.1)
            self.p2.bit_write(P27_PA_ON_L, HIGH)
            return "Ignition sequence started"
        else:
            return "Power booster is ready<br/>"

    def my_pa_off(self):
        if not self.p27:
            return "Core station out of control"
        print("Shutting down PA")
        self.p27.bit_write(P27_PA_ON_L, HIGH)
        self.p27.bit_write(P27_PA_OFF_L, LOW)
        time.sleep(0.1)
        self.p27.bit_write(P27_PA_OFF_L, HIGH)
        return "PA is shut down"

    def my_qro_on(self):
        if not self.p27:
            return "Core station out of control"
        pa_rdy = self.p27.bit_read(P27_PA_READY)
        if not pa_rdy:
            return "Power booster is not ready<br/>"
        self.p27.bit_write(P27_PA_ON_L, LOW)
        return "Power booster enabled"

    def my_qro_off(self):
        if not self.p27:
            return "Core station out of control"
        self.p27.bit_write(P27_PA_ON_L, HIGH)
        return "Power booster disabled"

    def my_rx70_on(self):
        if not self.p27:
            return "Core station out of control"
        self.p27.bit_write(P27_RX_432_L, LOW)
        return "70cm rx enabled"

    def my_rx70_off(self):
        if not self.p27:
            return "Core station out of control"
        self.p27.bit_write(P27_RX_432_L, HIGH)
        return "70cm rx disabled"

    def my_tx70_on(self):
        if not self.p27:
            return "Core station out of control"
        self.p27.bit_write(P27_TX_432_L, LOW)
        return "70cm tx enabled"

    def my_tx70_off(self):
        if not self.p27:
            return "Core station out of control"
        self.p27.bit_write(P27_TX_432_L, HIGH)
        return "70cm tx disabled"

    def my_wsjtx_upload(self, request):
        ret = {"added": 0, "adjusted": 0}
        cur = self.db.cursor()
        for k, v in request.files.items():
            file_data = v.read().decode("utf-8")
            print(file_data)
            for line in file_data.splitlines():
                startdate, starttime, enddate, endtime, callsign, locator, frequency, transmit_mode, trprt, rrprt, power, comment, dxname, propagation = line.split(
                    ',')
                starttime = starttime.replace(':', '')[:4]
                _endtime = endtime.replace(':', '')[:4]
                if propagation == "TR":
                    propagation = "T"
                callsign = callsign.upper()
                locator = locator.upper()
                q = """SELECT qsoid, date, time, tx, rx, locator, mode, transmit_mode from nac_log_new where date=%s and
                     abs(date_part('hour',time::time-%s::time)*60+date_part('minute',time::time-%s::time)) < 10
                     and callsign = %s"""
                cur.execute(q, (startdate, starttime, starttime, callsign))
                lines = cur.fetchall()
                if len(lines) == 1:
                    # print("Found QSO: %s" % lines)
                    qso = lines[0]
                    qso_date = qso[1]
                    qso_time = qso[2]
                    adjustments = 0
                    if locator not in qso[5]:
                        print("Bad locator %s, should be %s" % (qso[5], locator))
                        bearing, distance, points, square_no = self.distance_to(locator, qso_date, qso_time)
                        cur.execute(
                            "UPDATE nac_log_new set locator = %s, distance = %s, square = %s, points = %s where qsoid=%s",
                            (locator, str(int(distance * 100) / 100.0), square_no, points, qso[0]))
                        adjustments += 1
                    if qso[6] != propagation and propagation:
                        print("Bad propagation mode %s, should be %s" % (qso[6], propagation))
                        cur.execute("UPDATE nac_log_new set mode = %s where qsoid=%s", (propagation, qso[0]))
                        adjustments += 1
                    if qso[7] != transmit_mode:
                        print("Bad transmit mode %s, should be %s" % (qso[7], transmit_mode))
                        cur.execute("UPDATE nac_log_new set transmit_mode = %s where qsoid=%s", (transmit_mode, qso[0]))
                        adjustments += 1
                    if qso[3] != trprt:
                        print("Bad sent report %s, should be %s" % (qso[3], trprt))
                        cur.execute("UPDATE nac_log_new set tx = %s where qsoid=%s", (trprt, qso[0]))
                        adjustments += 1
                    if qso[4] != rrprt:
                        print("Bad received report %s, should be %s" % (qso[4], rrprt))
                        cur.execute("UPDATE nac_log_new set rx = %s where qsoid=%s", (rrprt, qso[0]))
                        adjustments += 1
                    if adjustments:
                        ret["adjusted"] += 1
                elif len(lines) > 1:
                    print("Multiple qsos found; %s" % lines)
                    pass
                else:
                    q = """SELECT qsoid, date, time, tx, rx, locator, abs(date_part('hour',time::time-%s::time)*60+date_part('minute',time::time-%s::time)) from nac_log_new where date=%s
                        and callsign = %s"""
                    cur.execute(q, (starttime, starttime, startdate, callsign))
                    lines = cur.fetchall()
                    print("Missing QSO: %s" % line)
                    if lines:
                        print("Found:", lines)
                    else:
                        bearing, distance, points, square_no = self.distance_to(locator, startdate, starttime)
                        qso = {
                            "date": startdate,
                            "time": starttime,
                            "callsign": callsign,
                            "tx": trprt,
                            "rx": rrprt,
                            "locator": locator,
                            "distance": str(int(distance * 100) / 100.0),
                            "square": square_no,
                            "points": points,
                            "complete": True,
                            "band": "%d-%s" % (int(float(frequency)), transmit_mode),
                            "mode": propagation,
                            "transmit_mode": transmit_mode,
                            "frequency": frequency,
                        }
                        self.do_commit_qso(qso)
                        ret["added"] += 1
            break
        if ret["adjusted"]:
            self.db.commit()
        return "QSQ:s added: %d, adjusted: %s" % (ret["added"], ret["adjusted"])



    def make_log(self, json):
        band = json.get("band", None)
        log_remarks = json.get("log_remarks", None)
        if band:
            contest_log = produce_contest_log(band, log_remarks=log_remarks)
            json["contest_log"] = contest_log
            self.app.client_mgr.emit_log(json)

    def toggle_qro(self):
        if self.p27:
            pa_rdy = self.p27.bit_read(P27_PA_READY)
            if pa_rdy:
                pa_on = not self.p27.bit_read(P27_PA_ON_L)
                if pa_on:
                    self.p27.bit_write(P27_PA_ON_L, HIGH)
                else:
                    self.p27.bit_write(P27_PA_ON_L, LOW)
            self.app.client_mgr.status_update(force=True)


    def toggle_pa(self):
        if self.p27:

            if self.pa_running is None:
                pa_rdy = self.p27.bit_read("PA_READY")
                self.pa_running = pa_rdy

            rx_on = not self.p27.bit_read("TRX_RX_ACTIVE_L")
            tx_on = not self.p27.bit_read("TRX_TX_ACTIVE_L")

            if self.pa_running:
                self.p27.bit_write("PA_OFF_L", LOW)
                time.sleep(0.1)
                self.p27.bit_write("PA_OFF_L", HIGH)
                self.pa_running = False
            else:
                if rx_on or tx_on:
                    self.p27.bit_write("PA_ON_L", LOW)
                    time.sleep(0.1)
                    self.p27.bit_write("PA_ON_L", HIGH)
                    self.pa_running = True

            self.app.client_mgr.status_update(force=True)

    def track_az(self, what):
        try:
            mn, ms, mw, me, mlat, mlon = mh.to_rect(self.my_qth())
            n, s, w, e, lat, lon = mh.to_rect(what)
            bearing = sphere.bearing((mlon, mlat), (lon, lat))
            print("Calculated bearing from %s to %s to be %f" % (self.my_qth(), what, bearing))
            self.app.azel.az_track(int(bearing))
            self.app.client_mgr.add_mh_on_map(what)
        except (TypeError, ValueError):
            pass

        q = """SELECT qsoid, locator from nac_log_new where callsign = %s order by date desc"""

        cur = self.db.cursor()
        cur.execute(q, (what,))
        lines = cur.fetchall()
        if lines:
            loc = lines[0][1]
            bearing, _distance = self.distance_to(loc)
            print("Tracking Az %d to %s at %s" % (int(bearing), what, loc))
            self.app.azel.az_track(int(bearing))
