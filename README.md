libpebble
=========

Interact with your Pebble from any device.

Getting started
---------------

I've only tested this on OS X 10.8. Things will be a little different on other platforms. Firstly make sure you have Python and PySerial installed.

Next, pair your Pebble to your computer and make sure it's setup as a serial port. For me, it gets exposed as /dev/tty.Pebble402F-SerialPortSe. If this is different for you, you'll need to edit pebble.py. The 402F bit is my Pebble's ID. You can just run pebble.py with your ID as an argument if the rest of that path matches.

Once you're paired and the serial port is setup, try running pebble.py. You should get a notification on your Pebble to test that it works properly.

Join #pebble on Freenode IRC to let me know how you get on and share your creations!

###Linux Notes

**Please note the following was tested on Linux Mint 13, but should be valid for any Debian based distro**

 * Install rfcomm `sudo apt-get install rfcomm`
 * Bind the device `sudo rfcomm bind 0 PEBBLE_BLUETOOTH_ADDRESS 1`
 * make the following code change:

Change:

    self._ser = serial.Serial("/dev/tty.Pebble"+id+"-SerialPortSe", 115200, timeout=2)

to: 

    self._ser = serial.Serial("/dev/rfcomm0", 115200, timeout=2)

You can run the application as normal now.  You may have to run it as root with `sudo python pebble.py`

Status
------

The following are currently supported:

* Pinging device
* Resetting device
* Setting/getting time
* Sending notifications
* Setting the currently playing track
* Listing installed apps
* Installing apps
* Deleting apps
* Getting the installed firmware versions
* Installing firmware
* Getting device data (serial, BT MAC etc)

REPL
----

A basic REPL is available, it is best used with ipython:

    `sudo ipython repl.py`

The variable pebble refers the watch connection.  You can for example do `pebble.ping()` to perform a ping.

Thanks
------

* Pebble for making an awesome watch.
* RaYmAn for helping me figure out how the PutBytesClient worked.
* Overv for helping me pick apart the Android different message factories in the Android app.
