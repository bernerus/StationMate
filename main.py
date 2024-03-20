
import os, signal
import sys
import argparse
import RPi.GPIO as GPIO
# noinspection PyUnresolvedReferences
import time


def kill_siblings():

    # Ask user for the name of process
    name = "CoreStationCtrl/main.py"
    try:

        # iterating through each instance of the process
        for line in os.popen("ps -ef | grep " + name + " | grep -v grep"):
            fields = line.split()

            # extracting Process ID from the output
            pid = fields[1]
            _ppid = fields[2]
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
                except Exception as ex:
                    print ("Process %s is now dead: %s" % (int(pid), ex))
                    break

    except Exception as ex:
        print("Error %s Encountered while running script"%ex)


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
    print("Another instance of CoreSatationCtrlr is running. Quitting: %s" % e)
    sys.exit(1)


from flask import Flask, render_template, request
from config import DevelopmentConfig
from flask_socketio import SocketIO, emit
from flask_socketio.namespace import Namespace
# from morsetx import *
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

logger.info("Starting Core Station controller")


socket_io = SocketIO(async_mode='eventlet', logger=False, engineio_logger=False, ping_timeout=60, ping_interval=4)


class MyApp(Flask):
    def __init__(self, import_name, **kwargs):

        super().__init__(import_name, **kwargs)

        self.config.from_object(DevelopmentConfig)

        # with open("etc/google_api.txt") as f:
        #     api_key = f.readline()
        # self.config['GOOGLEMAPS_API_KEY'] = api_key

        socket_io.init_app(self)

        self.socket_io = socket_io

        # self._db = psycopg2.connect(dbname='ham_station')

        from hamop import HamOp
        self.ham_op = HamOp(self, logger)

        from clientmgr import ClientMgr
        self.client_mgr = ClientMgr(self, logger, socket_io)

        # from azel import AzelController
        # self.azel = AzelController(self, logger, socket_io, hysteresis=14)
        #
        # from aircraft_tracker import AircraftTracker
        # self.aircraft_tracker = AircraftTracker(self, logger, socket_io, url="http://192.168.1.129:8754")
        #
        # from station_tracker import StationTracker
        # self.station_tracker = StationTracker(self, logger, socket_io)

        # rows = self.ham_op.fetch_my_current_data("144")
        # self.my_data = {x["key"]: x["value"] for x in rows}
        #
        # self.keyer = Morser(logger, speed=None, p20=self.azel.p20)
        # self.keyer_thread = threading.Thread(target=self.keyer.background_thread, args=())
        # self.keyer_thread.daemon = True  # Daemonize keyer_thread
        # self.keyer_thread.start()

app=MyApp(__name__)
class WsjtxNamespace(Namespace):
    """

    :class:`WsjtxNamespace` is a class that extends the `Namespace` class from the `SocketIO` library. It handles events related to WSJT-X
    message exchanger py-wsjtx.

    Methods:
        - `on_connect()`:
            - This method is called when the WSJT-X message exchanger connects.
            - It logs a message that the exchanger has connected.
            - then emits a `server_response` event with data `{'data': 'Connected', 'count': 0}`.

        - `on_disconnect()`:
            - This method is called when yhr WSJT-X message exchanger disconnects.
            - It logs a message that the exchanger has disconnected.

        - `on_my_event(sid, data)`:
            - This method is called when a custom event `my_event` is triggered.
            - It emits a `my_response` event with the given data.

        - `on_set_dx_note(json)`:
            - This method is called when a `set_dx_note` event is triggered with some JSON data.
            - It logs a message that the DX note is being filled with the given JSON data.
            - It retrieves the callsign and locator from the JSON data and sets them using the `set_dx_call` method from the `app.client_mgr`.
            - It emits a `fill_dx_note` event with the JSON data, broadcasting it to all clients.

        - `on_set_dx_grid(grid)`:
            - Emits a `fill_dx_grid` event with the `grid`, broadcasting it to all clients.

        - `on_set_trx70(json)`:
            - This method is called when a `set_trx70` event is triggered with some JSON data.
            - It logs a message that the TRX70 is being set.
            - It sets the TRX70 using the `set_trx70` method from the `app.ham_op`.

        - `on_commit_wsjtx_qso(json)`:
            - This method is called when a `commit_wsjtx_qso` event is triggered with some JSON data.
            - It retrieves the necessary fields from the JSON data and creates a `qso` dictionary with the following keys:
                - `callsign`: The DX call from the JSON data.
                - `band`: The dial frequency divided by 1,000,000.
                - `txmode`: The transmit mode from the JSON data.
                - `tx`: The report sent from the JSON data.
                - `rx`: The report received from the JSON data.
                - `locator`: The DX grid from the JSON data.
                - `frequency`: The dial frequency divided by 1,000,000.
                - `date`: The date from the `date_time_on` field of the JSON data.
                - `time`: The time from the `date_time_on` field of the JSON data.
                - `complete`: True.
                - `propmode`: The propagation mode from the JSON data.
            - If the `dx_call` and `dx_grid` are provided, it looks up any known full locator using the `lookup_locator` method from the `app.ham_op` and adds it to the `qso` dictionary
    * as `augmented_locator`.
            - It calculates the bearing, distance, contest points, and square count using the `distance_to` method from the `app.ham_op` and adds them to the `qso` dictionary.
            - It logs a message that the QSO from WSJT-X is being committed with the `qso` dictionary.
            - It commits the QSO using the `do_commit_qso` method from the `app.ham_op` and retrieves the new QSO ID.
            - It adds the QSO ID to the `qso` dictionary.
            - It emits a `commit_qso` event with the `qso` dictionary, broadcasting it to all clients.

    Note: Please refer to the relevant code implementation for further details on the methods and their usage.
    """
    @staticmethod
    def on_connect():
        logger.info("WSJTX exchanger connected")
        emit('server_response', {'data': 'Connected', 'count': 0})
    @staticmethod
    def on_disconnect():
        logger.info("WSJTX exchanger disconnected")
        pass

    # @staticmethod
    # def on_my_event(sid, data):
    #     emit('my_response', (sid,data))

    # @staticmethod
    # def on_set_dx_note(json):
    #     logger.info("Fill DX note %s" % json)
    #     callsign = json["callsign"]
    #     locator = json["locator"]
    #     app.client_mgr.set_dx_call(callsign, locator)
    #     emit("fill_dx_note", json, namespace="/", broadcast=True)

    # @staticmethod
    # def on_set_dx_grid(grid):
    #     logger.info("Set DX grid to %s" % grid)
    #     emit("fill_dx_grid", grid, namespace="/", broadcast=True)

    @staticmethod
    def on_set_trx70(json):
        logger.info("Set TRX70")
        app.ham_op.set_trx70(json)

    # @staticmethod
    # def on_commit_wsjtx_qso(json):
    #     dt = json["date_time_on"]  # type: str
    #     fq = int(json["dial_frequency"])
    #     qso = {
    #         "callsign": json["dx_call"],
    #         "band": "%f" % (fq / 1000000),
    #         "txmode": json["txmode"],
    #         "tx": json["report_sent"],
    #         "rx": json["report_received"],
    #         "locator": json["dx_grid"],
    #         "frequency": "%f" % (fq / 1000000),
    #         "date": dt[:10],
    #         "time": dt[11:13] + dt[14:16],
    #         "complete": True,
    #         "propmode": json["propmode"]
    #     }



        # If given only the square, look up any known full locator if previously known
        # found_loc = app.ham_op.lookup_locator(json["dx_call"], json["dx_grid"])
        # if found_loc:
        #     qso["augmented_locator"] = found_loc
        #
        # bearing, distance, points, square_count = app.ham_op.distance_to(qso["locator"], qso["date"], qso["time"])
        # qso["distance"] = "%4.1f" % distance
        # qso["points"] = points

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

        # logger.info("Commit QSO from WSJT-X %s", qso)
        # new_qso_id = app.ham_op.do_commit_qso(qso)
        # qso["id"] = new_qso_id
        # app.client_mgr.add_qso(qso)  # do_commit_qso does this.

socket_io.on_namespace(WsjtxNamespace('/wsjtx'))

# @app.route('/')
# def index():
#     with open("etc/g16e.txt") as f:
#         key=f.readline()
#     return render_template('sm6fbq.html',  gapikey=key, async_mode=socket_io.async_mode)
#
# @app.route('/az')
# def get_azimuth():
#     return "Az=%d ticks" % app.azel.az

@app.route("/help")
def cmd_help():
    help_text = """
        <table>
        <tr><td>/</td><td>Start server</td></tr>
        <tr><td>/help</td><td>See this help text</td></tr>
        <tr><td>/status</td><td>Return rig status</td></tr>
        <tr><td>/paon</td><td>Turn on the power supply to the transmitter power amplifiers</td></tr>
        <tr><td>/paoff</td><td>Turn off the power supply to the transmitter power amplifiers</td></tr>
        <tr><td>/qroon</td><td>Enable high power transmission</td></tr>
        <tr><td>/qrooff</td><td>Disable high power transmission</td></tr>
        <tr><td>/rx70</td><td>Configure core station for 70cm reception (Just causes RX disconnect from the antenna)</td></tr>
        <tr><td>/tx70</td><td>Configure core station for 70cm transmission.</td></tr>
        <tr><td>/rx2</td><td>Opposite of rx70</td></tr>
        <tr><td>/tx2</td><td>Opposite of tx70</td></tr>
        """
    return help_text


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

@socket_io.event()
def connect():
    app.client_mgr.connect()

@socket_io.on('connect', namespace="/stats")
def connect():
    app.client_mgr.connect(namespace="/stats")


@socket_io.event
def band_select(json):
    app.client_mgr.band_select(json)

def message_received():
    logger.debug('message was received!!!')

@socket_io.on("toggle_qro")
def handle_toggle_qro(_json):
    app.ham_op.toggle_qro()


@socket_io.on("toggle_pa")
def handle_toggle_pa(_json):
    app.ham_op.toggle_pa()

@socket_io.on("toggle_tx70")
def handle_toggle_tx70(_json):
    app.ham_op.toggle_tx70()

@socket_io.on("toggle_rx70")
def handle_toggle_rx70(_json):
    app.ham_op.toggle_rx70()

@socket_io.on('disconnect')
def test_disconnect():
    logger.info('Client %s disconnected', request.host)

@atexit.register
def goodbye():
    logger.info("Goodbye!!")
    #app.azel.az_stop()
    GPIO.cleanup()

#logger.info("Starting antenna tracker")
# app.azel.startup()
#logger.info("Starting aircraft tracker")
# app.aircraft_tracker.startup()
#logger.info("Starting stations tracker")
# app.station_tracker.startup()

if __name__ == '__main__':
    try:
        socket_io.run(app, host='0.0.0.0', port=8877, log_output=False, debug=False, use_reloader=False)
    finally:
        app.azel.az_stop()
        pass
