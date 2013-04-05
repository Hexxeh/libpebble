#!/usr/bin/env python

import binascii
import glob
import itertools
import json
import logging
import os
import serial
import stm32_crc
import threading
import time
import traceback
import uuid
import zipfile

from collections import OrderedDict
from LightBluePebble import LightBluePebble
from struct import pack, unpack

log = logging.getLogger()
logging.basicConfig(format='[%(levelname)-8s] %(message)s')
log.setLevel(logging.DEBUG)

DEFAULT_PEBBLE_ID = None #Triggers autodetection on unix-like systems

DEBUG_PROTOCOL = False

class PebbleBundle(object):
	MANIFEST_FILENAME = 'manifest.json'

	def __init__(self, bundle_path):
		bundle_abs_path = os.path.abspath(bundle_path)
		if not os.path.exists(bundle_abs_path):
			raise "Bundle does not exist: " + bundle_path

		self.zip = zipfile.ZipFile(bundle_abs_path)
		self.path = bundle_abs_path
		self.manifest = None

	def get_manifest(self):
		if (self.manifest):
			return self.manifest

		if self.MANIFEST_FILENAME not in self.zip.namelist():
			raise "Could not find {}; are you sure this is a PebbleBundle?".format(self.MANIFEST_FILENAME)

		self.manifest = json.loads(self.zip.read(self.MANIFEST_FILENAME))
		return self.manifest

	def close(self):
		self.zip.close()

	def is_firmware_bundle(self):
		return 'firmware' in self.get_manifest()

	def is_app_bundle(self):
		return 'application' in self.get_manifest()

	def has_resources(self):
		return 'resources' in self.get_manifest()

	def get_firmware_info(self):
		if not self.is_firmware_bundle():
			return None

		return self.get_manifest()['firmware']

	def get_application_info(self):
		if not self.is_app_bundle():
			return None

		return self.get_manifest()['application']

	def get_resources_info(self):
		if not self.has_resources():
			return None

		return self.get_manifest()['resources']


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

class PebbleError(Exception):
	 def __init__(self, id, message):
		self._id = id
		self._message = message

	 def __str__(self):
		return "%s (ID:%s)" % (self._message, self._id)

class Pebble(object):

	"""
	A connection to a Pebble watch; data and commands may be sent
	to the watch through an instance of this class.
	"""

	endpoints = {
		"TIME": 11,
		"VERSION": 16,
		"PHONE_VERSION": 17,
		"SYSTEM_MESSAGE": 18,
		"MUSIC_CONTROL": 32,
		"PHONE_CONTROL": 33,
		"APPLICATION_MESSAGE": 48,
		"LAUNCHER": 49,
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

	@staticmethod
	def AutodetectDevice():
		if os.name != "posix": #i.e. Windows
			raise NotImplementedError("Autodetection is only implemented on UNIX-like systems.")

		pebbles = glob.glob("/dev/tty.Pebble????-SerialPortSe")

		if len(pebbles) == 0:
			raise PebbleError(None, "Autodetection could not find any Pebble devices")
		elif len(pebbles) > 1:
			log.warn("Autodetect found %d Pebbles; using most recent" % len(pebbles))
			#NOTE: Not entirely sure if this is the correct approach
			pebbles.sort(key=lambda x: os.stat(x).st_mtime, reverse=True)

		id = pebbles[0][15:19]
		log.info("Autodetect found a Pebble with ID %s" % id)
		return id

	def __init__(self, id = None, using_lightblue = True, pair_first = False):
		if id is None and not using_lightblue:
			id = Pebble.AutodetectDevice()
		self.id = id
		self.using_lightblue = using_lightblue
		self._alive = True
		self._endpoint_handlers = {}
		self._internal_endpoint_handlers = {
			self.endpoints["TIME"]: self._get_time_response,
			self.endpoints["VERSION"]: self._version_response,
			self.endpoints["PHONE_VERSION"]: self._phone_version_response,
			self.endpoints["SYSTEM_MESSAGE"]: self._system_message_response,
			self.endpoints["MUSIC_CONTROL"]: self._music_control_response,
			self.endpoints["APPLICATION_MESSAGE"]: self._application_message_response,
			self.endpoints["LAUNCHER"]: self._application_message_response,
			self.endpoints["LOGS"]: self._log_response,
			self.endpoints["PING"]: self._ping_response,
			self.endpoints["APP_MANAGER"]: self._appbank_status_response
		}

		try:
			if using_lightblue:
				self._ser = LightBluePebble(self.id, pair_first)
			else:
				devicefile = "/dev/tty.Pebble"+id+"-SerialPortSe"
				log.debug("Attempting to open %s as Pebble device %s" % (devicefile, id))
				self._ser = serial.Serial(devicefile, 115200, timeout=1)

			log.debug("Initializing reader thread")
			self._read_thread = threading.Thread(target=self._reader)
			self._read_thread.setDaemon(True)
			self._read_thread.start()
			log.debug("Reader thread loaded on tid %s" % self._read_thread.name)
		except PebbleError:
			raise PebbleError(id, "Failed to connect to Pebble")
		except:
			raise

	def __del__(self):
		try:
			self._ser.close()
		except:
			pass

	def _reader(self):
		try:
			while self._alive:
				endpoint, resp = self._recv_message()
				if resp == None:
					continue

				if endpoint in self._internal_endpoint_handlers:
					resp = self._internal_endpoint_handlers[endpoint](endpoint, resp)

				if endpoint in self._endpoint_handlers and resp:
					self._endpoint_handlers[endpoint](endpoint, resp)
		except:
			traceback.print_exc()
			raise PebbleError(self.id, "Lost connection to Pebble")
			self._alive = False

	def _build_message(self, endpoint, data):
		return pack("!HH", len(data), endpoint)+data

	def _send_message(self, endpoint, data, callback = None):
		if endpoint not in self.endpoints:
			raise PebbleError(self.id, "Invalid endpoint specified")

		msg = self._build_message(self.endpoints[endpoint], data)

		if DEBUG_PROTOCOL:
			log.debug('>>> ' + msg.encode('hex'))
		self._ser.write(msg)

	def _recv_message(self):
		if self.using_lightblue:
			try:
				endpoint, resp, data = self._ser.read()
				if resp is None:
					return None, None
			except TypeError:
				# the lightblue process has likely shutdown and cannot be read from
				self.alive = False
				return None, None
		else:
			data = self._ser.read(4)
			if len(data) == 0:
				return (None, None)
			elif len(data) < 4:
				raise PebbleError(self.id, "Malformed response with length "+str(len(data)))
			size, endpoint = unpack("!HH", data)
			resp = self._ser.read(size)

		if DEBUG_PROTOCOL:
			log.debug("Got message for endpoint %s of length %d" % (endpoint, len(resp)))
			log.debug('<<< ' + (data + resp).encode('hex'))

		return (endpoint, resp)

	def register_endpoint(self, endpoint_name, func):
		if endpoint_name not in self.endpoints:
			raise PebbleError(self.id, "Invalid endpoint specified")

		endpoint = self.endpoints[endpoint_name]
		self._endpoint_handlers[endpoint] = func

	def notification_sms(self, sender, body):

		"""Send a 'SMS Notification' to the displayed on the watch."""

		ts = str(int(time.time())*1000)
		parts = [sender, body, ts]
		data = "\x01"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message("NOTIFICATION", data)

	def notification_email(self, sender, subject, body):

		"""Send an 'Email Notification' to the displayed on the watch."""

		ts = str(int(time.time())*1000)
		parts = [sender, subject, ts, body]
		data = "\x00"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message("NOTIFICATION", data)

	def set_nowplaying_metadata(self, track, album, artist):

		"""Update the song metadata displayed in Pebble's music app."""

		parts = [artist, album, track]

		data = pack("!b", 16)
		for part in parts:
			part = part[0:29] if len(part) > 30 else part
			data += pack("!b", len(part))+part
		self._send_message("MUSIC_CONTROL", data)

	def get_versions(self, async = False):

		"""
		Retrieve a summary of version information for various software
		(firmware, bootloader, etc) running on the watch.
		"""

		self._send_message("VERSION", "\x00")

		if not async:
			return EndpointSync(self, "VERSION").get_data()

	def get_appbank_status(self, async = False):

		"""
		Retrieve a list of all installed watch-apps.

		This is particularly useful when trying to locate a
		free app-bank to use when installing a new watch-app.
		"""

		self._send_message("APP_MANAGER", "\x01")

		if not async:
			return EndpointSync(self, "APP_MANAGER").get_data()

	def remove_app(self, appid, index):

		"""Remove an installed application from the target app-bank."""

		data = pack("!bII", 2, appid, index)
		self._send_message("APP_MANAGER", data)

	def remove_app_by_uuid(self, uuid):

		"""Remove an installed application by UUID."""

		data = pack("b", 0x02) + uuid
		self._send_message("APP_MANAGER", data)

	def get_time(self, async = False):

		"""Retrieve the time from the Pebble's RTC."""

		self._send_message("TIME", "\x00")

		if not async:
			return EndpointSync(self, "TIME").get_data()

	def set_time(self, timestamp):

		"""Set the time stored in the target Pebble's RTC."""

		data = pack("!bL", 2, timestamp)
		self._send_message("TIME", data)

	def reinstall_app(self, name, pbz_path):

		"""
		A convenience method to uninstall and install an app.

		This will only work if the app hasn't changed names between the new and old versions.
		"""
		apps = self.get_appbank_status()
		for app in apps["apps"]:
			if app["name"] == name:
				self.remove_app(app["id"], app["index"])
		self.install_app(pbz_path)

	def install_app(self, pbz_path):

		"""
		Install an app bundle (*.pbw) to the target Pebble.

		This will pick the first free app-bank available.
		"""

		bundle = PebbleBundle(pbz_path)
		if not bundle.is_app_bundle():
			raise PebbleError(self.id, "This is not an app bundle")

		binary = bundle.zip.read(
			bundle.get_application_info()['name'])
		if bundle.has_resources():
			resources = bundle.zip.read(
				bundle.get_resources_info()['name'])
		else:
			resources = None

		apps = self.get_appbank_status()

		if not apps:
			raise PebbleError(self.id, "could not obtain app list; try again")

		first_free = 1
		for app in apps["apps"]:
			if app["index"] == first_free:
				first_free += 1
		if first_free == apps["banks"]:
			raise PebbleError(self.id, "All %d app banks are full" % apps["banks"])
		log.debug("Attempting to add app to bank %d of %d" % (first_free, apps["banks"]))

		client = PutBytesClient(self, first_free, "BINARY", binary)
		self.register_endpoint("PUTBYTES", client.handle_message)
		client.init()
		while not client._done and not client._error:
			pass
		if client._error:
			raise PebbleError(self.id, "Failed to send application binary %s/pebble-app.bin" % pbz_path)

		if resources:
			client = PutBytesClient(self, first_free, "RESOURCES", resources)
			self.register_endpoint("PUTBYTES", client.handle_message)
			client.init()
			while not client._done and not client._error:
				pass
			if client._error:
				raise PebbleError(self.id, "Failed to send application resources %s/app_resources.pbpack" % pbz_path)

		time.sleep(2)
		self._add_app(first_free)
		time.sleep(2)


	def install_firmware(self, pbz_path, recovery=False):

		"""Install a firmware bundle to the target watch."""

		resources = None
		with zipfile.ZipFile(pbz_path) as pbz:
			binary = pbz.read("tintin_fw.bin")
			if not recovery:
				resources = pbz.read("system_resources.pbpack")

		self.system_message("FIRMWARE_START")
		time.sleep(2)

		if resources:
			client = PutBytesClient(self, 0, "SYS_RESOURCES", resources)
			self.register_endpoint("PUTBYTES", client.handle_message)
			client.init()
			while not client._done and not client._error:
				pass
			if client._error:
				raise PebbleError(self.id, "Failed to send firmware resources %s/system_resources.pbpack" % pbz_path)


		client = PutBytesClient(self, 0, "RECOVERY" if recovery else "FIRMWARE", binary)
		self.register_endpoint("PUTBYTES", client.handle_message)
		client.init()
		while not client._done and not client._error:
			pass
		if client._error:
			raise PebbleError(self.id, "Failed to send firmware binary %s/tintin_fw.bin" % pbz_path)

		self.system_message("FIRMWARE_COMPLETE")

	def launcher_message(self, app_uuid, key_value, uuid_is_string = True, async = False):
		""" send an appication message to launch or kill a specified application"""

		launcher_keys = {
			"RUN_STATE_KEY": b'\x00\x00\x00\x01'
		}

		launcher_key_values = {
			"NOT_RUNNING": b'\x00',
			"RUNNING": b'\x01'
		}

		if key_value not in launcher_key_values:
			raise PebbleError(self.id, "not a valid application message")

		if uuid_is_string:
			app_uuid = app_uuid.decode('hex')
		elif type(app_uuid) is uuid.UUID:
			app_uuid = app_uuid.bytes
		#else we can assume it's a byte array

		amsg = AppMessage()

		# build and send a single tuple-sized launcher command
		app_message_tuple = amsg.build_tuple(launcher_keys["RUN_STATE_KEY"], "UINT", launcher_key_values[key_value])
		app_message_dict = amsg.build_dict(app_message_tuple)
		packed_message = amsg.build_message(app_message_dict, "PUSH", app_uuid)
		self._send_message("LAUNCHER", packed_message)

		# wait for either ACK or NACK response
		if not async:
			return EndpointSync(self, "LAUNCHER").get_data()

	def system_message(self, command):

		"""
		Send a 'system message' to the watch.

		These messages are used to signal important events/state-changes to the watch firmware.
		"""

		commands = {
			"FIRMWARE_AVAILABLE": 0,
			"FIRMWARE_START": 1,
			"FIRMWARE_COMPLETE": 2,
			"FIRMWARE_FAIL": 3,
			"FIRMWARE_UP_TO_DATE": 4,
			"FIRMWARE_OUT_OF_DATE": 5,
			"BLUETOOTH_START_DISCOVERABLE": 6,
			"BLUETOOTH_END_DISCOVERABLE": 7
		}
		if command not in commands:
			raise PebbleError(self.id, "Invalid command \"%s\"" % command)
		data = pack("!bb", 0, commands[command])
		log.debug("Sending command %s (code %d)" % (command, commands[command]))
		self._send_message("SYSTEM_MESSAGE", data)

	def ping(self, cookie = 0, async = False):

		"""Send a 'ping' to the watch to test connectivity."""

		data = pack("!bL", 0, cookie)
		self._send_message("PING", data)

		if not async:
			return EndpointSync(self, "PING").get_data()

	def reset(self):

		"""Reset the watch remotely."""

		self._send_message("RESET", "\x00")

	def disconnect(self):

		"""Disconnect from the target Pebble."""

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

	def _system_message_response(self, endpoint, data):
		if len(data) == 2:
			log.info("Got system message %s" % repr(unpack('!bb', data)))
		else:
			log.info("Got 'unknown' system message...")

	def _log_response(self, endpoint, data):
		if (len(data) < 8):
			log.warn("Unable to decode log message (length %d is less than 8)" % len(data))
			return;

		timestamp, level, msgsize, linenumber = unpack("!Ibbh", data[:8])
		filename = data[8:24].decode('utf-8')
		message = data[24:24+msgsize].decode('utf-8')

		log_levels = {
			0: "*",
			1: "E",
			50: "W",
			100: "I",
			200: "D",
			250: "V"
		}

		level = log_levels[level] if level in log_levels else "?"

		print timestamp, level, filename, linenumber, message

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

	def _application_message_response(self, endpoint, data):
		app_messages = {
			b'\x01': "PUSH",
			b'\x02': "REQUEST",
			b'\xFF': "ACK",
			b'\x7F': "NACK"
		}

		if len(data) > 1:
			rest = data[1:]
		else:
			rest = ''
		if data[0] in app_messages:
			return app_messages[data[0]] + rest


	def _phone_version_response(self, endpoint, data):
		session_cap = {
			"GAMMA_RAY" : 0x80000000,
		}
		remote_cap = {
			"TELEPHONY" : 16,
			"SMS" : 32,
			"GPS" : 64,
			"BTLE" : 128,
			"CAMERA_REAR" : 256,
			"ACCEL" : 512,
			"GYRO" : 1024,
			"COMPASS" : 2048,
		}
		os = {
			"UNKNOWN" : 0,
			"IOS" : 1,
			"ANDROID" : 2,
			"OSX" : 3,
			"LINUX" : 4,
			"WINDOWS" : 5,
		}

		# Then session capabilities, android adds GAMMA_RAY and it's
		# the only session flag so far
		session = session_cap["GAMMA_RAY"]

		# Then phone capabilities, android app adds TELEPHONY and SMS,
		# and the phone type (we know android works for now)
		remote = remote_cap["TELEPHONY"] | remote_cap["SMS"] | os["ANDROID"]

		msg = pack("!biII", 1, -1, session, remote)
		self._send_message("PHONE_VERSION", msg);

	def _music_control_response(self, endpoint, data):
		event, = unpack("!b", data)

		event_names = {
			1: "PLAYPAUSE",
			4: "NEXT",
			5: "PREVIOUS",
		}

		return event_names[event] if event in event_names else None


class AppMessage(object):
# tools to build a valid app message
	def build_tuple(self, key, data_type, data):
		""" make a single app_message tuple"""
		# available app message datatypes:
		tuple_datatypes = {
			"BYTE_ARRAY": b'\x00',
			"CSTRIMG": b'\x01',
			"UINT": b'\x02',
			"INT": b'\x03'
		}
		# first build the message_tuple
		app_message_tuple = OrderedDict([
			("KEY", key),
			("TYPE", tuple_datatypes[data_type]),
			("LENGTH", pack('<H', len(data))),
			("DATA", data)
		])
		# handle the little endians
		app_message_tuple["KEY"] = app_message_tuple["KEY"][::-1]
		app_message_tuple["DATA"] = app_message_tuple["DATA"][::-1]
		return app_message_tuple

	def build_dict(self, tuple_of_tuples):
		""" make a dictionary from a list of app_message tuples"""
		# note that "TUPLE" can refer to 0 or more tuples. Tuples must be correct endian-ness already
		tuple_count = len(tuple_of_tuples)
		# make the bytearray from the flattened tuples
		tuple_total_bytes = ''.join(item for item in itertools.chain(*tuple_of_tuples.values()))
		# now build the dict
		app_message_dict = OrderedDict([
			("TUPLECOUNT", pack('B', tuple_count)),
			("TUPLE", tuple_total_bytes)
		])
		return app_message_dict

	def build_message(self, dict_of_tuples, command, uuid, transaction_id=b'\x00'):
		""" build the app_message intended for app with matching uuid"""
		# NOTE: uuid must be a byte array
		# available app_message commands:
		app_messages = {
			"PUSH": b'\x01',
			"REQUEST": b'\x02',
			"ACK": b'\xFF',
			"NACK": b'\x7F'
		}
		# finally build the entire message
		app_message = OrderedDict([
			("COMMAND", app_messages[command]),
			("TRANSACTIONID", transaction_id),
			("UUID", uuid),
			("DICT", ''.join(dict_of_tuples.values()))
		])
		return ''.join(app_message.values())


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
		"FIRMWARE": 1,
		"RECOVERY": 2,
		"SYS_RESOURCES": 3,
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
		self._error = False

	def init(self):
		data = pack("!bIbb", 1, len(self._buffer), self._transfer_type, self._index)
		self._pebble._send_message("PUTBYTES", data)
		self._state = self.states["WAIT_FOR_TOKEN"]

	def wait_for_token(self, resp):
		res, = unpack("!b", resp[0])
		if res != 1:
			log.error("init failed with code %d" % res)
			self._error = True
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
			log.debug("Sent %d of %d bytes" % (len(self._buffer)-self._left, len(self._buffer)))
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
		msgdata = pack("!bI", 4, self._token & 0xFFFFFFFF)
		self._pebble.send_message("PUTBYTES", msgdata)
		self._error = True

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
