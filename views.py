from flask import render_template
from . import main

@main.app.route('/')
def index():
    return render_template('sm6fbq.html')


@main.app.route("/myqth")
def my_qth():
    rows = main.app.hamop.fetch_my_current_data()
    my_data = {x["key"]: x["value"] for x in rows}
    myqth = my_data["my_locator"]
    return myqth


@main.app.route("/status")
def my_pa(self):
    if self.p27:
        pa_rdy = self.p27.bit_read("PA_READY")
        trx_tx = not self.p27.bit_read("TRX_TX_ACTIVE_L")
        trx_rx = not self.p27.bit_read("TRX_RX_ACTIVE_L")
        pa_active = not self.p27.bit_read("PA_ON_L")
        rx70 = not self.p27.bit_read("RX_432_L")
        tx70 = not self.p27.bit_read("TX_432_L")
        s = ""
        s += "Transceiver is receiving<br/>" if trx_rx else "Transceiver is not receiving.<br/>"
        s += "Transceiver is transmitting<br/>" if trx_tx else "Transceiver is not transmitting.<br/>"
        s += "Power accelerator ready<br/>" if pa_rdy else "Power accelerator is not ready<br/>"
        s += "Power accelerator active<br/>" if pa_active else "Power accelerator is inactive.<br/>"
        s += "RX 70cm active<br/>" if rx70 else "RX 70cm is inactive.<br/>"
        s += "TX 70cm active<br/>" if tx70 else "TX 70cm is inactive.<br/>"
    else:
        s = "Core station info is not available<br/>"

    s += "Antenna is tracking the current wind<br/>" if self.tracking_wind else "Antenna is not tracking the current wind.<br/>"
    s += "Antenna is targeted at azimuth %d degrees<br/>" % self.azel.get_az_target() if self.azel.get_az_target() else "Antenna has no azimuth target<br/>"

    return s
