import queue
from threading import Lock
from p27_defs import *

from flask_socketio import emit
from flask import current_app
from datetime import date

import locator.src.maidenhead as mh

msg_q = queue.Queue()
thread_lock = Lock()

def background_thread(app):
    """Example of how to send server generated events to clients."""
    count = 0
    with app.app_context():
        while True:
            count += 1
            if not msg_q.empty():
                what, item = msg_q.get_nowait()
                # print("Sending %s %d %s" % (what, count, item))
                app.socket_io.emit(what, item, broadcast=True)
            app.socket_io.sleep(0.1)

def status_update_thread(app):
    """Check status and send updates to clients"""
    with app.app_context():
        while True:
            current_status = app.ham_op.get_status()
            app.client_mgr.status_push(current_status)
            app.socket_io.sleep(0.5)

def send_reload():
    msg_q.put(("globalReload", {}))


def send_update(key, clazz, value):
    msg_q.put(("update_class", {"forId": key, "class": clazz, "value": value}))


class ClientMgr:
    def __init__(self, app, socket_io):

        self.app=app
        self.socket_io = socket_io
        self.current_band = "432"

        self.last_p2_sense = None
        self.last_pushed_status = None
        self.last_pushed_azel = (None, None)

        self.message_thread = None
        self.status_thread = None

        self.map_mh_length = 6
        self.mhs_on_map = []
        self.distinct_mhs_on_map = False

        pass

    def get_map_mh_length(self):
        return self.map_mh_length

    def set_map_mh_length(self, length):
        self.map_mh_length = length
        if length < 6:
            self.distinct_mhs_on_map = True
        else:
            self.distinct_mhs_on_map = False

    def add_mhs_on_map(self, mhs):
        distinct = self.distinct_mhs_on_map
        mh_length = self.get_map_mh_length()
        to_send = []
        mhs = [x[0:mh_length] for x in mhs]
        if distinct:
            mhs = set(mhs) - set(self.mhs_on_map)
        for loc in mhs:
            try:
                n, s, w, e, lat, lon = mh.to_rect(loc)
                self.mhs_on_map.append(loc)
                to_send.append({"id": loc, "n": n, "s": s, "w": w, "e": e})
            except (TypeError, ValueError):
                pass

        msg_q.put(("add_rects", to_send))

    def add_mh_on_map(self, loc):
        self.add_mhs_on_map([loc])

    def status_push(self, current, force=False):
        if current != self.last_pushed_status or self.last_pushed_status is None or force:
            if self.app.ham_op.pa_running:
                if current & P27_PA_READY:
                    send_update("pa_ready_led", "active", True)
                    send_update("pa_ready_led", "warming", False)
                else:
                    send_update("pa_ready_led", "warming", True)
                    send_update("pa_ready_led", "active", False)
            else:
                send_update("pa_ready_led", "warming", False)
                send_update("pa_ready_led", "active", False)

            # self.send_update("pa_ready_led", "led-gray", not (current & 0x02))

            send_update("pa_active_led", "active", not (current & P27_PA_ON_L))

            send_update("trx_rx_led", "active", not (current & P27_TRX_RX_ACTIVE_L))
            send_update("trx_tx_led", "active", not (current & P27_TRX_TX_ACTIVE_L))
            self.last_pushed_status = current

        self.app.azel.update_status()

    def push_wind_led(self, tracking_wind):
        send_update("wind_led", "fas", tracking_wind)
        send_update("wind_led", "fa-thin", not tracking_wind)
        self.app.client_mgr.last_tracking_wind = tracking_wind

    def status_update(self, force=False):
        current_p2_sense = self.app.ham_op.get_status()
        self.status_push(current_p2_sense, force=force)

    def send_my_data(self):
        rows = self.app.ham_op.fetch_my_current_data()

        msg = {}
        for row in rows:
            k = row["key"]
            v = row["value"]
            msg[k] = v
        msg["current_band"] = self.current_band
        msg_q.put(("set_mydata", msg))

    def startup(self):
        self.status_update()

    def get_current_band(self):
        return self.current_band

    def send_azel(self, force=None):
        current_azel = self.app.azel.get_azel()
        if current_azel != self.last_pushed_azel or force:
            msg_q.put(("set_azel", {"az": current_azel[0], "el": current_azel[1]}))
        self.last_pushed_azel = current_azel



    def connect(self):
        # Clear the queue

        try:
            while not msg_q.empty():
                msg_q.get_nowait()
        except queue.Empty:
            pass

        self.send_origo()
        self.send_my_data()
        self.send_azel()

        with thread_lock:
            if self.message_thread is None:
                self.message_thread = self.socket_io.start_background_task(background_thread, current_app._get_current_object())
        with thread_lock:
            if self.status_thread is None:
                self.status_thread = self.socket_io.start_background_task(status_update_thread, current_app._get_current_object())

        emit('my_response', {'data': 'Connected', 'count': 0})

        rows = self.app.ham_op.get_log_rows()
        qsos = []
        mhs = []
        self.mhs_on_map = []
        for row in rows:
            qso = {"id": row[0],
                   "date": row[1],
                   "time": row[2],
                   "callsign": row[3],
                   "tx": row[4],
                   "rx": row[5],
                   "locator": row[6],
                   "distance": row[7],
                   "square": row[8],
                   "points": row[9],
                   "complete": row[10],
                   "mode": row[11],
                   "acc_sqn": row[12],
                   "band": row[13],
                   }
            qsos.append(qso)
            if self.app.azel.current_band in row[13]:
                mhs.append(row[6])

        emit("add_qsos", qsos)
        self.add_mhs_on_map(mhs)

        self.status_update(force=True)


    def send_origo(self):
        rows = self.app.ham_op.fetch_my_current_data(self.current_band)
        my_data = {x["key"]: x["value"] for x in rows}
        myqth = my_data["my_locator"]
        n, s, w, e, lat, lon = mh.to_rect(myqth)
        print("Queueing origo %f %f" % (lon, lat))
        msg_q.put(("set_origo", {"lon": lon, "lat": lat, "qth": myqth, "n": n, "s": s, "w": w, "e": e}))


    def send_mydata(self):
        msg = self.app.hamop.get_mydata()
        msg["current_band"] = self.current_band
        msg_q.put(("set_mydata", msg))

    def lookup_locator(self, qso):
        other_loc = qso["locator"]
        qso_date = qso.get("date", date.today().isoformat())
        qso_time = qso.get("time")

        bearing, distance, points, square_no = self.app.ham_op.distance_to(other_loc, qso_date, qso_time)
        qso["bearing"] = bearing
        qso["distance"] = str(int(distance * 10) / 10.0)
        # print(distance);

        qso["square"] = str(square_no)
        qso["points"] = str(points)
        emit("locator_data", qso)

    def band_select(self, json):

        new_band = json.get("band", "144")
        if new_band != self.current_band:
            self.current_band = new_band
            send_reload()

    def emit_log(self, json):
        emit("log_data", json)


def circle(size, user_location):
    c = {  # draw circle on map (user_location as center)
        'stroke_color': '#0000FF',
        'stroke_opacity': .5,
        'stroke_weight': 1,
        # line(stroke) style
        'fill_color': '#FFFFFF',
        'fill_opacity': 0,
        # fill style
        'center': {  # set circle to user_location
            'lat': user_location[0],
            'lng': user_location[1]
        },
        'radius': size
    }
    return c




def message_received():
    print('message was received!!!')


# @socket_io.event
# def connect():
#     client_mgr.connect()



