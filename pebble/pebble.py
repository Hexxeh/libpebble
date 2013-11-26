#!/usr/bin/env python

import binascii
import datetime
import glob
import itertools
import json
import logging as log
import os
import sh
import signal
import stm32_crc
import struct
import threading
import time
import traceback
import re
import uuid
import zipfile
import WebSocketPebble

from collections import OrderedDict
from struct import pack, unpack
from PIL import Image

DEFAULT_PEBBLE_ID = None #Triggers autodetection on unix-like systems
DEFAULT_WEBSOCKET_PORT = 9000
DEBUG_PROTOCOL = False
APP_ELF_PATH = 'build/pebble-app.elf'

class PebbleBundle(object):
    MANIFEST_FILENAME = 'manifest.json'

    STRUCT_DEFINITION = [
            '8s',   # header
            '2B',   # struct version
            '2B',   # sdk version
            '2B',   # app version
            'H',    # size
            'I',    # offset
            'I',    # crc
            '32s',  # app name
            '32s',  # company name
            'I',    # icon resource id
            'I',    # symbol table address
            'I',    # flags
            'I',    # relocation list start
            'I',    # num relocation list entries
            '16s'   # uuid
    ]

    def __init__(self, bundle_path):
        bundle_abs_path = os.path.abspath(bundle_path)
        if not os.path.exists(bundle_abs_path):
            raise Exception("Bundle does not exist: " + bundle_path)

        self.zip = zipfile.ZipFile(bundle_abs_path)
        self.path = bundle_abs_path
        self.manifest = None
        self.header = None

        self.app_metadata_struct = struct.Struct(''.join(self.STRUCT_DEFINITION))
        self.app_metadata_length_bytes = self.app_metadata_struct.size

        self.print_pbl_logs = False

    def get_manifest(self):
        if (self.manifest):
            return self.manifest

        if self.MANIFEST_FILENAME not in self.zip.namelist():
            raise Exception("Could not find {}; are you sure this is a PebbleBundle?".format(self.MANIFEST_FILENAME))

        self.manifest = json.loads(self.zip.read(self.MANIFEST_FILENAME))
        return self.manifest

    def get_app_metadata(self):

        if (self.header):
            return self.header

        app_manifest = self.get_manifest()['application']

        app_bin = self.zip.open(app_manifest['name']).read()

        header = app_bin[0:self.app_metadata_length_bytes]
        values = self.app_metadata_struct.unpack(header)
        self.header = {
                'sentinel' : values[0],
                'struct_version_major' : values[1],
                'struct_version_minor' : values[2],
                'sdk_version_major' : values[3],
                'sdk_version_minor' : values[4],
                'app_version_major' : values[5],
                'app_version_minor' : values[6],
                'app_size' : values[7],
                'offset' : values[8],
                'crc' : values[9],
                'app_name' : values[10].rstrip('\0'),
                'company_name' : values[11].rstrip('\0'),
                'icon_resource_id' : values[12],
                'symbol_table_addr' : values[13],
                'flags' : values[14],
                'relocation_list_index' : values[15],
                'num_relocation_entries' : values[16],
                'uuid' : uuid.UUID(bytes=values[17])
        }
        return self.header

    def close(self):
        self.zip.close()

    def is_firmware_bundle(self):
        return 'firmware' in self.get_manifest()

    def is_app_bundle(self):
        return 'application' in self.get_manifest()

    def has_resources(self):
        return 'resources' in self.get_manifest()

    def has_javascript(self):
        return 'js' in self.get_manifest()

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

class ScreenshotSync():
    timeout = 60
    SCREENSHOT_OK = 0
    SCREENSHOT_MALFORMED_COMMAND = 1
    SCREENSHOT_OOM_ERROR = 2

    def __init__(self, pebble, endpoint, progress_callback):
        self.marker = threading.Event()
        self.data = ''
        self.have_read_header = False
        self.length_received = 0
        self.progress_callback = progress_callback
        pebble.register_endpoint(endpoint, self.message_callback)

    # Received a reply message from the watch. We expect several of these...
    def message_callback(self, endpoint, data):
        if not self.have_read_header:
            data = self.read_header(data)
            self.have_read_header = True

        self.data += data
        self.length_received += len(data) * 8 # in bits
        self.progress_callback(float(self.length_received)/self.total_length)
        if self.length_received >= self.total_length:
            self.marker.set()

    def read_header(self, data):
        image_header = struct.Struct("!BIII")
        header_len = image_header.size
        header_data = data[:header_len]
        data = data[header_len:]
        response_code, version, self.width, self.height = \
          image_header.unpack(header_data)

        if response_code is not ScreenshotSync.SCREENSHOT_OK:
            raise PebbleError(None, "Pebble responded with nonzero response "
                "code %d, signaling an error on the watch side." %
                response_code)

        if version is not 1:
            raise PebbleError(None, "Received unrecognized image format "
                "version %d from watch. Maybe your libpebble is out of "
                "sync with your firmware version?" % version)

        self.total_length = self.width * self.height
        return data

    def get_data(self):
        try:
            self.marker.wait(timeout=self.timeout)
            return Image.frombuffer('1', (self.width, self.height), \
                self.data, "raw", "1;R", 0, 1)
        except:
            raise PebbleError(None, "Timed out... Is the Pebble phone app connected?")

class EndpointSync():
    timeout = 10

    def __init__(self, pebble, endpoint):
        self.marker = threading.Event()
        pebble.register_endpoint(endpoint, self.callback)

    def callback(self, endpoint, response):
        self.data = response
        self.marker.set()

    def get_data(self):
        try:
            self.marker.wait(timeout=self.timeout)
            return self.data
        except:
            raise PebbleError(None, "Timed out... Is the Pebble phone app connected?")

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
            "APP_LOGS": 2006,
            "NOTIFICATION": 3000,
            "RESOURCE": 4000,
            "APP_MANAGER": 6000,
            "SCREENSHOT": 8000,
            "PUTBYTES": 48879,
    }

    log_levels = {
            0: "*",
            1: "E",
            50: "W",
            100: "I",
            200: "D",
            250: "V"
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



    def __init__(self, id = None):
        self.id = id
        self._connection_type = None
        self._ser = None
        self._read_thread = None
        self._alive = True
        self._ws_client = None
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
                self.endpoints["APP_LOGS"]: self._app_log_response,
                self.endpoints["APP_MANAGER"]: self._appbank_status_response,
                self.endpoints["SCREENSHOT"]: self._screenshot_response,
        }

    def init_reader(self):
        try:
            log.debug("Initializing reader thread")
            self._read_thread = threading.Thread(target=self._reader)
            self._read_thread.setDaemon(True)
            self._read_thread.start()
            log.debug("Reader thread loaded on tid %s" % self._read_thread.name)
        except PebbleError:
            raise PebbleError(id, "Failed to connect to Pebble")
        except:
            raise

    def connect_via_serial(self, id = None):
        self._connection_type = 'serial'

        if id != None:
            self.id = id
        if self.id is None:
            self.id = Pebble.AutodetectDevice()

        import serial
        devicefile = "/dev/tty.Pebble{}-SerialPortSe".format(self.id)
        log.debug("Attempting to open %s as Pebble device %s" % (devicefile, self.id))
        self._ser = serial.Serial(devicefile, 115200, timeout=1)
        self.init_reader()

    def connect_via_lightblue(self, pair_first = False):
        self._connection_type = 'lightblue'

        from LightBluePebble import LightBluePebble
        self._ser = LightBluePebble(self.id, pair_first)
        signal.signal(signal.SIGINT, self._exit_signal_handler)
        self.init_reader()

    def connect_via_websocket(self, host, port=DEFAULT_WEBSOCKET_PORT):
        self._connection_type = 'websocket'

        WebSocketPebble.enableTrace(False)
        self._ser = WebSocketPebble.create_connection(host, port, connect_timeout=5)
        self.init_reader()

    def _exit_signal_handler(self, signum, frame):
        log.warn("Disconnecting before exiting...")
        self.disconnect()
        time.sleep(1)
        os._exit(0)

    def __del__(self):
        try:
            self._ser.close()
        except:
            pass

    def _reader(self):
        try:
            while self._alive:
                source, endpoint, resp = self._recv_message()
                #reading message if socket is closed causes exceptions

                if resp is None or source is None:
                    # ignore message
                    continue

                if source == 'ws':
                    if endpoint in ['status', 'phoneInfo']:
                        # phone -> sdk message
                        self._ws_client.handle_response(endpoint, resp)
                    elif endpoint == 'log':
                        log.info(resp)
                    continue

                #log.info("message for endpoint " + str(endpoint) + " resp : " + str(resp))
                if endpoint in self._internal_endpoint_handlers:
                    resp = self._internal_endpoint_handlers[endpoint](endpoint, resp)

                if endpoint in self._endpoint_handlers and resp is not None:
                    self._endpoint_handlers[endpoint](endpoint, resp)
        except Exception, e:
            print str(e)
            log.error("Lost connection to Pebble")
            self._alive = False
            os._exit(-1)


    def _pack_message_data(self, lead, parts):
        pascal = map(lambda x: x[:255], parts)
        d = pack("b" + reduce(lambda x,y: str(x) + "p" + str(y), map(lambda x: len(x) + 1, pascal)) + "p", lead, *pascal)
        return d

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
        if self._connection_type != 'serial':
            try:
                source, endpoint, resp, data = self._ser.read()
                if resp is None:
                    return None, None, None
            except TypeError:
                # the lightblue process has likely shutdown and cannot be read from
                self.alive = False
                return None, None, None
        else:
            data = self._ser.read(4)
            if len(data) == 0:
                return (None, None, None)
            elif len(data) < 4:
                raise PebbleError(self.id, "Malformed response with length "+str(len(data)))
            size, endpoint = unpack("!HH", data)
            resp = self._ser.read(size)
        if DEBUG_PROTOCOL:
            log.debug("Got message for endpoint %s of length %d" % (endpoint, len(resp)))
            log.debug('<<< ' + (data + resp).encode('hex'))

        return ("serial", endpoint, resp)

    def register_endpoint(self, endpoint_name, func):
        if endpoint_name not in self.endpoints:
            raise PebbleError(self.id, "Invalid endpoint specified")

        endpoint = self.endpoints[endpoint_name]
        self._endpoint_handlers[endpoint] = func

    def notification_sms(self, sender, body):

        """Send a 'SMS Notification' to the displayed on the watch."""

        ts = str(int(time.time())*1000)
        parts = [sender, body, ts]
        self._send_message("NOTIFICATION", self._pack_message_data(1, parts))

    def notification_email(self, sender, subject, body):

        """Send an 'Email Notification' to the displayed on the watch."""

        ts = str(int(time.time())*1000)
        parts = [sender, body, ts, subject]
        self._send_message("NOTIFICATION", self._pack_message_data(0, parts))

    def set_nowplaying_metadata(self, track, album, artist):

        """Update the song metadata displayed in Pebble's music app."""

        parts = [artist[:30], album[:30], track[:30]]
        self._send_message("MUSIC_CONTROL", self._pack_message_data(16, parts))

    def screenshot(self, progress_callback):
        self._send_message("SCREENSHOT", "\x00")
        return ScreenshotSync(self, "SCREENSHOT", progress_callback).get_data()

    def get_versions(self, async = False):

        """
        Retrieve a summary of version information for various software
        (firmware, bootloader, etc) running on the watch.
        """

        self._send_message("VERSION", "\x00")

        if not async:
            return EndpointSync(self, "VERSION").get_data()


    def list_apps_by_uuid(self, async=False):
        data = pack("b", 0x05)
        self._send_message("APP_MANAGER", data)
        if not async:
            return EndpointSync(self, "APP_MANAGER").get_data()

    def describe_app_by_uuid(self, uuid, uuid_is_string=True, async = False):
        if uuid_is_string:
            uuid = uuid.decode('hex')
        elif type(uuid) is uuid.UUID:
            uuid = uuid.bytes
        # else, assume it's a byte array

        data = pack("b", 0x06) + str(uuid)
        self._send_message("APP_MANAGER", data)

        if not async:
            return EndpointSync(self, "APP_MANAGER").get_data()

    def current_running_uuid(self, async = False):
        data = pack("b", 0x07)
        self._send_message("APP_MANAGER", data)
        if not async:
            return EndpointSync(self, "APP_MANAGER").get_data()


    def get_appbank_status(self, async = False):

        """
        Retrieve a list of all installed watch-apps.

        This is particularly useful when trying to locate a
        free app-bank to use when installing a new watch-app.
        """
        self._send_message("APP_MANAGER", "\x01")

        if not async:
            apps = EndpointSync(self, "APP_MANAGER").get_data()
            return apps if type(apps) is dict else { 'apps': [] }

    def remove_app(self, appid, index, async=False):

        """Remove an installed application from the target app-bank."""

        data = pack("!bII", 2, appid, index)
        self._send_message("APP_MANAGER", data)

        if not async:
            return EndpointSync(self, "APP_MANAGER").get_data()

    def remove_app_by_uuid(self, uuid_to_remove, uuid_is_string=True, async = False):

        """Remove an installed application by UUID."""

        if uuid_is_string:
            uuid_to_remove = uuid_to_remove.decode('hex')
        elif type(uuid_to_remove) is uuid.UUID:
            uuid_to_remove = uuid_to_remove.bytes
        # else, assume it's a byte array

        data = pack("b", 0x02) + str(uuid_to_remove)
        self._send_message("APP_MANAGER", data)

        if not async:
            return EndpointSync(self, "APP_MANAGER").get_data()

    def get_time(self, async = False):

        """Retrieve the time from the Pebble's RTC."""

        self._send_message("TIME", "\x00")

        if not async:
            return EndpointSync(self, "TIME").get_data()

    def set_time(self, timestamp):

        """Set the time stored in the target Pebble's RTC."""

        data = pack("!bL", 2, timestamp)
        self._send_message("TIME", data)


    def install_app_ws(self, pbw_path):
        self._ws_client = WSClient()
        f = open(pbw_path, 'r')
        data = f.read()
        self._ser.write(data, ws_cmd=WebSocketPebble.WS_CMD_APP_INSTALL)
        self._ws_client.listen()
        while not self._ws_client._received and not self._ws_client._error:
            pass
        if self._ws_client._topic == 'status' \
                and self._ws_client._response == 0:
            log.info("Installation successful")
            return True
        log.debug("WS Operation failed with response %s" % 
                                        self._ws_client._response)
        log.error("Failed to install %s" % repr(pbw_path))
        return False


    def get_phone_info(self):
        self._ws_client = WSClient()
        # The first byte is reserved for future use as a protocol version ID
        #  and must be 0 for now. 
        data = pack("!b", 0)
        self._ser.write(data, ws_cmd=WebSocketPebble.WS_CMD_PHONE_INFO)
        self._ws_client.listen()
        while not self._ws_client._received and not self._ws_client._error:
          pass
        if self._ws_client._topic == 'phoneInfo':
          return self._ws_client._response
        else:
          log.error('get_phone_info: Unexpected response to "%s"' % self._ws_client._topic)
          return 'Unknown'

    def install_app_pebble_protocol(self, pbw_path, launch_on_install=True):

        bundle = PebbleBundle(pbw_path)
        if not bundle.is_app_bundle():
            raise PebbleError(self.id, "This is not an app bundle")

        app_metadata = bundle.get_app_metadata()
        self.remove_app_by_uuid(app_metadata['uuid'].bytes, uuid_is_string=False)

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

        binary = bundle.zip.read(bundle.get_application_info()['name'])
        if bundle.has_resources():
            resources = bundle.zip.read(bundle.get_resources_info()['name'])
        else:
            resources = None
        client = PutBytesClient(self, first_free, "BINARY", binary)
        self.register_endpoint("PUTBYTES", client.handle_message)
        client.init()
        while not client._done and not client._error:
            pass
        if client._error:
            raise PebbleError(self.id, "Failed to send application binary %s/pebble-app.bin" % pbw_path)

        if resources:
            client = PutBytesClient(self, first_free, "RESOURCES", resources)
            self.register_endpoint("PUTBYTES", client.handle_message)
            client.init()
            while not client._done and not client._error:
                pass
            if client._error:
                raise PebbleError(self.id, "Failed to send application resources %s/app_resources.pbpack" % pbw_path)

        time.sleep(2)
        self._add_app(first_free)
        time.sleep(2)

        if launch_on_install:
            self.launcher_message(app_metadata['uuid'].bytes, "RUNNING", uuid_is_string=False)

    def install_app(self, pbw_path, launch_on_install=True):

        """Install an app bundle (*.pbw) to the target Pebble."""

        if self._connection_type == 'websocket':
            self.install_app_ws(pbw_path)
        else:
            self.install_app_pebble_protocol(pbw_path, launch_on_install)

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
                "RUN_STATE_KEY": 1,
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

    def app_message_send_tuple(self, app_uuid, key, tuple_datatype, tuple_data):

        """  Send a Dictionary with a single tuple to the app corresponding to UUID """

        app_uuid = app_uuid.decode('hex')
        amsg = AppMessage()

        app_message_tuple = amsg.build_tuple(key, tuple_datatype, tuple_data)
        app_message_dict = amsg.build_dict(app_message_tuple)
        packed_message = amsg.build_message(app_message_dict, "PUSH", app_uuid)
        self._send_message("APPLICATION_MESSAGE", packed_message)

    def app_message_send_string(self, app_uuid, key, string):

        """  Send a Dictionary with a single tuple of type CSTRING to the app corresponding to UUID """

        # NULL terminate and pack
        string = string + '\0'
        fmt =  '<' + str(len(string)) + 's'
        string = pack(fmt, string);

        self.app_message_send_tuple(app_uuid, key, "CSTRING", string)

    def app_message_send_uint(self, app_uuid, key, tuple_uint):

        """  Send a Dictionary with a single tuple of type UINT to the app corresponding to UUID """

        fmt = '<' + str(tuple_uint.bit_length() / 8 + 1) + 'B'
        tuple_uint = pack(fmt, tuple_uint)

        self.app_message_send_tuple(app_uuid, key, "UINT", tuple_uint)

    def app_message_send_int(self, app_uuid, key, tuple_int):

        """  Send a Dictionary with a single tuple of type INT to the app corresponding to UUID """

        fmt = '<' + str(tuple_int.bit_length() / 8 + 1) + 'b'
        tuple_int = pack(fmt, tuple_int)

        self.app_message_send_tuple(app_uuid, key, "INT", tuple_int)

    def app_message_send_byte_array(self, app_uuid, key, tuple_byte_array):

        """  Send a Dictionary with a single tuple of type BYTE_ARRAY to the app corresponding to UUID """

        # Already packed, fix endianness
        tuple_byte_array = tuple_byte_array[::-1]

        self.app_message_send_tuple(app_uuid, key, "BYTE_ARRAY", tuple_byte_array)

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



    def ping(self, cookie = 0xDEC0DE, async = False):

        """Send a 'ping' to the watch to test connectivity."""

        data = pack("!bL", 0, cookie)
        self._send_message("PING", data)

        if not async:
            return EndpointSync(self, "PING").get_data()

    def reset(self):

        """Reset the watch remotely."""

        self._send_message("RESET", "\x00")

    def dump_logs(self, generation_number):
        """Dump the saved logs from the watch.

        Arguments:
        generation_number -- The genration to dump, where 0 is the current boot and 3 is the oldest boot.
        """

        if generation_number > 3:
            raise Exception("Invalid generation number %u, should be [0-3]" % generation_number)

        log.info('=== Generation %u ===' % generation_number)

        class LogDumpClient(object):
            def __init__(self, pebble):
                self.done = False
                self._pebble = pebble

            def parse_log_dump_response(self, endpoint, data):
                if (len(data) < 5):
                    log.warn("Unable to decode log dump message (length %d is less than 8)" % len(data))
                    return

                response_type, response_cookie = unpack("!BI", data[:5])
                if response_type == 0x81:
                    self.done = True
                    return
                elif response_type != 0x80 or response_cookie != cookie:
                    log.info("Received unexpected message with type 0x%x cookie %u expected 0x80 %u" %
                        (response_type, response_cookie, cookie))
                    self.done = True
                    return

                timestamp, str_level, filename, linenumber, message = self._pebble._parse_log_response(data[5:])

                timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

                log.info("{} {} {}:{}> {}".format(str_level, timestamp_str, filename, linenumber, message))

        client = LogDumpClient(self)
        self.register_endpoint("LOG_DUMP", client.parse_log_dump_response)

        import random
        cookie = random.randint(0, pow(2, 32) - 1)
        self._send_message("LOG_DUMP", pack("!BBI", 0x10, generation_number, cookie))

        while not client.done:
            time.sleep(1)

    def app_log_enable(self):
        log.info("Enabling application logging...")
        self._send_message("APP_LOGS", pack("!B", 0x01))

    def app_log_disable(self):
        log.info("Disabling application logging...")
        self._send_message("APP_LOGS", pack("!B", 0x00))

    def disconnect(self):

        """Disconnect from the target Pebble."""

        self._alive = False
        self._ser.close()

    def set_print_pbl_logs(self, value):
        self.print_pbl_logs = value

    def _add_app(self, index):
        data = pack("!bI", 3, index)
        self._send_message("APP_MANAGER", data)

    def _screenshot_response(self, endpoint, data):
        return data

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

    def _parse_log_response(self, log_message_data):
        timestamp, level, msgsize, linenumber = unpack("!IBBH", log_message_data[:8])
        filename = log_message_data[8:24].decode('utf-8')
        message = log_message_data[24:24+msgsize].decode('utf-8')

        str_level = self.log_levels[level] if level in self.log_levels else "?"

        return timestamp, str_level, filename, linenumber, message

    def _log_response(self, endpoint, data):
        if (len(data) < 8):
            log.warn("Unable to decode log message (length %d is less than 8)" % len(data))
            return

        if self.print_pbl_logs:
            timestamp, str_level, filename, linenumber, message = self._parse_log_response(data)

            log.info("{} {} {} {} {}".format(timestamp, str_level, filename, linenumber, message))

    def _print_crash_message(self, crashed_uuid, crashed_pc, crashed_lr):
        # Read the current projects UUID from it's appinfo.json. If we can't do this or the uuid doesn't match
        # the uuid of the crashed app we don't print anything.
        from PblProjectCreator import check_project_directory, PebbleProjectException
        try:
            check_project_directory()
        except PebbleProjectException:
            # We're not in the project directory
            return

        with open('appinfo.json', 'r') as f:
            try:
                app_info = json.load(f)
                app_uuid = uuid.UUID(app_info['uuid'])
            except ValueError as e:
                log.warn("Could not look up debugging symbols.")
                log.warn("Failed parsing appinfo.json")
                log.warn(str(e))
                return

        if (app_uuid != crashed_uuid):
            # Someone other than us crashed, just bail
            return


        if not os.path.exists(APP_ELF_PATH):
            log.warn("Could not look up debugging symbols.")
            log.warn("Could not find ELF file: %s" % APP_ELF_PATH)
            log.warn("Please try rebuilding your project")
            return


        def print_register(register_name, addr_str):
            if (addr_str[0] == '?') or (int(addr_str, 16) > 0x20000):
                # We log '???' when the reigster isn't available

                # The firmware translates app crash addresses to be relative to the start of the firmware
                # image. We filter out addresses that are higher than 128k since we know those higher addresses
                # are most likely from the firmware itself and not the app

                result = '???'
            else:
                result = sh.arm_none_eabi_addr2line(addr_str, exe=APP_ELF_PATH).strip()

            log.warn("%24s %10s %s", register_name + ':', addr_str, result)

        print_register("Program Counter (PC)", crashed_pc)
        print_register("Link Register (LR)", crashed_lr)


    def _app_log_response(self, endpoint, data):
        if (len(data) < 8):
            log.warn("Unable to decode log message (length %d is less than 8)" % len(data))
            return

        app_uuid = uuid.UUID(bytes=data[0:16])
        timestamp, str_level, filename, linenumber, message = self._parse_log_response(data[16:])

        log.info("{} {}:{} {}".format(str_level, filename, linenumber, message))

        # See if the log message we printed matches the message we print when we crash. If so, try to provide
        # some additional information by looking up the filename and linenumber for the symbol we crasehd at.
        m = re.search('App fault! ({[0-9a-fA-F\-]+}) PC: (\S+) LR: (\S+)', message)
        if m:
            crashed_uuid_str = m.group(1)
            crashed_uuid = uuid.UUID(crashed_uuid_str)

            self._print_crash_message(crashed_uuid, m.group(2), m.group(3))

    def _appbank_status_response(self, endpoint, data):
        def unpack_uuid(data):
            UUID_FORMAT = "{}{}{}{}-{}{}-{}{}-{}{}-{}{}{}{}{}{}"
            uuid = unpack("!bbbbbbbbbbbbbbbb", data)
            uuid = ["%02x" % (x & 0xff) for x in uuid]
            return UUID_FORMAT.format(*uuid)
        apps = {}
        restype, = unpack("!b", data[0])

        app_install_message = {
                0: "app available",
                1: "app removed",
                2: "app updated"
        }

        if restype == 1:
            apps["banks"], apps_installed = unpack("!II", data[1:9])
            apps["apps"] = []

            appinfo_size = 78
            offset = 9
            for i in xrange(apps_installed):
                app = {}
                try:
                    app["id"], app["index"], app["name"], app["company"], app["flags"], app["version"] = \
                            unpack("!II32s32sIH", data[offset:offset+appinfo_size])
                    app["name"] = app["name"].replace("\x00", "")
                    app["company"] = app["company"].replace("\x00", "")
                    apps["apps"] += [app]
                except:
                    if offset+appinfo_size > len(data):
                        log.warn("Couldn't load bank %d; remaining data = %s" % (i,repr(data[offset:])))
                    else:
                        raise
                offset += appinfo_size

            return apps

        elif restype == 2:
            message_id = unpack("!I", data[1:])
            message_id = int(''.join(map(str, message_id)))
            return app_install_message[message_id]

        elif restype == 5:
            apps_installed = unpack("!I", data[1:5])[0]
            uuids = []

            uuid_size = 16
            offset = 5
            for i in xrange(apps_installed):
                uuid = unpack_uuid(data[offset:offset+uuid_size])
                offset += uuid_size
                uuids.append(uuid)
            return uuids

        elif restype == 6:
            app = {}
            app["version"], app["name"], app["company"] = unpack("H32s32s", data[1:])
            app["name"] = app["name"].replace("\x00", "")
            app["company"] = app["company"].replace("\x00", "")
            return app

        elif restype == 7:
            uuid = unpack_uuid(data[1:17])
            return uuid

        else:
            return restype

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
                "CSTRING": b'\x01',
                "UINT": b'\x02',
                "INT": b'\x03'
        }

        # build the message_tuple
        app_message_tuple = OrderedDict([
                ("KEY", pack('<L', key)),
                ("TYPE", tuple_datatypes[data_type]),
                ("LENGTH", pack('<H', len(data))),
                ("DATA", data)
        ])

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


class WSClient(object):
    states = {
      "IDLE": 0,
      "LISTENING": 1,
    }

    def __init__(self):
      self._state = self.states["IDLE"]
      self._response = None
      self._topic = None
      self._received = False
      self._error = False
      self._timer = threading.Timer(30.0, self.timeout)

    def timeout(self):
      if (self._state != self.states["LISTENING"]):
        log.error("Timeout triggered when not listening")
        return
      self._error = True
      self._received = False
      self._state = self.states["IDLE"]

    def listen(self):
      self._state = self.states["LISTENING"]
      self._received = False
      self._error = False
      self._timer.start()

    def handle_response(self, topic, response):
      if self._state != self.states["LISTENING"]:
        log.debug("Unexpected status message")
        self._error = True

      self._timer.cancel()
      self._topic = topic
      self._response = response;
      self._received = True


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
        self._pebble._send_message("PUTBYTES", msgdata)
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
