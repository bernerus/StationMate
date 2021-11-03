from flask import session, redirect, url_for, render_template, request
from flask_socketio import *

from main import app

@app.socket_io.on('my event')
def handle_my_custom_event(self, json):
	print('received my event: ' + str(json))
	emit('my response', json, callback=message_received)
	self.send_azel(force=True)