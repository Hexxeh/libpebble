#!/usr/bin/env python

import serial, codecs, sys, binascii, time
from pprint import pprint
from struct import *

class Pebble(object):
	def __init__(self, id):
		try:
			self._ser = serial.Serial("/dev/tty.Pebble"+id+"-SerialPortSe", 19200, timeout=1)

			# we get a null response when we connect, discard it
			self._ser.read(5)
		except:
			raise Exception("Failed to connect to Pebble")

	def __del__(self):
		try:
			self._ser.close()
		except:
			pass

	def _build_message(self, endpoint, data):
		return pack("!hh", len(data), endpoint)+data

	def _send_message(self, endpoint, data):
		msg = self._build_message(endpoint, data)
		self._ser.write(msg)

	def _recv_message(self):
		data = self._ser.read(4)
		if len(data) < 4:
			raise Exception("Malformed response with length "+str(len(data)))
		size, endpoint = unpack("!hh", data)
		resp = self._ser.read(size)
		return (endpoint, resp)

	def notification_sms(self, sender, body):
		ts = str(int(time.time())*1000)
		parts = [sender, body, ts]
		data = "\x01"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message(3000, data)

	def notification_email(self, sender, subject, body):
		ts = str(int(time.time())*1000)
		parts = [sender, subject, ts, body]
		data = "\x00"
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message(3000, data)	

	def set_nowplaying_metadata(self, track, album, artist):
		ts = str(int(time.time())*1000)
		parts = [artist, album, track]
		data = pack("!b", 16)
		for part in parts:
			data += pack("!b", len(part))+part
		self._send_message(32, data)

	def get_versions(self):
		self._send_message(16, "\x00")
		endpoint, resp = self._recv_message()
		return self._version_response(resp)

	def get_appbank_status(self):
		self._send_message(6000, "\x01")

		apps = {}
		endpoint, resp = self._recv_message()
		restype, apps["banks"], apps_installed = unpack("!bII", resp[:9])
		apps["apps"] = []

		appinfo_size = 78
		offset = 9
		for i in xrange(apps_installed):
			app = {}
			app["id"], app["index"], app["name"], app["company"], app["flags"], app["version"] = \
				unpack("!II32s32sIH", resp[offset:offset+appinfo_size])
			app["name"] = app["name"].replace("\x00", "")
			app["company"] = app["company"].replace("\x00", "")
			apps["apps"] += [app]
			offset += appinfo_size

		return apps

	def remove_app(self, appid, index):
		data = pack("!bII", 2, appid, index)
		self._send_message(6000, data)
		endpoint, resp = self._recv_message()

	def get_time(self):
		self._send_message(11, "\x00")
		endpoint, resp = self._recv_message()
		restype, timestamp = unpack("!bL", resp)
		return timestamp

	def set_time(self, timestamp):
		data = pack("!bL", 2, timestamp)
		self._send_message(11, data)

	def ping(self, cookie = 0):
		data = pack("!bL", 0, cookie)
		self._send_message(2001, data)
		endpoint, resp = self._recv_message()
		restype, retcookie = unpack("!bL", resp)
		return cookie == retcookie

	def reset(self):
		self._send_message(2003, "\x00")

	def _version_response(self, data):
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
	pebble.ping()

	print "Pebble is running firmware version "+pebble.get_versions()["normal_fw"]["version"]
	print "Installed apps:"
	for app in pebble.get_appbank_status()["apps"]:
		print " - "+app["name"]