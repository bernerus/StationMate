
import os, signal
import sys
import time
import datetime
import argparse


def kill_siblings():

    # Ask user for the name of process
    name = "StnMate2/main.py"
    try:

        # iterating through each instance of the process
        for line in os.popen("ps -ef | grep " + name + " | grep -v grep"):
            fields = line.split()

            # extracting Process ID from the output
            pid = fields[1]
            ppid = fields[2]
            if int(pid) == os.getpid(): # Avoid suicide
                continue
            # if fields[-1].endswith("debugging"):
                # continue

            # terminating process
            while True:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    # os.kill(int(ppid), signal.SIGSTOP)
                    print("Sent kill signal to process %d" % int(pid))
                    time.sleep(1)
                except Exception as e:
                    print ("Process %s is now dead: %s" % (int(pid), e))
                    break

    except:
        print("Error Encountered while running script")


parser = argparse.ArgumentParser(
                    prog='StnMate2',
                    description='This program helps me remote controlling my ham station and aid in the finding VHF/UHF Dx and logging QSOs',
                    epilog='SM6FBQ 2021-2023')
parser.add_argument("--debugging", action="store_true",
                    help="Run a debugging session, kills any simultaneously running sibling instances")

parsed_args=parser.parse_args()

if parsed_args.debugging:
    kill_siblings()

import socket

address = ("", 8878)
s = socket.socket()
try:
    s.bind(address)
except OSError as e:
    print("Another instance of StnMate2 is running. Quitting: %s" % e)
    sys.exit(1)


from flask import Flask, render_template, request
import psycopg2
from config import DevelopmentConfig
from flask_socketio import SocketIO, emit, send, Namespace
from morsetx import *
import threading
import atexit
import logging

logger=logging.getLogger(__name__)
if parsed_args.debugging:
    logger.setLevel("DEBUG")
else:
    logger.setLevel("INFO")
hdlr = logging.StreamHandler()
hdlr.setFormatter(logging.Formatter('%(asctime)s %(levelname)8s %(filename)20s:%(lineno)-5s %(message)s'))
logger.addHandler(hdlr)

logger.info("Starting stnMate")


socket_io = SocketIO(async_mode="eventlet", logger=False, engineio_logger=False, ping_timeout=60, ping_interval=4)


class MyApp(Flask):
    def __init__(self, import_name, **kwargs):

        super().__init__(import_name, **kwargs)

        self.config.from_object(DevelopmentConfig)

        with open("etc/google_api.txt") as f:
            api_key = f.readline()
        self.config['GOOGLEMAPS_API_KEY'] = api_key

        socket_io.init_app(self)

        self.socket_io = socket_io

        self._db = psycopg2.connect(dbname='ham_station')

        from hamop import HamOp
        self.ham_op = HamOp(self, logger, self._db)

        from clientmgr import ClientMgr
        self.client_mgr = ClientMgr(self, logger, socket_io)

        from azel import AzElControl
        self.azel = AzElControl(self, logger, socket_io, hysteresis=14)

        from aircraft_tracker import AircraftTracker
        self.aircraft_tracker = AircraftTracker(self, logger, socket_io, url="http://192.168.1.129:8754")

        from station_tracker import StationTracker
        self.station_tracker = StationTracker(self, logger, socket_io)

        rows = self.ham_op.fetch_my_current_data("144")
        self.my_data = {x["key"]: x["value"] for x in rows}

        self.keyer = Morser(logger, speed=None, p20=self.azel.p20)
        self.keyer_thread = threading.Thread(target=self.keyer.background_thread, args=())
        self.keyer_thread.daemon = True  # Daemonize keyer_thread
        self.keyer_thread.start()

app=MyApp(__name__)
class WsjtxNamespace(Namespace):

    @staticmethod
    def on_connect():
        logger.info("WSJTX exchanger connected")
        emit('server_response', {'data': 'Connected', 'count': 0})
    @staticmethod
    def on_disconnect():
        logger.info("WSJTX exchanger disconnected")
        pass

    @staticmethod
    def on_my_event(sid, data):
        emit('my_response', data)

    @staticmethod
    def on_set_dx_note(json):
        logger.info("Fill DX note %s" % json)
        callsign = json["callsign"]
        locator = json["locator"]
        app.client_mgr.set_dx_call(callsign, locator)
        emit("fill_dx_note", json, namespace="/", broadcast=True)

    @staticmethod
    def on_set_dx_grid(grid):
        logger.info("Set DX grid to %s" % grid)
        emit("fill_dx_grid", grid, namespace="/", broadcast=True)

    @staticmethod
    def on_set_trx70(json):
        logger.info("Set TRX70")
        app.ham_op.set_trx70(json)

    @staticmethod
    def on_commit_wsjtx_qso(json):
        dt = json["date_time_on"]  # type: str
        fq = int(json["dial_frequency"])
        qso = {
            "callsign": json["dx_call"],
            "band": "%f" % (fq / 1000000),
            "txmode": json["txmode"],
            "tx": json["report_sent"],
            "rx": json["report_received"],
            "locator": json["dx_grid"],
            "frequency": "%f" % (fq / 1000000),
            "date": dt[:10],
            "time": dt[11:13] + dt[14:16],
            "complete": True,
            "propmode": json["propmode"]
        }



        # If given only the square, look up any known full locator if previously known
        found_loc = app.ham_op.lookup_locator(json["dx_call"], json["dx_grid"])
        if found_loc:
            qso["augmented_locator"] = found_loc

        bearing, distance, points, square_count = app.ham_op.distance_to(qso["locator"], qso["date"], qso["time"])
        qso["distance"] = "%4.1f" % distance
        qso["points"] = points

        # "dx_grid": p.dx_grid,
        # "dx_call": p.dx_call,
        # "dial_frequency": p.dial_frequency,
        # "mode": p.mode,
        # "comments": p.comments,
        # "date_time_off": p.date_time_off,
        # "date_time_on": p.date_time_on,
        # "exch_received": p.exch_received,
        # "exch_sent": p.exch_sent,
        # "my_call": p.my_call,
        # "my_grid": p.my_grid,
        # "name": p.name,
        # "op_name": p.op_name,
        # "propmode": p.propmode,
        # "report_received": p.report_received,
        # "report_sent": p.report_send,
        # "tx_power": p.tx_power

        logger.info("Commit QSO from WSJT-X %s", qso)
        new_qso_id = app.ham_op.do_commit_qso(qso)
        qso["id"] = new_qso_id
        # app.client_mgr.add_qso(qso)  # do_commit_qso does this.

socket_io.on_namespace(WsjtxNamespace('/wsjtx'))

@app.route('/')
def index():
    with open("etc/g16e.txt") as f:
        key=f.readline()
    return render_template('sm6fbq.html',  gapikey=key, async_mode=socket_io.async_mode)

@app.route('/az')
def get_azimuth():
    return "Az=%d ticks" % app.azel.az

@app.route("/help")
def cmd_help():
    help_text = """
        <table>
        <tr><td>/</td><td>Start antenna and log view</td></tr>
        <tr><td>/help</td><td>See this help text</td></tr>
        <tr><td>/az</td><td>Return current antenna azimuth in ticks</td></tr>
        <tr><td>/translate_qras</td><td>Translate all legacy QRA locators in the log to Maidenhead locators</td></tr>
        <tr><td>/recompute_distances</td><td>Recompute all distances in the log and add distances where missing</td></tr>
        <tr><td>/status</td><td>Return rig status</td></tr>
        <tr><td>/paon</td><td>Turn on the power supply to the transmitter power amplifiers</td></tr>
        <tr><td>/paoff</td><td>Turn off the power supply to the transmitter power amplifiers</td></tr>
        <tr><td>/qroon</td><td>Enable high power transmission</td></tr>
        <tr><td>/qrooff</td><td>Disable high power transmission</td></tr>
        <tr><td>/rx70</td><td>Configure core station for 70cm reception (Just causes RX disconnect from the antenna)</td></tr>
        <tr><td>/tx70</td><td>Configure core station for 70cm transmission.</td></tr>
        <tr><td>/rx2</td><td>Opposite of rx70</td></tr>
        <tr><td>/tx2</td><td>Opposite of tx70</td></tr>
        <tr><td>/wsjtx_upload</td><td>Upload a wsjt-x log file to the station log.</td></tr>
        <tr><td>/az_scan</td><td>Sweep the antenna azimuth. Requires parameters</td></tr>
        <tr><td>/commit_qso</td><td>Commit a qso to the station log. Requires parameters</td></tr></table>
        """
    return help_text

@app.route("/myqth")
def my_qth():
    return app.ham_op.my_qth()

@app.route("/translate_qras")  # Maintenance entry, converts all legacy QRA locators to maidenhead locators.
def translate_qras():
    return app.ham_op.translate_qras()

@app.route("/recompute_distances")  # Maintenance entry, recomputes all distances
def recompute_distances():
    return app.ham_op.recompute_distances()

@app.route("/status")
def my_status():
    return app.ham_op.my_status()


@app.route("/paon")
def my_pa_on():
    return app.ham_op.my_pa_on()



@app.route("/paoff")
def my_pa_off():
    return app.ham_op.my_pa_off()



@app.route("/qroon")
def my_qro_on():
    return app.ham_op.my_qro_on()


@app.route("/qrooff")
def my_qro_off():
    return app.ham_op.my_qro_off()


@app.route("/rx70")
def my_rx70_on():
    return app.ham_op.my_rx70_on()

@app.route("/rx2")
def my_rx70_off():
    return app.ham_op.my_rx70_off()

@app.route("/tx70")
def my_tx70_on():
    return app.ham_op.my_tx70_on()

@app.route("/tx2")
def my_tx70_off():
    return app.ham_op.my_tx70_off()

@app.route('/wsjtx_upload', methods=['POST'])
def my_wsjtx_upload():
    return app.ham_op.my_wsjtx_upload(request)

@app.route('/az_scan', defaults={"az_start":0,"az_stop":180, "period":30, "sweeps":2, "increment":15})
def az_scan(az_start,az_stop,period,sweeps, increment):
    logger.info("AZ_scan start=%d, az_stop=%d, period=%d, sweeps=%d increment=%d" % (az_start,az_stop,period,sweeps, increment))
    return app.azel.sweep(az_start,az_stop,period,sweeps,increment)

@app.route('/commit_qso', methods=['POST'])
def commit_qso():
    return commit_qso(request)

##############

@socket_io.event()
def connect():
    app.client_mgr.connect()



@socket_io.on('connect', namespace="/stats")
def connect():
    app.client_mgr.connect(namespace="/stats")

@socket_io.event
def calibrate(_json):
    app.azel.calibrate()
    return "Azimuth calibration done"


@socket_io.event
def set_map_mh_length(json):
    length = int(json["length"])
    app.client_mgr.set_locator_precision_used_on_map(length)

@socket_io.event
def set_log_scope(json):
    scope = json["scope"]
    app.client_mgr.set_log_scope(scope)


@socket_io.event
def set_az(json):
    print("Pointing at %d" % json["az"])
    app.azel.set_az(json["az"])
    app.client_mgr.send_azel(force=True)

@socket_io.event
def set_az(json):
    print("Pointing at %d" % json["az"])
    app.azel.set_az(json["az"])
    app.client_mgr.send_azel(force=True)

@socket_io.event
def manual(what):
    # print("Manual event %s" % what)
    app.azel.manual(what)

@socket_io.on("get_azel")
def get_azel():
    ret=app.azel.get_azel()
    return ret

@socket_io.event
def add_az(json):
    print("Adjusting az target %d" % json["diff"])
    app.azel.add_az(json["diff"])
    app.client_mgr.send_azel(force=True)


@socket_io.event
def stop(_json):
    app.azel.stop()
    app.client_mgr.status_update()


@socket_io.event
def lookup_locator(qso):
    app.client_mgr.lookup_locator(qso)


@socket_io.event
def untrack(_json):
    app.azel.untrack()
    return "Stopped tracking"


@socket_io.event
def transmit_cw(json):
    speed = json.get("speed", None)
    if speed:
        app.keyer.set_speed(speed)
    repeat = json.get("repeat", 1)
    # keyer.send_message(json["msg"], repeat=repeat)
    while repeat:
        app.keyer.txq.put(json["msg"])
        repeat -= 1
    pass


@socket_io.event
def make_log(json):
    app.ham_op.make_log(json)


@socket_io.event
def band_select(json):
    app.client_mgr.band_select(json)


@socket_io.event
def set_cw_speed(json):
    speed = int(json.get("speed", None))
    app.keyer.set_speed(speed)

def message_received():
    logger.debug('message was received!!!')

@socket_io.on('my event')
def handle_my_custom_event(json):
    logger.debug('received my event: ' + str(json))
    emit('my response', json, callback=message_received)
    app.client_mgr.send_azel(force=True)
    app.station_tracker.refresh()


@socket_io.on("track_wind")
def handle_track_wind(_json):
    app.azel.track_wind()

@socket_io.on("track_moon")
def handle_track_moon(_json):
    app.azel.track_moon()

@socket_io.on("track_sun")
def handle_track_sun(_json):
    app.azel.track_sun()

@socket_io.on("pop_target")
def handle_pop_target(_json):
    #logger.debug("Handle pop_target")
    return app.azel.pop_target()


@socket_io.on("toggle_qro")
def handle_toggle_qro(_json):
    app.ham_op.toggle_qro()


@socket_io.on("toggle_pa")
def handle_toggle_pa(_json):
    app.ham_op.toggle_pa()

@socket_io.on("toggle_tx70")
def handle_toggle_tx70(_json):
    app.ham_op.toggle_tx70()


@socket_io.on("toggle_auto_track")
def handle_toggle_auto_track(_json):
    app.client_mgr.toggle_auto_track()

@socket_io.on("toggle_rx70")
def handle_toggle_rx70(_json):
    app.ham_op.toggle_rx70()


@socket_io.on("toggle_hide_logged_stations")
def handle_toggle_hide_logged_stations(_json):
    app.client_mgr.toggle_hide_logged_stations()

@socket_io.on("toggle_aircraft_layer")
def handle_toggle_aircraft_layer(_json):
    app.client_mgr.toggle_aircraft_layer()

@socket_io.on("toggle_station_layer")
def handle_toggle_station_layer(_json):
    app.client_mgr.toggle_station_layer()

@socket_io.on("toggle_beacon_layer")
def handle_toggle_beacon_layer(_json):
    app.client_mgr.toggle_beacon_layer()
@socket_io.on("track_az")
def handle_track_az(_json):
    logger.debug('received track_az: ' + str(_json))
    app.ham_op.az_track(_json["az"].upper())


@socket_io.event()
def commit_qso(qso):
    new_qso_id = app.ham_op.do_commit_qso(qso)
    qso["id"] = new_qso_id
    emit("qso_committed", qso)
    app.station_tracker.refresh()


@socket_io.event()
def delete_qso(qso):
    app.ham_op.do_delete_qso(qso)
    app.station_tracker.refresh()

@socket_io.on('disconnect')
def test_disconnect():
    logger.info('Client %s disconnected', request.host)



@socket_io.event()
def az_scan_go(json):
    logger.info("Run AZ scan using %s" % json)
    return app.azel.sweep(int(json["start"]), int(json["stop"]), int(json["period"]), int(json["sweeps"]), int(json["increment"]))

@socket_io.event()
def plane_click(plane_id):
    logger.info("Plane click on %s" % plane_id)
    return app.aircraft_tracker.track_plane(plane_id)

@socket_io.event()
def station_click(callsign):
    logger.info("Station click on %s" % callsign)
    emit("fill_dx_grid", callsign, namespace="/", broadcast=True)
    return app.station_tracker.track_station(app.azel, callsign)

@socket_io.event()
def map_settings(settings):
    app.client_mgr.map_settings(settings)

@atexit.register
def goodbye():
    logger.info("Goodbye!!")
    app.azel.az_stop()
    app.azel.GPIO_cleanup()  # clean up GPIO on exit


logger.info("Starting antenna tracker")
app.azel.startup()
logger.info("Starting aircraft tracker")
app.aircraft_tracker.startup()
logger.info("Starting stations tracker")
app.station_tracker.startup()

if __name__ == '__main__':
    try:
        socket_io.run(app, host='0.0.0.0', port=8877, log_output=False, debug=False, use_reloader=False)
    finally:
        app.azel.az_stop()
        pass
