
from flask import Flask, render_template, request
import psycopg2
from config import DevelopmentConfig
from flask_socketio import SocketIO, emit
from morsetx import *
import threading
import atexit


socket_io = SocketIO(async_mode="eventlet")

def create_app(config=DevelopmentConfig):
    _app = Flask(__name__)
    _app.config.from_object(config)

    with open("etc/google_api.txt") as f:
        api_key = f.readline()
    _app.config['GOOGLEMAPS_API_KEY'] = api_key


    socket_io.init_app(_app)
    return _app

app = create_app()
app.socket_io = socket_io

_db = psycopg2.connect(dbname='ham_station')

from hamop import HamOp
app.ham_op = HamOp(app, _db)

from clientmgr import ClientMgr
app.client_mgr = ClientMgr(app, socket_io)

from azel import AzElControl
app.azel = AzElControl(app, socket_io, hysteresis=2)
app.azel.startup()

app.keyer = Morser(speed=None, p20=app.azel.p20)
app.keyer_thread = threading.Thread(target=app.keyer.background_thread, args=())
app.keyer_thread.daemon = True  # Daemonize keyer_thread
app.keyer_thread.start()

# class ShowMap(View):
#     def dispatch_request(self):
#         return render_template('sm6fbq.html')

@app.route('/')
def index():
    return render_template('sm6fbq.html',  async_mode=socket_io.async_mode)

@app.route('/az')
def get_azimuth():
    return "Az=%d ticks" % app.azel.az


@app.route("/myqth")
def my_qth():
    return app.ham_op.my_qth()



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


##############

@socket_io.event
def connect():
    app.client_mgr.connect()

@socket_io.event
def calibrate(_json):
    app.azel.calibrate()
    return "Azimuth calibration done"


@socket_io.event
def set_map_mh_length(json):
    length = int(json["length"])
    app.client_mgr.set_map_mh_length(length)

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
    print('message was received!!!')

@socket_io.on('my event')
def handle_my_custom_event(json):
    print('received my event: ' + str(json))
    emit('my response', json, callback=message_received)
    app.client_mgr.send_azel(force=True)


@socket_io.on("track wind")
def handle_track_wind(_json):
    app.azel.track_wind()


@socket_io.on("toggle_qro")
def handle_toggle_qro(_json):
    app.ham_op.toggle_qro()



@socket_io.on("toggle_pa")
def handle_toggle_pa(_json):
    app.ham_op.toggle_pa()


@socket_io.on("track az")
def handle_track_az(json):
    app.azel.untrack_wind()

    # print('received track_az: ' + str(json))
    # emit('my response', json, callback=messageReceived)

    try:
        az_value = int(json["az"])
        app.azel.az_track(az_value)
        return
    except ValueError:
        pass

    app.ham_op.az_track(json["az"])


@socket_io.event()
def commit_qso(qso):
    new_qso_id = app.ham_op.do_commit_qso(qso)
    qso["id"] = new_qso_id
    emit("qso_committed", qso)


@socket_io.event()
def delete_qso(qso):
    app.ham_op.do_delete_qso(qso)

@socket_io.on('disconnect')
def test_disconnect():
    print('Client disconnected', request.host)

@socket_io.event()
def map_settings(settings):
    app.client_mgr.map_settings(settings)

@atexit.register
def goodbye():
    print("Goodbye!!")
    app.azel.az_stop()
    app.azel.GPIO_cleanup()  # clean up GPIO on exit



if __name__ == '__main__':
    try:
        socket_io.run(app, host='0.0.0.0', port=8877, log_output=False, debug=False)
    finally:
        app.azel.az_stop()
        pass
