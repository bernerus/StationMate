from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import MyApp

import util
from pcf8574 import *

from p27_defs import *
from p26_defs import *
from contest_log import *

import psycopg2.extras
from datetime import datetime
import locator.src.maidenhead as mh
import math
import adif_io


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import psycopg2


def commit_qso(request):
    ret = {"added": 0, "adjusted": 0}


class HamOp:
    """ Handles all data and functions pertaining to the ham operator and station"""
    def try_init_p27(self):
        if not self.p27:
            try:
                self.p27 = PCF(self.logger, P27_I2C_ADDRESS, {P27_PA_OFF_L: (0, OUTPUT),
                                                              P27_UNUSED_1: (1, INPUT),
                                                              P27_PA_ON_L: (2, OUTPUT),
                                                              P27_UNUSED_3: (3, INPUT),
                                                              P27_RX_432_L: (4, OUTPUT),
                                                              P27_TX_432_L: (5, OUTPUT),
                                                              P27_UNUSED_6: (6, INPUT),
                                                              P27_UNUSED_7: (7, INPUT),
                                                              })
                self.p27.bit_write(P27_PA_OFF_L, HIGH)
                # self.p27.bit_write(P27_PA_ON_L, HIGH)
                self.p27.bit_write(P27_RX_432_L, HIGH)
                self.p27.bit_write(P27_TX_432_L, HIGH)
                self.logger.info("Found I2C port %x" % P27_I2C_ADDRESS)

            except OSError:
                self.logger.error("I2C port %x not found" % P27_I2C_ADDRESS)
                self.p27 = None
                self.disable_core_controls()
        return self.p27

    def try_init_p26(self):
        if not self.p26:
            try:
                self.p26 = PCF(self.logger, P26_I2C_ADDRESS, {P26_PA_PWR_ON_L: (0, INPUT),
                                                 P26_PA_READY: (1, INPUT),
                                                 P26_PA_QRO_ACTIVE: (2, OUTPUT),
                                                 P26_XRX_432_L: (3, INPUT),
                                                 P26_RX_432_L: (4, OUTPUT),
                                                 P26_TX_432_L: (5, OUTPUT),
                                                 P26_TRX_RX_ACTIVE_L: (6, INPUT),
                                                 P26_TRX_TX_ACTIVE_L: (7, INPUT),
                                                 })
                self.p26.bit_read(P26_PA_READY)
                self.logger.info("Found I2C port %x" % P26_I2C_ADDRESS)

            except OSError:
                self.logger.error("I2C port %x not found" % P26_I2C_ADDRESS)
                self.p26 = None
                self.disable_core_controls()
        return self.p26


    def __init__(self, app:'MyApp', logger, db: psycopg2):
        self.app = app
        self.logger = logger
        self.db = db
        self.core_controls = True
        self.p27 = None
        self.p26 = None

        self.try_init_p27()
        self.try_init_p26()

        self.last_p26_sense = None
        self.pa_running = None
        self.last_status = 0xff

        pass
    def disable_core_controls(self):
        self.core_controls=False

    def enable_core_controls(self):
        self.core_controls = True

    def p26_byte_read(self, xx):
        try:
            return self.p26.byte_read(xx)
        except IOError:
            #self.p26 = None
            #self.try_init_p26()
            return self.p26.byte_read(xx)

    def p27_byte_read(self, xx):
        try:
            return self.p27.byte_read(xx)
        except IOError:
            #self.p27 = None
           # self.p27 = self.try_init_p27()
            if not self.p27:
                return
            return self.p27.byte_read(xx)

    def p26_bit_read(self, xx):
        try:
            return self.p26.bit_read(xx)
        except IOError:
            #self.p26 = None
            #self.p26 = self.try_init_p26()
            return self.p26.bit_read(xx)

    def p27_bit_read(self, xx):
        try:
            return self.p27.bit_read(xx)
        except IOError:
            #self.p27 = None
            #self.try_init_p27()
            if not self.p27:
                return
            return self.p27.bit_read(xx)

    def status_sense(self):
        #self.try_init_p26()
        if not self.p26:
            return
        current_p26_sense = self.p26_byte_read(0xff)

        if current_p26_sense != self.last_p26_sense or self.last_p26_sense is None:
            self.app.client_mgr.status_push(current_p26_sense)

        self.last_p26_sense = current_p26_sense

    def get_mydata(self, band="144"):
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

        msg = {x["key"]: x["value"] for x in rows}
        return msg

    def get_status(self):
        #self.try_init_p26()
        #self.try_init_p27()
        if not self.p26:
            return
        current_p26_sense = self.p26_byte_read(0xff)
        return current_p26_sense

    def my_status(self):
        #self.try_init_p26()
        #self.try_init_p27()
        if self.p27 and self.p26:
            pa_rdy = self.p26_bit_read(P26_PA_READY)
            pa_pwr_on = not self.p26_bit_read(P26_PA_PWR_ON_L)
            trx_tx = not self.p26_bit_read(P26_TRX_TX_ACTIVE_L)
            trx_rx = not self.p26_bit_read(P26_TRX_RX_ACTIVE_L)
            pa_active = not self.p26_bit_read(P26_PA_QRO_ACTIVE)
            rx70 = not self.p26_bit_read(P26_RX_432_L)
            tx70 = not self.p26_bit_read(P26_TX_432_L)
            s = ""
            s += "Transceiver is receiving<br/>" if trx_rx else "Transceiver is not receiving.<br/>"
            s += "Transceiver is transmitting<br/>" if trx_tx else "Transceiver is not transmitting.<br/>"
            s += "Power accelerator on<br/>" if pa_pwr_on else "Power accelerator off<br/>"
            s += "Power accelerator ready<br/>" if pa_rdy else "Power accelerator is not ready<br/>"
            s += "Power accelerator active<br/>" if pa_active else "Power accelerator is inactive.<br/>"
            s += "RX 70cm active<br/>" if rx70 else "RX 70cm is inactive.<br/>"
            s += "TX 70cm active<br/>" if tx70 else "TX 70cm is inactive.<br/>"
        else:
            s = "Core station info is not available<br/>"


        return s

    def fetch_my_current_data(self, band="144"):
        return self.fetch_config_data(type="str", band=band)

        #cur = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # ts = datetime.now().isoformat()[:10]
        # cur.execute("""SELECT * FROM config_str
        #                             WHERE (time_start IS NULL OR time_start <= %s ) AND
        #                                    (time_stop IS NULL OR time_stop >= %s) AND
        #                                    (band IS NULL OR band = %s)
        #                                    ORDER BY key""",
        #             (ts, ts, band)
        #             )
        # rows = cur.fetchall()
        # return rows

    def fetch_config_value(self, type, key, default=None):
        try:
            return {x["key"]: x["value"] for x in self.fetch_config_data(type, key)}[key]
        except KeyError:
            return default

    def fetch_config_data(self, type, key=None, band=None, at_time=None):

        valid_types = ["int", "float", "str"]

        if type not in valid_types:
            raise ValueError("Invalid type: %s for fetching config data, must be one of %s " % (type, valid_types))

        if band and type is not "str":
            raise ValueError("Fetching config data: band selector is only supported fir str type")

        cur = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if at_time is None:
            at_time = datetime.now().isoformat()
        s = "SELECT "
        s += "*" if key is None else "key, value"
        s += " FROM config_%s WHERE (" % type
        s += " (time_start IS NULL OR time_start <= %s) AND (time_stop IS NULL OR time_stop >= %s )"
        s +=  "AND key = %s" if key is not None else " "
        s += " AND (band IS NULL OR band = %s)" if band is not None else " "
        s += ") ORDER BY key"

        args = []
        args.append(at_time)
        args.append(at_time)
        if key is not None: args.append(key)
        if band is not None: args.append(band)
        # print(s, args)
        cur.execute(s, args)
        rows = cur.fetchall()
        return rows


    def set_config_data(self, type, key, value, from_time=None, to_time=None):
        if from_time is None:
            from_time = datetime.now().isoformat()
        valid_types = ["int", "float", "str"]
        if type not in valid_types:
            raise ValueError("Invalid type: %s for setting config data, must be one of %s " % (type, valid_types))

        cur = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Start a transaction
            cur.execute('BEGIN;')

            # Expire all active entries with the same key
            cur.execute("""
                    UPDATE config_%s """ % type + """
                    SET time_stop = %s
                    WHERE key = %s AND (time_stop IS NULL OR time_stop > %s);
                """, (from_time, key, from_time))

            # Insert the new entry with from_time as the time_start and NULL as the time_stop
            cur.execute("""
                    INSERT INTO config_%s""" % type + """ (key, value, time_start, time_stop) 
                    VALUES (%s, %s, %s, NULL);
                """, (key, value, from_time))

            # commit the transaction after all updates
            self.db.commit()
        except Exception as e:
            print("Error:", e)
            self.db.rollback()  # Rollback on exception






    def get_log_rows(self, since: datetime=None, until:datetime=None):

        t_date_start="1900-01-01T00:00:00"
        t_date_stop = "9999-12-31T23:59:59"
        if since is not None:
            t_date_start = since.isoformat()
        if until is not None:
            t_date_stop = until.isoformat()

        # self.logger.debug("Log rows start %s"% t_date_start)
         #self.logger.debug("Log rows end %s"% t_date_stop)

        args = (
            t_date_start[:10], t_date_stop[:10], t_date_start[11:16].replace(":", ""), t_date_stop[11:16].replace(":", ""))
        # self.logger.info("Args =  %s" % str(args))
        cur = self.db.cursor()
        q = """SELECT qsoid, date, time, callsign, tx, rx, locator, distance, square, points, complete, propmode, accumulated_sqn, band, augmented_locator
               FROM nac_log_new WHERE date >= %s and date <= %s and ((time >= %s and time <= %s) or time is null) ORDER BY date, time"""
        cur.execute(q , args)

        rows = cur.fetchall()
        return rows

    def distance_to(self, other_loc, qso_date=None, qso_time=None):
        """
        Calculates the bearing and distance to another location.

        :param other_loc: The coordinates of the other location.
        :param qso_date: The date of the QSO (optional).
        :param qso_time: The time of the QSO (optional).
        :return: A tuple containing the bearing and distance to the other location. If qso_date and qso_time
                 are provided, it also returns the points and square_count.
        """
        bearing, distance = mh.distance_between(self.my_qth(), other_loc)
        points = math.ceil(distance)

        if qso_date and qso_time:
            cur = self.db.cursor()
            cur.execute("SELECT DISTINCT substr(locator, 1, 4) as square from nac_log_new where date=%s and time < %s",
                        (qso_date, qso_time))
            rows = cur.fetchall()
            squares = {x[0] for x in rows}
            square_count = len(squares)

            if other_loc[:4] not in squares:
                squares.add(other_loc[:4])
                square_count += 1
                if "1700" <= qso_time < "2200":
                    points += 500
        else:
            return bearing, distance

        return bearing, distance, points, square_count

    def do_delete_qso(self, qso):
        self.logger.warning("Deleting qso with id=%s" % qso["id"])
        cur = self.db.cursor()
        cur.execute("""DELETE FROM nac_log_new WHERE qsoid = %s""", (int(qso["id"]),))
        self.db.commit()
        # self.app.client_mgr.send_reload()

    def find_augmented_locator(self, callsign:str, given_locator:str) ->Union[str, None]:
        """
        :param callsign: The callsign of the person for whom to find the augmented locator.
        :type callsign: str
        :param given_locator: The given locator to filter the search results. Optional.
        :type given_locator: str
        :return: The augmented locator of the person if found, else None.
        :rtype: str
        """
        if not callsign:
            return None
        cur = self.db.cursor()

        if not given_locator:
            cur.execute("""SELECT upper(locator) FROM callbook WHERE callsign=%s order by char_length(locator) DESC""",
                        (callsign.upper(),))
        else:
            short_given_loc=given_locator[0:4]
            cur.execute("""SELECT upper(locator) FROM callbook WHERE callsign=%s and substr(locator,1,4) = %s order by last_change DESC""",
                    (callsign.upper(), short_given_loc.upper()))
        rows = cur.fetchall()
        if not rows:
            return None
        return rows[0][0]


    def do_commit_qso(self, qso):
        cur = self.db.cursor()
        if "square" not in qso or not qso["square"]:
            qso["square"] = None
        if "locator" not in qso or not qso["locator"]:
            if len(qso["locator"]) < 6:
                qso["augmented_locator"] = self.find_augmented_locator(qso["callsign"], qso["locator"])
        if "band" not in qso or not qso["band"]:
            qso["band"] = self.app.client_mgr.current_band
        if "txmode" in qso and qso["txmode"]:
            txmode = qso["txmode"]
        else:
            if len(qso["tx"]) == 3:
                txmode = "CW"
            else:
                if "-" in qso["band"]:
                    txmode = qso["band"].split('-')[1]
                else:
                    txmode = "SSB"

        if "distance" not in qso or not qso["distance"]:
            qso = self.app.client_mgr.do_lookup_locator(qso)

        if "propmode" in qso and qso["propmode"]:
            propmode = qso["propmode"]
        else:
            propmode = "TR"

            if qso["tx"].upper().endswith('A') or qso["rx"].upper().endswith('A'):
                propmode = "AU"

            if "MS" in txmode.upper() and float(qso["distance"]) > 500.0:
                propmode = "MS"

            if float(qso["distance"]) > 3000:
                propmode = "EME"
        accumulated_square = None
        if "locator" in qso and qso["locator"]:
            cur.execute(
                """SELECT DISTINCT upper(substr(locator, 1, 4)) as loc FROM nac_log_new WHERE split_part(split_part(band,'-',1), '.',1) = %s""",
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

        if "augmented_locator" not in qso or not qso["augmented_locator"] and "locator" in qso and qso["locator"]:
            qso["augmented_locator"] = qso["locator"]

        if "id" in qso and qso["id"]:
            cur.execute("""UPDATE nac_log_new SET date=%s, time=%s, callsign=%s, tx=%s , rx=%s , locator=%s, distance=%s, square=%s, points=%s, complete=%s, band=%s, accumulated_sqn=%s, txmode=%s, propmode=%s, augmented_locator=%s 
                                  WHERE qsoid = %s""",
                        (qso["date"], qso["time"], qso["callsign"], qso["tx"], qso["rx"], qso["locator"],
                         qso["distance"], qso["square"], qso["points"], qso["complete"], band_or_fq, accumulated_square,
                         txmode, propmode, qso["augmented_locator"], qso["id"]))
            new_qso_id = qso["id"]
        else:

            cur.execute("""INSERT INTO nac_log_new (date, time, callsign, tx , rx , locator, distance, square, points, complete, band, accumulated_sqn, txmode, propmode, augmented_locator) 
                      values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,%s, %s) RETURNING qsoid""",
                    (qso["date"], qso["time"], qso["callsign"], qso["tx"], qso["rx"], qso["locator"],
                     qso["distance"], qso["square"], qso["points"], qso["complete"], band_or_fq, accumulated_square,
                     txmode, propmode, qso["augmented_locator"]))
            new_qso_id = cur.fetchone()[0]
        self.db.commit()
        cur.close()

        if "augmented_locator" in qso and qso["augmented_locator"]:
            self.app.client_mgr.add_mh_on_map(qso["augmented_locator"])
        if "id" in qso and qso["id"]:
            return qso["id"]
        else:
            self.app.client_mgr.add_qso(qso)
            return new_qso_id

    def callsigns_in_locator(self, loc):
        cur = self.db.cursor()
        q = "SELECT DISTINCT callsign from nac_log_new WHERE locator like %s ORDER BY callsign"
        cur.execute(q, (loc+'%',))
        rows = cur.fetchall()
        return [x[0] for x in rows]


    def my_qth(self):
        rows = self.fetch_my_current_data()
        my_data = {x["key"]: x["value"] for x in rows}
        myqth = my_data["my_locator"]
        return myqth

    def my_pa_on(self):
        if not self.p27:
            return "Core station out of control"

        pa_rdy = self.p26_bit_read(P26_PA_READY)
        if not pa_rdy:
            self.logger.info("Igniting booster")
            self.p27.bit_write(P27_PA_ON_L, LOW)
            time.sleep(0.1)
            self.p27.bit_write(P27_PA_ON_L, HIGH)
            return "Ignition sequence started"
        else:
            return "Power booster is ready<br/>"

    def my_pa_off(self):
        if not self.p27:
            return "Core station out of control"
        self.logger.info("Shutting down PA")
        self.p27.bit_write(P27_PA_ON_L, HIGH)
        self.p27.bit_write(P27_PA_OFF_L, LOW)
        time.sleep(0.1)
        self.p27.bit_write(P27_PA_OFF_L, HIGH)
        return "PA is shut down"

    def my_qro_on(self):
        if not self.p27:
            return "Core station out of control"
        pa_rdy = self.p26_bit_read(P26_PA_READY)
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

    def merge_into_log_db(self, cur, ret, qso):

        #starttime = starttime.replace(':', '')[:4]
        starttime = qso["TIME_ON"][:4]
        startdate = qso["QSO_DATE"][:4]+'-'+qso["QSO_DATE"][4:6]+"-"+qso["QSO_DATE"][6:8]


        #_endtime = endtime.replace(':', '')[:4]
        _endtime =  qso["TIME_OFF"][:4]
        if "PROP_MODE" in qso:
            propmode=qso["PROP_MODE"]
        else:
            propmode="TR"

        txmode = qso["MODE"]
        frequency = qso["FREQ"]
        if propmode == "TR":
            propmode = "T"
        callsign = qso["CALL"].upper()
        if "GRIDSQUARE" in qso:
            locator = qso["GRIDSQUARE"].upper()
        else:
            locator = None
        trprt = qso["RST_SENT"]
        rrprt = qso["RST_RCVD"]

        q = """SELECT id, qso_date, time_on, rst_sent, rst_rcvd, gridsquare, propmode, txmode from adif_log where qso_date=%s and
                                 abs(date_part('hour',time_on::time-%s::time)*60+date_part('minute',time_on::time-%s::time)) < 10
                                 and call = %s"""
        cur.execute(q, (startdate, starttime, starttime, callsign))
        lines = cur.fetchall()
        if len(lines) == 1:
            # print("Found QSO: %s" % lines)
            qso = lines[0]
            qso_date = qso[1]
            qso_time = qso[2]
            adjustments = 0
            if locator not in qso[5]:
                self.logger.error("Bad locator %s, should be %s" % (qso[5], locator))
                bearing, distance, points, square_no = self.distance_to(locator, qso_date, qso_time)
                cur.execute(
                    "UPDATE adif_log set gridsquare = %s, distance = %s, stnmate_square_no = %s, stnmate_points = %s where id=%s",
                    (locator, str(int(distance * 100) / 100.0), square_no, points, qso[0]))
                adjustments += 1
            if qso[6] != propmode and propmode:
                self.logger.error("Bad propagation mode %s, should be %s" % (qso[6], propmode))
                cur.execute("UPDATE adif_log set propmode = %s where id=%s", (propmode, qso[0]))
                adjustments += 1
            if qso[7] != txmode:
                self.logger.error("Bad transmit mode %s, should be %s" % (qso[7], txmode))
                cur.execute("UPDATE adif_log set mode = %s where id=%s", (txmode, qso[0]))
                adjustments += 1
            if qso[3] != trprt:
                self.logger.error("Bad sent report %s, should be %s" % (qso[3], trprt))
                cur.execute("UPDATE adif_log set rst_sent = %s where id=%s", (trprt, qso[0]))
                adjustments += 1
            if qso[4] != rrprt:
                self.logger.error("Bad received report %s, should be %s" % (qso[4], rrprt))
                cur.execute("UPDATE adif_log set rst_rcvd = %s where id=%s", (rrprt, qso[0]))
                adjustments += 1
            if adjustments:
                ret["adjusted"] += 1
        elif len(lines) > 1:
            self.logger.error("Multiple qsos found; %s" % lines)
            pass
        else:
            q = """SELECT qsoid, date, time, tx, rx, locator, abs(date_part('hour',time::time-%s::time)*60+date_part('minute',time::time-%s::time)) as datetime from nac_log_new where date=%s
                                    and callsign = %s"""
            cur.execute(q, (starttime, starttime, startdate, callsign))
            lines = cur.fetchall()
            self.logger.error("Missing QSO: %s" % str(qso))
            if lines:
                self.logger.debug("Found:", lines)
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
                    "band": "%d-%s" % (int(float(frequency)), txmode),
                    "propmode": propmode,
                    "txmode": txmode,
                    "frequency": frequency,
                }
                # self.do_commit_qso(qso)
                ret["added"] += 1

    def process_log_file(self, cur, file_data, ret):
        for qsos in file_data.splitlines():
            qso = qsos.split(',')
            self.merge_into_old_log_db(cur, qso, ret)

    def process_adi_file(self, cur, file_data, ret):
        qsos_raw, adif_header = adif_io.read_from_string(file_data)
        for qso in qsos_raw:
            self.merge_into_log_db(cur, ret, qso)

    def my_wsjtx_upload(self, request):
        """
        :param request: The request object containing files to be uploaded.
        :return: A string indicating the number of QSOs added and adjusted during the upload process.
        """
        ret = {"added": 0, "adjusted": 0}
        cur = self.db.cursor()
        for k, v in request.files.items():
            file_data = v.read().decode("utf-8")
            if v.filename.endswith(".log"):
                self.process_log_file(cur, file_data, ret)
                break
            elif v.filename.endswith(".adi"):
                self.process_adi_file(cur, file_data, ret)
            if ret["adjusted"]:
                self.db.commit()
        return "QSQ:s added: %d, adjusted: %s" % (ret["added"], ret["adjusted"])

    def merge_into_old_log_db(self, cur, qso, ret):
        try:

            startdate, starttime, enddate, endtime, callsign, locator, frequency, txmode, trprt, rrprt, power, comment, dxname, propmode = qso[0:14]
        except:
            import pprint
            pprint.pprint(qso)
            raise
        starttime = starttime.replace(':', '')[:4]

        timestamp = util.str_to_datetime(startdate,starttime)
        ts_min,ts_max = util.get_timespan(timestamp, 10)

        min_date_str,min_time_str = util.datetime_to_str(ts_min)
        max_date_str, max_time_str = util.datetime_to_str(ts_max)

        _endtime = endtime.replace(':', '')[:4]
        if propmode == "T":
            propmode = "TR"
        callsign = callsign.upper()
        locator = locator.upper()
        augmented_locator = self.find_augmented_locator(callsign, locator)

        q = """SELECT qsoid, date, time, tx, rx, locator, propmode, txmode, augmented_locator from nac_log_new where 
                                concat(date,time) between %s and %s
                                 and callsign = %s"""
        cur.execute(q, (min_date_str+min_time_str,max_date_str+max_time_str, callsign))
        lines = cur.fetchall()
        if len(lines) == 1:
            # print("Found QSO: %s" % lines)
            qso_in_db = lines[0]
            qso_in_db_date = qso_in_db[1]
            qso_in_db_time = qso_in_db[2]
            adjustments = 0
            if locator:
                if augmented_locator and (qso_in_db[8] is None or augmented_locator not in qso_in_db[8]) and augmented_locator.startswith(locator):
                    self.logger.warning("Adding or updating augmented locator %s" % augmented_locator)
                    bearing, distance, points, square_no = self.distance_to(augmented_locator, qso_in_db_date, qso_in_db_time)
                    cur.execute(
                        "UPDATE nac_log_new set augmented_locator = %s, distance = %s, square = %s, points = %s where qsoid=%s",
                        (augmented_locator, str(int(distance * 100) / 100.0), square_no, points, qso_in_db[0]))
                    adjustments += 1
            else:
                if augmented_locator and (qso_in_db[8] is None or augmented_locator not in qso_in_db[8]):
                    self.logger.warning("Adding augmented locator %s from plain lookup" % augmented_locator)
                    bearing, distance, points, square_no = self.distance_to(augmented_locator, qso_in_db_date, qso_in_db_time)
                    cur.execute(
                        "UPDATE nac_log_new set augmented_locator = %s, distance = %s, square = %s, points = %s where qsoid=%s",
                        (augmented_locator, str(int(distance * 100) / 100.0), square_no, points, qso_in_db[0]))
                    adjustments += 1

            if locator and (qso_in_db[5] is None or locator not in qso_in_db[5]):
                self.logger.error("Bad locator %s, should be %s" % (qso_in_db[5], locator))
                bearing, distance, points, square_no = self.distance_to(locator, qso_in_db_date, qso_in_db_time)
                cur.execute(
                    "UPDATE nac_log_new set locator = %s, distance = %s, square = %s, points = %s where qsoid=%s",
                    (locator, str(int(distance * 100) / 100.0), square_no, points, qso_in_db[0]))
                adjustments += 1
            if qso_in_db[6] != propmode and propmode:
                self.logger.error("Bad propagation mode %s, should be %s" % (qso_in_db[6], propmode))
                cur.execute("UPDATE nac_log_new set propmode = %s where qsoid=%s", (propmode, qso_in_db[0]))
                adjustments += 1
            if qso_in_db[7] != txmode:
                self.logger.error("Bad transmit mode %s, should be %s" % (qso_in_db[7], txmode))
                cur.execute("UPDATE nac_log_new set txmode = %s where qsoid=%s", (txmode, qso_in_db[0]))
                adjustments += 1
            if qso_in_db[3] != trprt:
                self.logger.error("Bad sent report %s, should be %s" % (qso_in_db[3], trprt))
                cur.execute("UPDATE nac_log_new set tx = %s where qsoid=%s", (trprt, qso_in_db[0]))
                adjustments += 1
            if qso_in_db[4] != rrprt:
                self.logger.error("Bad received report %s, should be %s" % (qso_in_db[4], rrprt))
                cur.execute("UPDATE nac_log_new set rx = %s where qsoid=%s", (rrprt, qso_in_db[0]))
                adjustments += 1
            if adjustments:
                ret["adjusted"] += 1
        elif len(lines) > 1:
            self.logger.error("Multiple qsos found; %s" % lines)
            pass
        else:
            q = """SELECT qsoid, date, time, tx, rx, locator, abs(date_part('hour',time::time-%s::time)*60+date_part('minute',time::time-%s::time)) as datetime from nac_log_new where date=%s
                            and callsign = %s"""
            cur.execute(q, (starttime, starttime, startdate, callsign))
            lines = cur.fetchall()
            self.logger.error("Missing QSO: %s" % qso)
            if lines:
                self.logger.debug("Found: %s" % lines)
            else:
                bearing = None
                distance = None
                points = None
                square_no = None
                if locator:
                    bearing, distance, points, square_no = self.distance_to(locator, startdate, starttime)
                qso_in_db = {
                    "date": startdate,
                    "time": starttime,
                    "callsign": callsign,
                    "tx": trprt,
                    "rx": rrprt,
                    "locator": locator,
                    "distance": str(int(distance * 100) / 100.0) if distance else None,
                    "square": square_no,
                    "points": points,
                    "complete": True,
                    "band": "%d-%s" % (int(float(frequency)), txmode),
                    "propmode": propmode,
                    "txmode": txmode,
                    "frequency": frequency,
                    "bearing": bearing
                }
                self.do_commit_qso(qso_in_db)
                ret["added"] += 1

    def make_log(self, json):
        band = json.get("band", None)
        log_remarks = json.get("log_remarks", None)
        if band:
            contest_log = produce_contest_log(band, self.logger, log_remarks=log_remarks)
            json["contest_log"] = contest_log
            emit_log(json)

    @staticmethod
    def make_adif_log(json):
        from adif_log import produce_adif_log
        band = json.get("band", None)
        if band:
            contest_log = produce_adif_log()
            json["contest_log"] = contest_log
            emit_log(json)


    def toggle_qro(self):
        if self.p27 and self.p26:
            # pa_rdy = self.p26_bit_read(P26_PA_READY)
            pa_pwr_on = not self.p26_bit_read(P26_PA_PWR_ON_L)
            if pa_pwr_on:
                pa_on = not self.p26_bit_read(P26_PA_QRO_ACTIVE)
                if pa_on:
                    self.p27.bit_write(P27_PA_ON_L, HIGH)
                else:
                    self.p27.bit_write(P27_PA_ON_L, LOW)
            else:
                self.p27.bit_write(P27_PA_ON_L, HIGH)
            self.app.client_mgr.status_update(force=True)


    def toggle_rx70(self):
        if self.p27 and self.p26:

            rx70_on = not self.p26_bit_read(P26_RX_432_L)
            if rx70_on:
                self.p27.bit_write(P27_RX_432_L, HIGH)
            else:
                self.p27.bit_write(P27_RX_432_L, LOW)

            self.app.client_mgr.status_update(force=True)

    def toggle_tx70(self):
        if self.p27 and self.p26:

            tx70_on = not self.p26_bit_read(P26_TX_432_L)
            if tx70_on:
                self.p27.bit_write(P27_TX_432_L, HIGH)
            else:
                self.p27.bit_write(P27_TX_432_L, LOW)

            self.app.client_mgr.status_update(force=True)

    def set_trx70(self, json):
        if self.p27 and self.p26:

            if "tx" in json:
                if json["tx"]:
                    self.p27.bit_write(P27_TX_432_L, LOW)
                else:
                    self.p27.bit_write(P27_TX_432_L, HIGH)

            if "rx" in json:
                if json["rx"]:
                    self.p27.bit_write(P27_RX_432_L, LOW)
                else:
                    self.p27.bit_write(P27_RX_432_L, HIGH)

            self.app.client_mgr.status_update(force=True)

    def toggle_pa(self):
        if self.p27 and self.p26:

            if self.pa_running is None:
                pa_rdy = self.p26_bit_read(P26_PA_READY)
                self.pa_running = pa_rdy

            rx_on = not self.p26_bit_read(P26_TRX_RX_ACTIVE_L)
            tx_on = not self.p26_bit_read(P26_TRX_TX_ACTIVE_L)

            if self.pa_running:
                self.p27.bit_write(P27_PA_OFF_L, LOW)
                time.sleep(0.1)
                self.p27.bit_write(P27_PA_OFF_L, HIGH)
                self.pa_running = False
            else:
                if rx_on or tx_on:
                    self.p27.bit_write(P27_PA_ON_L, LOW)
                    time.sleep(0.1)
                    self.p27.bit_write(P27_PA_ON_L, HIGH)
                    self.pa_running = True

            self.app.client_mgr.status_update(force=True)

    def az_track(self, what):

        try:
            az_value = int(what)
            self.app.azel.az_track_bearing(az_value)
            return
        except ValueError:
            pass

        try:
            n, s, w, e, lat, lon = mh.to_rect(what)
            self.app.azel.az_track_loc(what)
            self.app.client_mgr.add_mh_on_map(what)
        except (TypeError, ValueError):
            pass

        found_loc = self.lookup_locator(what)
        if found_loc:
            self.app.azel.az_track_station(what)


    def lookup_locator(self, callsign, given_loc=None) -> str:
        """
        Retrieves the locator associated with a given callsign from the QSO log or, if not found, from the callbook in the database.

        :param callsign: The callsign to lookup.
        :param given_loc: The optional locator to match against.
        :return: The found locator if found and matches given_loc, otherwise None.
        """
        q = """SELECT qsoid, locator from nac_log_new where callsign = %s order by date desc"""

        cur = self.db.cursor()
        cur.execute(q, (callsign,))
        rows = cur.fetchall()
        found_loc = None

        for row in rows:
            if not row[1] or len(row[1]) < 6:
                continue
            found_loc = row[1]
            break

        if found_loc is None:
            q = """SELECT locator from callbook where callsign = %s"""
            cur = self.db.cursor()
            cur.execute(q, (callsign,))
            rows = cur.fetchall()
            for row in rows:
                if len(row[0]) < 6:
                    continue
                found_loc = row[0]
            if given_loc:
                return found_loc if given_loc[:4] == found_loc[:4] else None
            else:
                return found_loc
        else:
            if given_loc:
                return found_loc if given_loc[:4] == found_loc[:4] else None
            else:
                return found_loc



    def store_map_setting(self, json, current_band, map_mh_length, log_scope):
        """
        Store the map setting in the database.

        :param json: A dictionary containing the map settings.
        :param current_band: The current band.
        :param map_mh_length: The map MH length.
        :param log_scope: The log scope.
        :return: None
        """
        from_az, to_az = self.app.azel.get_az_sector()
        q = """INSERT INTO origi(origo_lon, origo_lat, zoom, mh_length, band, az_from, az_to, log_scope)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT ON CONSTRAINT origi_keys DO UPDATE
               SET origo_lon = %s, origo_lat = %s, zoom = %s 
               """
               # """WHERE mh_length = %s and band=%s and az_from=%s and az_to=%s and log_scope=%s"""
        args = [json['lon'], json['lat'], json['zoom'], map_mh_length, current_band, from_az, to_az, log_scope]
        args.extend([ json['lon'], json['lat'], json['zoom']])
        # args.extend(args)
        cur = self.db.cursor()
        cur.execute(q, args)
        self.db.commit()

    def get_map_setting(self, current_band, map_mh_length, log_scope):
        q = """SELECT origo_lon, origo_lat, zoom from origi WHERE mh_length = %s and band = %s and az_from = %s and az_to = %s and log_scope = %s"""
        from_az, to_az = self.app.azel.get_az_sector()
        args = [map_mh_length, current_band, from_az, to_az, log_scope]
        cur = self.db.cursor()
        cur.execute(q, args)
        lines = cur.fetchall()
        if lines:
            return lines[0]

    def get_reachable_stations(self, max_age=1800, max_dist=40000, max_beamwidth=30, band="144"):  # max_age in seconds, max_distance in km, max_beamwidth in degrees
        # self.logger.debug("get_reachable_stations max_age=%d, max_dist=%d. max_beamwidth=%d" %(max_age, max_dist, max_beamwidth))

        dt = datetime.now()
        # getting the timestamp
        ts = datetime.timestamp(dt)
        if band.startswith("50"):
            minfq=50000000
            maxfq=54000000
        elif band.startswith("144"):
            minfq=144000000
            maxfq=146000000
        elif band.startswith("432"):
            minfq=432000000
            maxfq=438000000
        else:
            minfq=0
            maxfq=360000000000

        q1 = """ select distinct on (r.rx_callsign, r.rx_loc) r.rx_callsign as callsign, 
                                    r.rx_loc as locator, r.rx_heading as az, r.my_rx_distance as dist, 
                                    (extract(epoch from statement_timestamp()) - r.happened_at)/60 as age_minutes, 
                                    r.my_rx_heading as my_az, r.mode as txmode, r.happened_at as happened_at, r.dx_callsign as dx_callsign, r.dx_loc as dx_loc
                from reports as r
                where ABS(MOD(r.rx_heading - 180, 360) - r.my_rx_heading) < %s/2
                    and r.my_rx_distance < %s 
                    and  extract(epoch from statement_timestamp()) - happened_at < %s
                group by callsign, locator, az, dist, age_minutes, my_az, txmode, happened_at, dx_callsign, dx_loc
                union
                select distinct on (t.dx_callsign, t.dx_loc) t.dx_callsign as callsign , 
                                    t.dx_loc as locator, t.tx_heading as az, t.my_tx_distance as dist, 
                                    (extract(epoch from statement_timestamp()) - t.happened_at)/60 as age_minutes, 
                                    t.my_tx_heading as my_az, t.mode as txmode, t.happened_at as happened_at, t.rx_callsign as dx_callsign, t.rx_loc as dx_loc
                from reports as t
                where ABS(MOD(t.tx_heading - 180, 360) - t.my_tx_heading) < %s/2
                    and t.my_tx_distance < %s 
                    and  extract(epoch from statement_timestamp()) - t.happened_at < %s
                group by callsign, locator, az, dist, age_minutes, my_az, txmode, happened_at, dx_callsign, dx_loc
                order by age_minutes;
            """
        q = """ select r.rx_callsign as callsign, 
                                            r.rx_loc as locator, r.rx_heading as az, r.my_rx_distance as dist, 
                                            (%s - r.happened_at)/60 as age_minutes, 
                                            r.my_rx_heading as my_az, r.mode as txmode, r.happened_at as happened_at, r.dx_callsign as dx_callsign, 
                                            r.dx_loc as dx_loc, r.my_tx_heading, r.tx_heading, r.my_tx_distance, r.frequency, r.snr
                        from reports as r
                        where ABS(MOD(r.rx_heading - 180, 360) - r.my_rx_heading) < %s/2
                            and r.my_rx_distance < %s 
                            and  %s - happened_at < %s
                        order by happened_at desc 
                    """
        beacon_query = """ select b.dx_callsign as callsign, 
                                                    b.dx_loc as locator, b.frequency as frequency, b.snr as snr, b.mode as txmode, b.qtf as az
                                from beacons b 
                                where frequency >= %s and frequency <= %s
                            """

        with self.db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            #cur.execute(q, (max_beamwidth, max_dist, max_age, max_beamwidth, max_dist, max_age))
            # self.logger.debug("executing %s with max_beamwidth=%d, max_dist=%d, max_age=%d" %(q, max_beamwidth, max_dist, max_age))

            ret = {}

            cur.execute(beacon_query, (minfq, maxfq))
            rows = cur.fetchall()
            for r in rows:
                cs = r["callsign"]
                if cs not in ret:
                    ret[cs] = r

            cur.execute(q, (ts, max_beamwidth, max_dist, ts, max_age))
            rows = cur.fetchall()
            for r in rows:
                cs = r["callsign"]
                if cs not in ret or ret[cs]["happened_at"] < r["happened_at"]:
                    ret[cs] = r
                dxcs = r["dx_callsign"]
                if dxcs not in ret or ("happened_at" in ret[dxcs] and ret[dxcs]["happened_at"] < r["happened_at"]):
                    rp = r.copy()
                    rp["callsign"] = dxcs
                    rp["locator"] = r["dx_loc"]
                    rp["dx_loc"] = r["locator"]
                    rp["dx_callsign"] = cs
                    rp["az"] = r["tx_heading"]
                    rp["tx_heading"] = r["az"]
                    rp["dist"] = r["my_tx_distance"]
                    rp["my_tx_distance"] = r["dist"]
                    rp["my_az"] = r["my_tx_heading"]
                    rp["my_tx_heading"] = r["my_az"]
                    ret[cs] = dict(r)
                    ret[dxcs] = dict(rp)


            return ret

    def translate_qras(self):
        """
        Translate QRA locators to MH locators in the `nac_log_new` table.

        :return: A string containing the translated QRA locators and the number of locators translated.
        """
        import locator.src.qra as qra
        with self.db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            q = "SELECT qsoid, callsign, locator from nac_log_new where length(locator) = 5"

            cur.execute(q)
            rows = cur.fetchall()
            n=0
            ret = ""
            for r in rows:
                try:
                    lat, lon = qra.to_location(r['locator'])
                except:
                    self.logger.error("QRA locator %s of %s is not recognizable"%(r['locator'],r['callsign']))
                    continue
                mhloc = mh.to_maiden(lat, lon).upper()
                s = "QRA locator %s of %s corresponds to MH locator %s" %(r['locator'], r['callsign'], mhloc)
                ret += s + "<br/>"
                self.logger.info(s)
                q1="UPDATE nac_log_new set locator = %s where qsoid=%s"
                cur.execute(q1, (mhloc, r['qsoid']))
                n += 1
        return ret + "%d QRA locators translated" % n

    def recompute_distances(self):
        """
        Recomputes distances for callsigns in the database based on their locator and my_locator.
        Updates the distance field in the database for each callsign that has a changed distance.

        :return: A formatted string listing the ODXs and MH fields and the number of distances changed.
        """

        from collections import defaultdict
        q =  "SELECT qsoid,callsign,locator,my_locator, distance, propmode, band from nac_log_new"

        with self.db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(q)
            rows = cur.fetchall()
            ret = ""
            n=0
            odxs = {}  # {propmode/band: (callsign, distance)
            mhfields = {}  # {field/band: count}
            for r in rows:
                band = r["band"].split('.')[0]
                dx_loc = r["locator"]
                my_loc = r["my_locator"]
                callsign = r["callsign"]
                if dx_loc and my_loc:
                    dx_loc = dx_loc.upper()
                    my_loc = my_loc.upper()
                    bearing, distance = mh.distance_between(my_loc, dx_loc)
                    odx_key = r["propmode"]+"/"+band
                    if odx_key not in odxs:
                        odxs[odx_key] = "",0.0
                    if distance > odxs[odx_key][1]:
                        odxs[odx_key] = callsign,distance
                    field_key = dx_loc[0:2]+"/"+band
                    if field_key not in mhfields:
                        mhfields[field_key] = 1
                    else:
                        mhfields[field_key] += 1
                    if not  r["distance"] or abs(distance - r["distance"]) > 0.1:
                        if not r["distance"]:
                            s = "Distance computed for %s to %5.1f" % (callsign, distance)
                        else:
                            s = "Distance changed for %s from %5.1f to %5.1f" % (callsign, r["distance"], distance)
                        self.logger.info(s)
                        ret += s + "<br/>"
                        q1="UPDATE nac_log_new set distance = %s where qsoid=%s"
                        cur.execute(q1, (distance, r["qsoid"]))
                        n += 1
            # ret += pprint.pformat(odxs)
            pprint.pprint(mhfields)
            ret += "ODX list:<br/>"
            for k,v in odxs.items():
                ret += "%s: %s %5.0f km<br/>" % (k, v[0],v[1])
            ret += "MH fields: <br/>"
            for band in ["50","144","432","1296"]:
                nf=0
                for k,v in mhfields.items():
                    if k.endswith(band):
                        ret += "%s: %d<br/>" % (k, v)
                        nf += 1
                ret += "%d fields on %s MHz<br/>" % (nf, band)
        return ret + "%d distances changed" % n