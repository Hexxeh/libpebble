import errno
import sys
import logging
from websocket import *
from struct import unpack
from struct import pack

# This file contains the libpebble websocket client.
# Based on websocket.py from:
# https://github.com/liris/websocket-client

WS_CMD_WATCH_TO_PHONE = 0x00
WS_CMD_PHONE_TO_WATCH = 0x01
WS_CMD_PHONE_APP_LOG = 0x02
WS_CMD_SERVER_LOG = 0x03
WS_CMD_APP_INSTALL = 0x04
WS_CMD_STATUS = 0x5
WS_CMD_PHONE_INFO = 0x06

class WebSocketPebble(WebSocket):

######## libPebble Bridge Methods #########

    def write(self, payload, opcode = ABNF.OPCODE_BINARY, ws_cmd = WS_CMD_PHONE_TO_WATCH):
        """
        BRIDGES THIS METHOD:
        def write(self, message):
            try:
                self.send_queue.put(message)
                self.bt_message_sent.wait()
            except:
                self.bt_teardown.set()
                if self.debug_protocol:
                    log.debug("LightBlue process has shutdown (queue write)")

        """
        # Append command byte to the payload:
        payload = pack("B", ws_cmd) + payload
        frame = ABNF.create_frame(payload, opcode)
        if self.get_mask_key:
            frame.get_mask_key = self.get_mask_key
        data = frame.format()

        sent = 0
        while sent < len(data):
            sent += self.sock.send(data[sent:])
            if traceEnabled:
                logging.debug('send>>> ' + data.encode('hex'))

    def read(self):
        """
        BRIDGES THIS METHOD:
        def read(self):
            try:
                return self.rec_queue.get()
            except Queue.Empty:
                return (None, None, '')
            except:
                self.bt_teardown.set()
                if self.debug_protocol:
                    log.debug("LightBlue process has shutdown (queue read)")
                return (None, None, '')
                
        NOTE: The return value of this method was modified from 3 tuples to
        4 tuples in order to support multiple possible WS_CMD id's besides
        just WS_CMD_WATCH_TO_PHONE and WS_CMD_STATUS. Now, the first item in
        the tuple (source) identifies which WS_CMD we received. The other
        transports (LightBlue, etc.), if/when they are re-instantiated into
        active use will have to be updated to return this new 4 item tuple. 
                
        retval:   (source, topic, response, data)
            source can be either 'ws' or 'watch'
            if source is 'watch', then topic is the endpoint identifier
            if source is 'ws', then topic is either 'status','phoneInfo',
                    or 'log'
            
        """
        opcode, data = self.recv_data()
        ws_cmd = unpack('!b',data[0])
        if ws_cmd[0]==WS_CMD_SERVER_LOG:
            logging.debug("Server: %s" % repr(data[1:]))
        if ws_cmd[0]==WS_CMD_PHONE_APP_LOG:
            logging.debug("Log: %s" % repr(data[1:]))
            return ('ws', 'log', data[1:], data)
        if ws_cmd[0]==WS_CMD_PHONE_TO_WATCH:
            logging.debug("Phone ==> Watch: %s" % data[1:].encode("hex"))
        if ws_cmd[0]==WS_CMD_WATCH_TO_PHONE:
            logging.debug("Watch ==> Phone: %s" % data[1:].encode("hex"))
            size, endpoint = unpack("!HH", data[1:5])
            resp = data[5:]
            return ('watch', endpoint, resp, data[1:5])
        if ws_cmd[0]==WS_CMD_STATUS:
            logging.debug("Status: %s" % repr(data[1:]))
            status = unpack("I", data[1:5])[0]
            return ('ws', 'status', status, data[1:5])
        if ws_cmd[0]==WS_CMD_PHONE_INFO:
            logging.debug("Phone info: %s" % repr(data[1:]))
            response = data[1:]
            return ('ws', 'phoneInfo', response, data)
        else:
            return (None, None, None, data)



######################################

def create_connection(host, port=9000, timeout=None, connect_timeout=None, **options):
    """
    connect to ws://host:port and return websocket object.

    Connect to ws://host:port and return the WebSocket object.
    Passing optional timeout parameter will set the timeout on the socket.
    If no timeout is supplied, the global default timeout setting returned by getdefauttimeout() is used.
    You can customize using 'options'.
    If you set "header" dict object, you can set your own custom header.

    >>> conn = create_connection("ws://echo.websocket.org/",
         ...     header=["User-Agent: MyProgram",
         ...             "x-custom: header"])


    timeout: socket timeout time. This value is integer.
             if you set None for this value, it means "use default_timeout value"

    options: current support option is only "header".
             if you set header as dict value, the custom HTTP headers are added.
    """

    url = "ws://{}:{}".format(host, port)
    try:
        sockopt = options.get("sockopt", ())
        websock = WebSocketPebble(sockopt=sockopt)
        websock.settimeout(connect_timeout is not None and connect_timeout or default_timeout)
        websock.connect(url, **options)
        websock.settimeout(timeout is not None and timeout or default_timeout)
    except socket.timeout as e:
        logging.error("Could not connect to phone at {}:{}. Connection timed out".format(host, port))
        os._exit(-1)
    except socket.error as e:
        if e.errno == errno.ECONNREFUSED:
            logging.error("Could not connect to phone at {}:{}. "
                      "Ensure that 'Developer Connection' is enabled in the Pebble app.".format(host, port))
            os._exit(-1)
        else:
            raise e
    except WebSocketConnectionClosedException as e:
        logging.error("Connection was rejected. The Pebble app is already connected to another client.")
        os._exit(-1)
    return websock

_MAX_INTEGER = (1 << 32) -1
_AVAILABLE_KEY_CHARS = range(0x21, 0x2f + 1) + range(0x3a, 0x7e + 1)
_MAX_CHAR_BYTE = (1<<8) -1




if __name__ == "__main__":
    enableTrace(True)
    if len(sys.argv) < 2:
        print "Need the WebSocket server address, i.e. ws://localhost:9000"
        sys.exit(1)
    ws = create_connection(sys.argv[1])
    print("Sending 'Hello, World'...")
    ws.send("Hello, World")
    print("Sent")
    print("Receiving...")
    result = ws.recv()
    print("Received '%s'" % result)
