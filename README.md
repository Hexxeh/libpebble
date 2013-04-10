libpebble
=========
Interact with your Pebble from OSX, Ubuntu or Debian operating systems.

###General Dependancies
The following dependancies should be installed regardless of the Operating System:

_Python_
* `python 2.7`

_Lightblue:_
* `lightblue-0.4` from `https://github.com/pebble/lightblue-0.4`
    * `cd lightblue-0.4`
    * `sudo python setup.py install`

Getting started - Mac OSX
-------------------------
When using libpebble on OSX, it is recommended that `--lightblue` be utilized.

###Additional Dependencies
* `PyObjC` which can be installed via [pip](https://pypi.python.org/pypi/pip)
* `Xcode 2.1 or later` to build LightAquaBlue framework
* OSX 10.4 or later to perform MAC Address discovery

###Interacting with a Pebble
* First install the general dependancies and LightBlue
* From the `libpebble-dev` folder, execute the following: `./p.py --lightblue --pair get_time`
* Note that if no --pebble_id is specified before the command, you are provided with a GUI selection tool.
* Note that if a MAC address is supplied, initialization time is reduced. 
    * For example:  `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue get_time`
      where `00:11:22:33:44:55:66` is the Pebble's MAC Address, viewable on the Pebble from `settings`-->`about`
* The `--pebble_id` can also be the 4 letter friendly name of your pebble but this will require that the Pebble is broadcasting.

###Using libpebble without --lightblue on OSX
_NOT RECOMMENDED. MAY CAUSE KERNEL PANICS ON OSX 10.8.X_

* Pair your Pebble to your computer and make sure it's setup as a serial port. For example it could be exposed as `/dev/tty.Pebble123A-SerialPortSe`. You can accomplish this by using OSX's pairing utility in `System Preferences` --> `Bluetooth` -> `+` --> selecting your pebble `Pebble XXXX` then confirming the pairing code on the Pebble.
* Once you're paired and the serial port is setup, you can execute commands without the `--lightblue` flag, just ensure that the `--pebble_id` is the 4 letter friendly name of your Pebble, `123A` for example.
* A command to get the time might be: `./p.py --pebble_id 123A get_time`

Getting started - Ubuntu
------------------------
###Extra Dependancies
Installing lightblue-0.4 in Ubuntu requires some extra dependancies be installed via `apt-get install`:
* `python-dev`
* `libopenobex1-dev`
* `python-tk` if you wish to use the GUI selection tool

###Interacting with a Pebble

_Automated pairing via `--pair` on linux is not currently supported_

* First install the Ubuntu dependancies, general dependancies and lightblue
* In Ubuntu's `Menu`-->`Settings`-->`Connectivity`-->`Bluetooth` dialog, pair with your Pebble
* From the `libpebble-dev` folder, execute the following: `./p.py --lightblue get_time`
* Note that if no `--pebble_id` is specified before the command, you are provided with a GUI selection tool.
* For example: `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue get_time`
* The `--pebble_id` can also be the 4 letter firendly name of your pebble but this will still be slower than passing the MAC Address.

Getting started - Debian
------------------------

**Please note the following was tested on Linux Mint 13, but should be valid for any Debian based distro**

###Extra Dependancies
* Install rfcomm `sudo apt-get install rfcomm`
* Bind the device `sudo rfcomm bind 0 PEBBLE_BLUETOOTH_ADDRESS 1`
* Make the following code change to `pebble/pebble.py`:

Change:

    self._ser = serial.Serial("/dev/tty.Pebble"+id+"-SerialPortSe", 115200, timeout=2)

to: 

    self._ser = serial.Serial("/dev/rfcomm0", 115200, timeout=2)

Note that you may have to run libpebble as root with `sudo python pebble.py`

###Interacting with a Pebble
* `./p.py --pebble_id 123A get_time`

Status
------

The following are currently supported:


* Installing applications
* Installing firmware
* Sending application messages
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
