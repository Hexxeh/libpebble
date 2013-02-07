#!/usr/bin/env python

import serial, codecs, sys, binascii, time, threading, stm32_crc, zipfile
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
		"PHONE_VERSION": 17,
		"SYSTEM_MESSAGE": 18,
		"MUSIC_CONTROL": 32,
		"PHONE_CONTROL": 33,
		"LOGS": 2000,
		"PING": 2001,
		"LOG_DUMP": 2002,
		"RESET": 2003,
		"APP": 2004,
		"NOTIFICATION": 3000,
		"RESOURCE": 4000,
		"APP_MANAGER": 6000,
		"PUTBYTES": 48879
	}

	def __init__(self, id):
		self._alive = True
		self._endpoint_handlers = {}
		self._internal_endpoint_handlers = {
			self.endpoints["TIME"]: self._get_time_response,
			self.endpoints["VERSION"]: self._version_response,
			self.endpoints["PING"]: self._ping_response,
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
		return pack("!HH", len(data), endpoint)+data

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
		size, endpoint = unpack("!HH", data)
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

	def install_app(self, pbz_path):
		with zipfile.ZipFile(pbz_path) as pbz:
			binary = pbz.read("pebble-app.bin")
			resources = pbz.read("app_resources.pbpack")

		apps = self.get_appbank_status()
		first_free = 1
		for app in apps["apps"]:
			if app["index"] == first_free:
				first_free += 1
		if first_free == apps["banks"]:
			raise Exception("No available app banks left")

		client = PutBytesClient(self, first_free, "BINARY", binary)
		self.register_endpoint("PUTBYTES", client.handle_message)
		client.init()
		while not client._done:
			pass

		client = PutBytesClient(self, first_free, "RESOURCES", resources)
		self.register_endpoint("PUTBYTES", client.handle_message)
		client.init()
		while not client._done:
			pass

		self._add_app(first_free)

	"""
		Valid commands:
			FIRMWARE_AVAILABLE = 0
			FIRMWARE_START = 1
			FIRMWARE_COMPLETE = 2
			FIRMWARE_FAIL = 3
			FIRMWARE_UP_TO_DATE = 4
			FIRMWARE_OUT_OF_DATE = 5
	"""
	def system_message(self, command):
		data = pack("!bb", 0, command)
		self._send_message("SYSTEM_MESSAGE", data)

	def ping(self, cookie = 0, async = False):
		data = pack("!bL", 0, cookie)
		self._send_message("PING", data)
		
		if not async:
			return EndpointSync(self, "PING").get_data()	

	def reset(self):
		self._send_message("RESET", "\x00")

	def disconnect(self):
		self._alive = False
		self._ser.close()

	def _add_app(self, index):
		data = pack("!bI", 3, index)
		self._send_message("APP_MANAGER", data)

	def _ping_response(self, endpoint, data):
		restype, retcookie = unpack("!bL", data)
		return retcookie

	def _get_time_response(self, endpoint, data):
		restype, timestamp = unpack("!bL", data)
		return timestamp

	def _appbank_status_response(self, endpoint, data):
		apps = {}
		restype, = unpack("!b", data[0])

		if restype == 1:
			apps["banks"], apps_installed = unpack("!II", data[1:9])
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

class PutBytesClient(object):
	states = {
		"NOT_STARTED": 0,
		"WAIT_FOR_TOKEN": 1,
		"IN_PROGRESS": 2,
		"COMMIT": 3,
		"COMPLETE": 4,
		"FAILED": 5
	}

	transfer_types = {
		"RESOURCES": 4,
		"BINARY": 5
	}

	def __init__(self, pebble, index, transfer_type, buffer):
		self._pebble = pebble
		self._state = self.states["NOT_STARTED"]
		self._transfer_type = self.transfer_types[transfer_type]
		self._buffer = buffer
		self._index = index
		self._done = False

	def init(self):
		data = pack("!bIbb", 1, len(self._buffer), self._transfer_type, self._index)
		self._pebble._send_message("PUTBYTES", data)
		self._state = self.states["WAIT_FOR_TOKEN"]

	def wait_for_token(self, resp):
		res, = unpack("!b", resp[0])
		if res != 1:
			self.abort()
			return
		self._token, = unpack("!I", resp[1:])
		self._left = len(self._buffer)
		self._state = self.states["IN_PROGRESS"]
		self.send()

	def in_progress(self, resp):
		res, = unpack("!b", resp[0])
		if res != 1:
			self.abort()
			return
		if self._left > 0:
			self.send() 
		else:
			self._state = self.states["COMMIT"]
			self.commit()	       

	def commit(self):
		data = pack("!bII", 3, self._token & 0xFFFFFFFF, stm32_crc.crc32(self._buffer))
		self._pebble._send_message("PUTBYTES", data)

	def handle_commit(self, resp):
		res, = unpack("!b", resp[0])
		if res != 1:
			self.abort()
			return
		self._state = self.states["COMPLETE"]
		self.complete()

	def complete(self):
		data = pack("!bI", 5, self._token & 0xFFFFFFFF)
		self._pebble._send_message("PUTBYTES", data)

	def handle_complete(self, resp):
		res, = unpack("!b", resp[0])
		if res != 1:
			self.abort()
			return
		self._done = True

	def abort(self):
		# error handling? what error handling!
		pass

	def send(self):
		datalen =  min(self._left, 2000)
		rg = len(self._buffer)-self._left
		msgdata = pack("!bII", 2, self._token & 0xFFFFFFFF, datalen)
		msgdata += self._buffer[rg:rg+datalen]
		self._pebble._send_message("PUTBYTES", msgdata)       
		self._left -= datalen

	def handle_message(self, endpoint, resp):
		if self._state == self.states["WAIT_FOR_TOKEN"]:
			self.wait_for_token(resp)
		elif self._state == self.states["IN_PROGRESS"]:
			self.in_progress(resp)
		elif self._state == self.states["COMMIT"]:
			self.handle_commit(resp)
		elif self._state == self.states["COMPLETE"]:
			self.handle_complete(resp)

if __name__ == '__main__':
	pebble_id = sys.argv[1] if len(sys.argv) > 1 else "402F"
	pebble = Pebble(pebble_id)

	pebble.notification_sms("libpebble", "Hello, Pebble!")

	# install app.pbz
	print "Installing app.pbz"
	pebble.install_app("app.pbz")
	
	# delete all apps
	#for app in pebble.get_appbank_status()["apps"]:
	#	pebble.remove_app(app["id"], app["index"])

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
