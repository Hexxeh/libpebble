#!/usr/bin/env python
import logging
import multiprocessing
import os
import Queue
import re
import socket
from multiprocessing import Process
from struct import unpack

log = logging.getLogger()
logging.basicConfig(format='[%(levelname)-8s] %(message)s')
log.setLevel(logging.DEBUG)

class LightBluePebbleError(Exception):
    def __init__(self, id, message):
        self._id = id
        self._message = message

    def __str__(self):
        return "%s ID:(%s) on LightBlue API" % (self._message, self._id)

class LightBluePebble(object):
    """ a wrapper for LightBlue that provides Serial-style read, write and close"""

    def __init__(self, id, should_pair, debug_protocol=False, connection_process_timeout=60):

        self.mac_address = id
        self.debug_protocol = debug_protocol
        self.should_pair = should_pair

        manager = multiprocessing.Manager()
        self.send_queue = manager.Queue()
        self.rec_queue = manager.Queue()

        self.bt_teardown = multiprocessing.Event()
        self.bt_message_sent = multiprocessing.Event()
        self.bt_connected = multiprocessing.Event()

        self.bt_socket_proc = Process(target=self.run)
        self.bt_socket_proc.daemon = True
        self.bt_socket_proc.start()

        # wait for a successful connection from child process before returning to main process
        self.bt_connected.wait(connection_process_timeout)
        if not self.bt_connected.is_set():
            raise LightBluePebbleError(id, "Connection timed out, LightBlueProcess was provided %d seconds to complete connecting" % connection_process_timeout)

    def write(self, message):
        """ send a message to the LightBlue processs"""
        try:
            self.send_queue.put(message)
            self.bt_message_sent.wait()
        except:
            self.bt_teardown.set()
            if self.debug_protocol:
                log.debug("LightBlue process has shutdown (queue write)")

    def read(self):
        """ read a pebble message from the LightBlue processs"""
        try:
            return self.rec_queue.get()
        except Queue.Empty:
            return (None, None, '')
        except:
            self.bt_teardown.set()
            if self.debug_protocol:
                log.debug("LightBlue process has shutdown (queue read)")
            return (None, None, '')

    def close(self):
        """ close the LightBlue connection process"""
        self.bt_teardown.set()

    def is_alive(self):
        return self.bt_socket_proc.is_alive()

    def run(self):
        """ create bluetooth process paired to mac_address, must be run as a process"""
        from lightblue import pair, socket as lb_socket, finddevices, selectdevice

        def autodetect(self):
            list_of_pebbles = list()

            if self.mac_address is not None and len(self.mac_address) is 4:
                # we have the friendly name, let's get the full mac address
                log.warn("Going to get full address for device %s, ensure device is broadcasting." % self.mac_address)
                # scan for active devices
                devices = finddevices(timeout=8)

                for device in devices:
                    if re.search(r'Pebble ' + self.mac_address, device[1], re.IGNORECASE):
                        log.debug("Found Pebble: %s @ %s" % (device[1], device[0]))
                        list_of_pebbles.append(device)

                if len(list_of_pebbles) is 1:
                    return list_of_pebbles[0][0]
                else:
                    raise LightBluePebbleError(self.mac_address, "Failed to find Pebble")
            else:
                # no pebble id was provided... give them the GUI selector
                try:
                    return selectdevice()[0]
                except TypeError:
                    log.warn("failed to select a device in GUI selector")
                    self.mac_address = None

        # notify that the process has started
        log.debug("LightBlue process has started on pid %d" % os.getpid())

        # do we need to autodetect?
        if self.mac_address is None or len(self.mac_address) is 4:
            self.mac_address = autodetect(self)

        # create the bluetooth socket from the mac address
        if self.should_pair and self.mac_address is not None:
            pair(self.mac_address)
        try:
            self._bts = lb_socket()
            self._bts.connect((self.mac_address, 1))  # pebble uses RFCOMM port 1
            self._bts.setblocking(False)
        except:
            raise LightBluePebbleError(self.mac_address, "Failed to connect to Pebble")

        # give them the mac address for using in faster connections
        log.debug("Connection established to " + self.mac_address)

        # Tell our parent that we have a pebble connected now
        self.bt_connected.set()

        send_data = e = None
        while not self.bt_teardown.is_set():
            # send anything in the send queue
            try:
                send_data = self.send_queue.get_nowait()
                self._bts.send(send_data)
                if self.debug_protocol:
                    log.debug("LightBlue Send: %r" % send_data)
                self.bt_message_sent.set()
            except Queue.Empty:
                pass
            except (IOError, EOFError):
                self.bt_teardown.set()
                e = "Queue Error while sending data"

            # if anything is received relay it back
            rec_data = None
            try:
                rec_data = self._bts.recv(4)
            except (socket.timeout, socket.error):
                # Exception raised from timing out on nonblocking
                pass

            if (rec_data is not None) and (len(rec_data) == 4):
                # check the Stream Multiplexing Layer message and get the length of the data to read
                size, endpoint = unpack("!HH", rec_data)
                resp = self._bts.recv(size)
                try:
                    self.rec_queue.put((endpoint, resp, rec_data))
                except (IOError, EOFError):
                    self.BT_TEARDOWN.set()
                    e = "Queue Error while recieving data"
                    pass
                if self.debug_protocol:
                    log.debug("LightBlue Read: %r " % resp)

        # just let it die silent whenever the parent dies and it throws an EOFERROR
        if e is not None and self.debug_protocol:
            raise LightBluePebbleError(self.mac_address, "LightBlue polling loop closed due to " + e)
