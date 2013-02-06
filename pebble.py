#!/usr/bin/env python

import serial, codecs, sys, binascii, time, threading
from pprint import pprint
from struct import *

class EndpointSync():
    timeout = 10

    def __init__(self, pebble, endpoint):
		pebble.register_endpoint(endpoint, self.callback)
		self.marker = threading.Event()

    def callback(self, *args):
        self.data = args
        self.marker.set()

    def get_data(self):
        try:
            self.marker.wait(timeout=self.timeout)
            return self.data[1]
        except:
            return False

class Pebble(object):
	endpoints = {
		"TIME": 11,
		"VERSION": 16,
		"MUSIC_CONTROL": 32,
		"PING": 2001,
		"NOTIFICATION": 3000,
		"RESOURCE": 4000,
		"APP_MANAGER": 6000
	}

	def __init__(self, id):
		self._alive = True
		self._endpoint_handlers = {}
		self._internal_endpoint_handlers = {
			self.endpoints["TIME"]: self._get_time_response,
			self.endpoints["VERSION"]: self._version_response,
			self.endpoints["APP_MANAGER"]: self._appbank_status_response
		}

		try:
			self._ser = serial.Serial("/dev/tty.Pebble"+id+"-SerialPortSe", 19200, timeout=1)
			# we get a null response when we connect, discard it
			self._ser.read(5)

			self._read_thread = threading.Thread(target=self._reader)
			self._read_thread.setDaemon(True)
			self._read_thread.start()
		except:
			raise Exception("Failed to connect to Pebble")

	def __del__(self):
		try:
			self._ser.close()
		except:
			pass

	def _reader(self):
		while self._alive:
			endpoint, resp = self._recv_message()
			if resp == None:
				continue

			if endpoint in self._internal_endpoint_handlers:
				resp = self._internal_endpoint_handlers[endpoint](endpoint, resp)

			if endpoint in self._endpoint_handlers:
				self._endpoint_handlers[endpoint](endpoint, resp)

	def _build_message(self, endpoint, data):
		return pack("!hh", len(data), endpoint)+data

	def _send_message(self, endpoint, data, callback = None):
		if endpoint not in self.endpoints:
			raise Exception("Invalid endpoint specified")

		msg = self._build_message(self.endpoints[endpoint], data)
		self._ser.write(msg)

	def _recv_message(self):
		data = self._ser.read(4)
		if len(data) == 0:
			return (None, None)
		elif len(data) < 4:
			raise Exception("Malformed response with length "+str(len(data)))
		size, endpoint = unpack("!hh", data)
		resp = self._ser.read(size)
		return (endpoint, resp)

	def register_endpoint(self, endpoint_name, func):
		if endpoint_name not in self.endpoints:
			raise Exception("Invalid endpoint specified")
		
		endpoint = self.endpoints[endpoint_name]
		self._endpoint_handlers[endpoint] = func

	def notification_sms(self, sender, body):
		ts = str(int(time.time())*1000)
		parts = [sender, body, ts]
		data = "\x01"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message("NOTIFICATION", data)

	def notification_email(self, sender, subject, body):
		ts = str(int(time.time())*1000)
		parts = [sender, subject, ts, body]
		data = "\x00"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message("NOTIFICATION", data)	

	def set_nowplaying_metadata(self, track, album, artist):
		ts = str(int(time.time())*1000)
		parts = [artist, album, track]
		data = pack("!b", 16)
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message("MUSIC_CONTROL", data)

	def get_versions(self, async = False):
		self._send_message("VERSION", "\x00")

		if not async:
			return EndpointSync(self, "VERSION").get_data()

	def get_appbank_status(self, async = False):
		self._send_message("APP_MANAGER", "\x01")

		if not async:
			return EndpointSync(self, "APP_MANAGER").get_data()

	def remove_app(self, appid, index):
		data = pack("!bII", 2, appid, index)
		self._send_message("APP_MANAGER", data)

	def get_time(self, async = False):
		self._send_message("TIME", "\x00")

		if not async:
			return EndpointSync(self, "TIME").get_data()

	def set_time(self, timestamp):
		data = pack("!bL", 2, timestamp)
		self._send_message("TIME", data)

	def ping(self, cookie = 0):
		data = pack("!bL", 0, cookie)
		self._send_message("PING", data)
		endpoint, resp = self._recv_message()
		restype, retcookie = unpack("!bL", resp)
		return cookie == retcookie

	def reset(self):
		self._send_message("RESET", "\x00")

	def disconnect(self):
		self._alive = False
		self._ser.close()

	def _get_time_response(self, endpoint, data):
		restype, timestamp = unpack("!bL", data)
		return timestamp

	def _appbank_status_response(self, endpoint, data):
		apps = {}
		restype, apps["banks"], apps_installed = unpack("!bII", data[:9])
		apps["apps"] = []

		appinfo_size = 78
		offset = 9
		for i in xrange(apps_installed):
			app = {}
			app["id"], app["index"], app["name"], app["company"], app["flags"], app["version"] = \
				unpack("!II32s32sIH", data[offset:offset+appinfo_size])
			app["name"] = app["name"].replace("\x00", "")
			app["company"] = app["company"].replace("\x00", "")
			apps["apps"] += [app]
			offset += appinfo_size

		return apps

	def _version_response(self, endpoint, data):
		fw_names = {
			0: "normal_fw",
			1: "recovery_fw"
		}

		resp = {}
		for i in xrange(2):
			fwver_size = 47
			offset = i*fwver_size+1
			fw = {}
			fw["timestamp"],fw["version"],fw["commit"],fw["is_recovery"], \
				fw["hardware_platform"],fw["metadata_ver"] = \
				unpack("!i32s8s?bb", data[offset:offset+fwver_size])

			fw["version"] = fw["version"].replace("\x00", "")
			fw["commit"] = fw["commit"].replace("\x00", "")

			fw_name = fw_names[i]
			resp[fw_name] = fw

		resp["bootloader_timestamp"],resp["hw_version"],resp["serial"] = \
			unpack("!L9s12s", data[95:120])
		
		resp["hw_version"] = resp["hw_version"].replace("\x00","")

		btmac_hex = binascii.hexlify(data[120:126])
		resp["btmac"] = ":".join([btmac_hex[i:i+2].upper() for i in reversed(xrange(0, 12, 2))])

		return resp

if __name__ == '__main__':
	pebble_id = sys.argv[1] if len(sys.argv) > 1 else "402F"
	pebble = Pebble(pebble_id)

	versions = pebble.get_versions()
	curtime = pebble.get_time()
	apps = pebble.get_appbank_status()

	print "Pebble "+pebble_id
	print "Firmware "+versions["normal_fw"]["version"]
	print "Recovery "+versions["recovery_fw"]["version"]
	print "Timestamp: "+str(curtime)

	print "Installed apps:"
	for app in apps["apps"]:
		print " - "+app["name"]