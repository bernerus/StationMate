from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import MyApp

import queue
from threading import Lock
from p26_defs import *
import re

from flask import current_app
from datetime import date, datetime

import locator.src.maidenhead as mh
from contest_log import get_contest_times

msg_q = queue.Queue()
thread_lock = Lock()

def background_thread(app):
    """Send server generated events to clients."""

    app.client_mgr.logger.info("Starting background thread")
    count = 0
    with app.app_context():
        while True:
                count += 1
                try:
                    if not msg_q.empty():
                        what, item = msg_q.get_nowait()
                        # print("Sending %s %d %s" % (what, count, item))
                        app.socket_io.emit(what, item, broadcast=True)
                except:
                    pass
                app.socket_io.sleep(0.1)


def status_update_thread(app):
    """Check status and send updates to clients"""
    app.client_mgr.logger.info("Starting update thread")
    with app.app_context():
        while True:
            try:
                current_status = app.ham_op.get_status()
                app.client_mgr.status_push(current_status)
            except:
                pass
            app.socket_io.sleep(0.5)




def send_update_class(key, clazz, value):
    # print("Update class forId=%s, class=%s, value=%s" % (key, clazz, value))
    msg_q.put(("update_class", {"forId": key, "class": clazz, "value": value}))

def send_update_classes(key, classes):
    # print("Update classes forId=%s, classes=%s," % (key, classes))
    msg_q.put(("update_classes", {"forId": key, "classes": classes}))


def send_update_state(key, state, value):
    msg_q.put(("update_state", {"forId": key, "state": state, "value": value}))


def emit(what, data):
    msg_q.put((what, data))




def send_reload():
    msg_q.put(("globalReload", {}))

class ClientMgr:
    def __init__(self, app: 'MyApp', logger, socket_io):
        """
        Initializes the class instance with the given parameters.

        :param app: The Flask app object.
        :param logger: The logger object.
        :param socket_io: The SocketIO object.

        """
        self.station_layer = True
        self.aircraft_layer = True
        self.app=app
        self.logger=logger
        self.socket_io = socket_io
        self.current_band = "144-FT8"

        self.last_p2_sense = None
        self.last_pushed_status = None
        self.last_pushed_azel = (None, None)
        self.previous_pushed_azel = (None, None)
        self.last_pushed_log_scope = None
        self.last_pushed_map_mh_length = None

        self.message_thread = None
        self.status_thread = None

        self.map_locator_precision = 6
        self.locators_on_map = []
        self.distinct_locators_on_map = False

        self.show_log_since = None
        self.show_log_until = None
        self.current_log_scope = "Forever"
        self.hiding_logged_stations = False
        self.antenna_freeze:bool = False

        self.auto_track = False

    @staticmethod
    def emit_log(json):
        emit("log_data", json)

    @staticmethod
    def emit(what, data):
        msg_q.put((what, data))
    @staticmethod
    def push_track_led(clazzes):
        send_update_classes("track_led", clazzes)
    @staticmethod
    def disable_core_controls():
        send_update_state("pa_ready_led", "disabled", True)
        send_update_state("pa_active_led", "disabled", True)
        send_update_state("trx_rx_led", "disabled", True)
        send_update_state("trx_tx_led", "disabled", True)
        send_update_state("rx70_led", "disabled", True)
        send_update_state("tx70_led", "disabled", True)
        pass

    @staticmethod
    def enable_core_controls():
        send_update_state("pa_ready_led", "disabled", False)
        send_update_state("pa_active_led", "disabled", False)
        send_update_state("trx_rx_led", "disabled", False)
        send_update_state("trx_tx_led", "disabled", False)
        send_update_state("rx70_led", "disabled", False)
        send_update_state("tx70_led", "disabled", False)
        pass

    def get_locator_precision_used_on_map(self):
        return self.map_locator_precision

    def set_locator_precision_used_on_map(self, length):
        """
        :param length: The desired length for the map MH (map locator precision).
        :return: None

        This method sets the map MH length to the specified value. If the length is different from the current map MH length, it updates the map_locator_precision attribute, emits a log message
        *, updates other attributes and invokes other methods accordingly.

        If the length is less than 6, it sets distinct_locators_on_map to True and emits "setMapZoom" event with zoom level 6. Otherwise, it sets distinct_locators_on_map to False and emits
        * "setMapZoom" event with zoom level 8. It also sends an update message for the "loc_distinct_led" class with the "active" attribute set to the updated distinct_locators_on_map value
        *. Finally, it invokes the update_locator_rects_on_map() method and potentially sends a reload message.

        Example usage:
        set_locator_precision_used_on_map(10)
        """
        if length != self.get_locator_precision_used_on_map():
            self.logger.info("Setting map MH length to %d", length)
            self.map_locator_precision = length
            if length < 6:
                self.distinct_locators_on_map = True
                emit("setMapZoom", 6)
            else:
                self.distinct_locators_on_map = False
                emit("setMapZoom", 8)
            send_update_class("loc_distinct_led", "active", self.distinct_locators_on_map)
            self.update_locator_rects_on_map()
            #send_reload()

    def update_locator_rects_on_map(self):
        locators, _qsqs = self.get_mhs()
        self.push_locator_rects_to_map(locators)

    def set_log_scope(self, scope):
        """
        Set the log scope for logging.

        :param scope: The new log scope.
        :type scope: str
        :return: None
        :rtype: None
        """
        if scope != self.current_log_scope:
            self.current_log_scope = scope
            if scope == "Forever":
                self.show_log_since = None
                self.show_log_until = None
            elif scope == "Today":
                self.show_log_since = datetime.combine(date.today(), datetime.min.time())
                self.show_log_until = None
            elif scope == "Contest":
                _dt, fr, to = get_contest_times(self.current_band)
                self.show_log_since = datetime.strptime(fr, "%Y-%m-%d %H:%M:%S")
                self.show_log_until = datetime.strptime(to, "%Y-%m-%d %H:%M:%S")
            send_reload()


    def push_locator_rects_to_map(self, locators):
        """
        :param locators: A list of locators that need to be pushed to the map.
        :return: None

        This method takes a list of locators and pushes rects outlining them to the map.

        It first retrieves the locator precision used on the map through the method `get_locator_precision_used_on_map()`.
        Then, it processes each locator in the list by truncating it to the retrieved locator precision. If distinct locators are required on the map, it removes any duplicate locators from the list.

        For each remaining locator, it attempts to convert it to a rectangle (rect) using the `mh.to_rect()` method. If the conversion is successful, the locator is added to the list of locators on
        * the map. If the conversion fails, the locator is ignored.

        Next, the method retrieves a list of callsigns associated with the locator using the `callsigns_in_locator()` method from the `ham_op` manager. Based on the length
        * of the locator, the method determines the title and hover_info properties. If the locator length is less than 6, the title is set to "Ruta" and hover_info is set to False. If the locator
        * length is less than 4, the title is set to "Fält".

        The method then builds an info string containing the title and the locator. It constructs an HTML table for displaying the callsigns associated with the locator. The callsigns are divided
        * into columns, with the number of columns determined based on the number of callsigns. Each callsign is appended to the appropriate column in the table.

        Finally, the method constructs a dictionary containing the id, north, south, west, east, info, and hover_info properties for each locator. This dictionary is added to a list called `
        *to_send`. The list of dictionaries is then passed to the `add_rects` method of the `msg_q` object for further processing.
        """
        locator_precision = self.get_locator_precision_used_on_map()
        to_send = []

        locators = [x[0:locator_precision] if x else None for x in locators]
        if self.distinct_locators_on_map:
            locators = set(locators) - set(self.locators_on_map)
        for locator in locators:
            n, s, w, e, lat, long = None, None, None, None, None, None
            try:
                n, s, w, e, lat, lon = mh.to_rect(locator)
                self.locators_on_map.append(locator)
            except (TypeError, ValueError):
                pass

            callsigns = self.app.ham_op.callsigns_in_locator(locator)
            title = "Lokator"
            hover_info=True
            if len(locator) < 6:
                hover_info=False
                title="Ruta"
            if len(locator) < 4:
                title = "Fält"
            info = "%s <b>%s</b>:<br/>" % (title, locator)
            info += "<table id=\"loctable_%s\" class=\"locator_callsigns\">" % locator
            callsign_array = ([],[],[],[])
            callsign_count=0
            callsigns_per_column = int(len(callsigns)/len(callsign_array))+1
            for cs in callsigns:
                column_number = int(callsign_count / callsigns_per_column)
                try:
                    callsign_array[column_number].append(cs)
                except IndexError as e:
                    pass
                callsign_count += 1
            for row in range(max([len(x) for x in callsign_array])):
                info+="<tr>"
                for column_number in callsign_array:
                        try:
                            info +="<td>"+column_number[row]+"</td>"
                        except IndexError:
                            info += "<td/>"
                info += "</tr>"

            info += "</table>"
            to_send.append({"id": locator, "n": n, "s": s, "w": w, "e": e, 'info':info, 'hover_info': hover_info})

        msg_q.put(("add_rects", to_send))

    def add_locator_rect_to_map(self, loc):
        locators, _qsqs = self.get_mhs()
        locators.append(loc)
        self.push_locator_rects_to_map(locators)

    def status_push(self, current, force=False):

        # if not self.app.ham_op.core_controls:
        #     self.disable_core_controls()
        # else:
        #     self.enable_core_controls()
        if current is None:

            # self.logger.info("Status push, force=%s" % force)
            send_update_state("pa_ready_led", "disabled", True)
            send_update_state("trx_rx_led", "disabled", True)
            send_update_state("trx_tx_led", "disabled", True)
            send_update_state("rx70_led", "disabled", True)
            send_update_state("tx70_led", "disabled", True)
            self.last_pushed_status = current
        else:
            if self.last_pushed_status is None:
                self.logger.info("Status push, force=%s" % force)
                send_update_state("trx_rx_led", "disabled", False)
                send_update_state("trx_tx_led", "disabled", False)
                send_update_state("rx70_led", "disabled", False)
                send_update_state("tx70_led", "disabled", False)

            if current and ((current != self.last_pushed_status)  or self.last_pushed_status is None or force):
                # self.logger.debug("Status push, force=%s" % force)
                if current & P26_PA_READY:
                    send_update_class("pa_ready_led", "active", True)
                    send_update_class("pa_ready_led", "warming", False)
                else:
                    if current & P26_PA_PWR_ON_L:
                        send_update_class("pa_ready_led", "warming", False)
                        send_update_class("pa_ready_led", "active", False)
                    else:
                        send_update_class("pa_ready_led", "warming", True)
                        send_update_class("pa_ready_led", "active", False)

                # self.send_update_class("pa_ready_led", "led-gray", not (current & 0x02))

                send_update_class("pa_active_led", "active", not (current & P26_PA_QRO_ACTIVE))

                send_update_class("trx_rx_led", "active", not (current & P26_TRX_RX_ACTIVE_L))
                send_update_class("trx_tx_led", "active", not (current & P26_TRX_TX_ACTIVE_L))

                send_update_class("rx70_led", "active", not (current & P26_RX_432_L))
                send_update_class("tx70_led", "active", not (current & P26_TX_432_L))

                if not (current & P26_TRX_RX_ACTIVE_L) or not (current & P26_TRX_TX_ACTIVE_L):
                    send_update_state("pa_ready_led", "disabled", False)
                    #if not current & P26_PA_READY:
                        #send_update_state("pa_ready_led", "disabled", True)
                self.last_pushed_status = current

            if self.current_log_scope != self.last_pushed_log_scope or force:
                send_update_class("log_scope_forever", "active", self.current_log_scope == "Forever")
                send_update_class("log_scope_today", "active", self.current_log_scope == "Today")
                send_update_class("log_scope_contest", "active", self.current_log_scope == "Contest")
                self.last_pushed_log_scope = self.current_log_scope

            if self.map_locator_precision != self.last_pushed_map_mh_length or force:
                send_update_class("loc_fields", "active", self.map_locator_precision == 2)
                send_update_class("loc_squares", "active", self.map_locator_precision == 4)
                send_update_class("loc_locators", "active", self.map_locator_precision >= 6)
                self.last_pushed_map_mh_length = self.map_locator_precision


        self.app.azel.status_update()

    def status_update(self, force=False):
        current_p2_sense = self.app.ham_op.get_status()
        self.status_push(current_p2_sense, force=force)
        send_update_class("auto_track_button", "active", self.auto_track)
        send_update_class("antenna_freeze_button", "active", self.antenna_freeze)
        send_update_class("show_hide_stations", "active", not self.station_layer)
        send_update_class("show_hide_logged_stations", "active", self.hiding_logged_stations)
        # emit("hiding_logged_stations", self.hiding_logged_stations)
        send_update_class("show_hide_aircraft", "active", not self.aircraft_layer)

    def send_my_data(self):
        rows = self.app.ham_op.fetch_my_current_data(self.current_band)

        msg = {x["key"]: x["value"] for x in rows}
        msg["current_band"] = self.current_band
        msg_q.put(("set_mydata", msg))

    def startup(self):
        self.status_update(force=True)

    def get_current_band(self):
        return self.current_band


    def send_azel(self, azel=None, force=None):
        if azel is None:
            azel = self.app.azel.get_azel()

        if azel != self.last_pushed_azel and azel != self.previous_pushed_azel or force:
            msg_q.put(("set_azel", {"az": azel[0], "el": azel[1]}))
        self.previous_pushed_azel = self.last_pushed_azel # Eliminate flapping
        self.last_pushed_azel = azel



    def connect(self, namespace="/"):
        """
        Connects to the given namespace.

        :param namespace: The namespace to connect to.
        :return: None
        """
        # Clear the queue

        if namespace=="/":
            try:
                while not msg_q.empty():
                    msg_q.get_nowait()
            except queue.Empty:
                pass

            self.send_origo()
            self.send_qth()
            self.send_my_data()
            self.send_azel(force=True)

            with thread_lock:
                if self.message_thread is None:
                    self.message_thread = self.socket_io.start_background_task(background_thread, current_app._get_current_object())
            with thread_lock:
                if self.status_thread is None:
                    self.status_thread = self.socket_io.start_background_task(status_update_thread, current_app._get_current_object())

            self.app.aircraft_tracker.startup()

            emit('my_response', {'data': 'Connected', 'count': 0})

            mhs, qsos = self.get_mhs()
            if qsos:
                emit("add_qsos", qsos)
                self.logger.debug("Adding %d qso:s from %s to %s" % (len(qsos), qsos[0]["callsign"], qsos[-1]["callsign"]))
            self.push_locator_rects_to_map(mhs)
            self.app.azel.target_stack.update_ui(force=True)
            self.status_update(force=True)

        else:
            self.app.socket_io.emit('my_response', {'data': 'Connected', 'count': 0}, namespace=namespace)

        # self.update_planes()
        # stations =self.app.ham_op.get_reachable_stations()
        # self.update_reachable_stations(stations)

    def get_mhs(self):
        rows = self.app.ham_op.get_log_rows(self.show_log_since, self.show_log_until)
        qsos = []
        mhs = []
        self.locators_on_map = []
        mhsqnumber = 0
        mhsqs = set()
        for row in rows:
            newmsqn = None
            if row[6]:
                mhsq = row[6][:4].upper()
                if mhsq not in mhsqs and row[13].startswith(re.split("[-.]", self.current_band)[0]) and row[10]:
                    newmsqn = len(mhsqs) + 1
                    mhsqs.add(mhsq)

            qso = {"id": row[0],
                   "date": row[1],
                   "time": row[2],
                   "callsign": row[3].upper(),
                   "tx": row[4],
                   "rx": row[5],
                   "locator": row[14].upper() if row[14] else row[6].upper() if row[6] else None,
                   "distance": row[7],
                   "square": row[8],
                   "points": row[9],
                   "complete": row[10],
                   "propmode": row[11],
                   "acc_sqn": newmsqn,
                   "band": row[13],
                   }
            qsos.append(qso)
            if row[6]:
                if row[13].startswith(re.split("[-.]", self.current_band)[0]) and (row[6] or row[14]):
                    mhs.append(row[14].upper() if row[14] and row[6] and len(row[14]) > len(row[6]) else row[6].upper())
        return mhs, qsos

    def update_map_center(self):
        settings = self.app.ham_op.get_map_setting(self.current_band, self.map_locator_precision, self.current_log_scope)
        #print("Settings=",settings)
        if settings:
            lon, lat, zoom = settings
            #print("Queueing origo %f %f, zoom=%d" % (lon, lat, zoom))
            msg_q.put(("set_origo", {"lon": lon, "lat": lat, "zoom": zoom}))


    def send_origo(self):
        rows = self.app.ham_op.fetch_my_current_data(self.current_band)
        my_data = {x["key"]: x["value"] for x in rows}
        myqth = my_data["my_locator"]
        n, s, w, e, lat, lon = mh.to_rect(myqth)
        zoom=8

        settings = self.app.ham_op.get_map_setting(self.current_band, self.map_locator_precision, self.current_log_scope)
        if settings:
            lon, lat, zoom = settings

        #print("Queueing origo %f %f, zoom=%d" % (lon, lat, zoom))
        msg_q.put(("set_origo", {"lon": lon, "lat": lat, "zoom": zoom}))


    def send_qth(self):
        rows = self.app.ham_op.fetch_my_current_data(self.current_band)
        my_data = {x["key"]: x["value"] for x in rows}
        my_qth = my_data["my_locator"]
        n, s, w, e, lat, lon = mh.to_rect(my_qth)

        #print("Queueing qth %f %f" % (lon, lat))
        msg_q.put(("set_qth", {"lon": lon, "lat": lat, "qth": my_qth, "n": n, "s": s, "w": w, "e": e}))


    def send_mydata(self):
        msg = self.app.ham_op.get_mydata(self.current_band)
        msg["current_band"] = self.current_band
        msg_q.put(("set_mydata", msg))

    def do_lookup_locator(self, qso):
        other_loc = qso["locator"]
        qso_date = qso.get("date", date.today().isoformat())
        qso_time = qso.get("time")

        bearing, distance, points, square_no = self.app.ham_op.distance_to(other_loc, qso_date, qso_time)
        qso["bearing"] = bearing
        qso["distance"] = str(int(distance * 10) / 10.0)
        # print(distance);

        qso["square"] = str(square_no)
        qso["points"] = str(points)

        return qso


    def band_select(self, json):

        new_band = json.get("band", "144")
        if new_band != self.current_band:
            self.current_band = new_band
            self.app.station_tracker.set_band(new_band)
            send_reload()

    def add_qso(self, qso):
        self.logger.info("Adding QSO with %s" % qso["callsign"])
        emit("add_qso", qso)
        # emit("qso_committed", qso)

    def send_reload(self):
        msg_q.put(("globalReload", {}))

    @staticmethod
    def update_target_list(targets):
        s = "<table id=\"targets\"><tr><th>Id</th><th>Active</th><th>Az/El</th><th>Period</th><th>TTL</th><th>Left</th><th>Note 1</th><th>Note 2</th></tr>"
        th_count = s.count("<th>")
        if targets is None:
            return
        for t in targets:
            ts = "<tr>"
            tsr = t.get_html_row()
            ct = tsr.count("<td>")
            while ct < th_count:
                tsr = tsr + "<td></td>"
                ct += 1
            s += ts + tsr + "</tr>"
        s += "</table>"
        msg_q.put(("update_target_list", s))

    @staticmethod
    def update_planes(planes):

        planes1 = {
            "3520": {"id": "TAY4537", "lat":57.6465, "lng": 13.0829, "alt":36000},
            "4540": {"id": "WZZ9SJ", "lat":57.6236, "lng": 13.4089, "alt": 34263},
        }

        planes2 = {
            "3520": {"id": "TAY4537", "lat": 57.7465, "lng": 13.2829, "alt": 36000},
            "4540": {"id": "WZZ9SJ", "lat": 57.6036, "lng": 13.3089, "alt": 34263},
        }
        if planes is not None:
            msg_q.put(("update_planes", planes))
            return

        msg_q.put(("update_planes", planes1))

        msg_q.put(("update_planes", planes2))

    def update_reachable_stations(self, beaming, other):
        """
        :param beaming: A dictionary of stations that are beaming towards the user's location. Each key-value pair in the dictionary represents a unique station, where the key is the station
        *'s unique identifier and the value is a dictionary containing station information.
        :param other: A dictionary of other stations that are not beaming towards the user's location. Each key-value pair in the dictionary represents a unique station, where the key is the
        * station's unique identifier and the value is a dictionary containing station information.
        :return: None

        This method updates the list of reachable stations based on the provided dictionaries of beaming and other stations. It uses the provided information to create a JSON object representing
        * each station and stores them in a dictionary. The resulting dictionary is then sent to a message queue for further processing and communication with the client application.
        """
        json={}

        worked_callsigns = set()
        if self.hiding_logged_stations:
            rows = self.app.ham_op.get_log_rows(self.show_log_since, self.show_log_until)
            for row in rows:
                cs = row[3].upper()
                worked_callsigns.add(cs)

        for s in beaming:
            station = beaming[s]
            callsign = station['callsign'].upper()
            if callsign in worked_callsigns:
                continue
            locator = station.get('locator','').upper()
            antaz = station.get('az', 0)
            dist = station.get('dist', 0)
            age = float(station.get('age_minutes', 0))
            myaz = station.get('my_az', 0)
            dx_callsign = station.get("dx_callsign", '')
            dx_loc=station.get("dx_loc", '')
            freq = station["frequency"]
            txmode = station["txmode"]
            antwidth=30

            info = f"""<span style=\"font-size:12pt\"> 
                        <b>{callsign}:</b><br/>
                        Locator:{locator}<br/>
                        QTF:{antaz}<br/>
                        Last report {age:2.1f} min ago with {dx_callsign}@{dx_loc}<br/>
                        Distance:{dist} km<br/>
                        QRG: {freq}, "txmode: {txmode}</span>
                    """
            try:
                txmode = station['txmode']
            except IndexError:
                txmode = "FT8"
            #antwidth = station["antwidth"] if "antwidth" in station else 30
            _n, _s, _w, _e, latitude, longitude = mh.to_rect(locator)
            if dist > 10:
                json[callsign] = {"callsign":callsign, "locator": locator, "position": {"lat": latitude, "lng": longitude}, "antenna_azimuth": antaz, "antenna_width": antwidth, "my_az":myaz, "txmode": txmode, "age": age, "distance": dist, "info":info}
        for s in other:
            station = other[s]
            callsign = station['callsign'].upper()
            if callsign in json or callsign in worked_callsigns:
                continue
            locator = station['locator'].upper()
            antaz = station.get('az', 0)
            dist = station.get('dist', 0)
            age = float(station.get('age_minutes',0))
            myaz = station.get('my_az',0)
            dx_callsign = station.get("dx_callsign",'')
            dx_loc=station.get("dx_loc",'')
            freq = station["frequency"]
            txmode = station["txmode"]
            antwidth = 360
            info = f"""<span style=\"font-size:12pt\"> 
                                    <b>{callsign}:</b><br/>
                                    Locator:{locator}<br/>
                                    QTF:{antaz}<br/>
                                    Last report {age:2.1f} min ago with {dx_callsign}@{dx_loc}<br/>
                                    Distance:{dist} km<br/>
                                    QRG: {freq}, "txmode: {txmode}</span>
                                """
            try:
                txmode = station['txmode']
            except IndexError:
                txmode = "FT8"
            _n, _s, _w, _e, latitude, longitude = mh.to_rect(locator)
            json[callsign] = {"callsign": callsign, "locator": locator, "position": {"lat": latitude, "lng": longitude}, "antenna_azimuth": antaz, "antenna_width": antwidth, "my_az": myaz, "txmode": txmode,"age": age,"distance":dist, "info": info}
        #import pprint
        #pprint.pprint(json)
        # self.logger.info("Pushing %d stations to client" % (len(json)))
        msg_q.put(("update_reachable_stations", json))

    def map_settings(self, json):
        self.logger.debug("Map settings received: %s", json)
        self.app.ham_op.store_map_setting(json, self.current_band, self.map_locator_precision, self.current_log_scope)

    def toggle_distinct(self):
        self.distinct_locators_on_map = not self.distinct_locators_on_map
        send_update_class("loc_distinct_led", "active", self.distinct_locators_on_map)
        self.update_locator_rects_on_map()

    def toggle_hide_logged_stations(self):
        self.hiding_logged_stations = not self.hiding_logged_stations
        # emit("hiding_logged_stations", self.hiding_logged_stations)
        self.app.station_tracker.refresh()
        self.status_update(force=True)

    def toggle_aircraft_layer(self):
        self.aircraft_layer = not self.aircraft_layer
        emit("aircraft_layer", self.aircraft_layer)
        if self.aircraft_layer:
            self.app.aircraft_tracker.startup()
        else:
            self.app.aircraft_tracker.shutdown()
        self.status_update(force=True)

    def toggle_station_layer(self):
        self.station_layer = not self.station_layer
        emit("station_layer", self.station_layer)
        if self.station_layer:
            self.app.station_tracker.startup()
        else:
            self.app.station_tracker.shutdown()

        self.status_update(force=True)

    def toggle_auto_track(self):
        self.auto_track = not self.auto_track
        # emit("Auto track", self.auto_track)
        send_update_class("auto_track_button", "active", self.auto_track)
        self.status_update(force=True)

    def toggle_antenna_freeze(self):
        self.antenna_freeze = not self.antenna_freeze
        if self.antenna_freeze:
            self.app.azel.disable_control()
        else:
            self.app.azel.enable_control()
        send_update_class("antenna_freeze_button", "active", self.antenna_freeze)
        self.status_update(force=True)

    def set_dx_call(self, callsign, locator):
        knowns = self.app.ham_op.callsigns_in_locator(locator)
        if callsign in knowns:
            emit("fill_dx_grid", callsign)
            if self.auto_track:
                self.app.azel.az_track_station(callsign, auto=True)
        else:
            emit("fill_dx_grid", locator)
            if self.auto_track:
                self.app.azel.az_track_loc(locator, auto=True)



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



