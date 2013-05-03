libpebble
=========
Interact with your Pebble from OSX, Ubuntu or Debian operating systems.

## Warning and Complications

* Supported OSes are `OSX 10.8`, `Ubuntu`, `Debian`
* OSes which can utilize a faster Bluetooth library, Lightblue-0.4, are `OSX 10.8` and `Ubuntu`
* Detailed Lightblue-0.4 installation instructions for earlier version of OSX (10.6) and other OSes can be found [here](http://lightblue.sourceforge.net/#downloads)


##1. Install Dependencies

All supported OSes will require `python 2.7` to operate libpebble. It can be installed [here](http://www.python.org/download/releases/2.7/)
* `Pyserial`will also be required, is can be installed via [pip](https://pypi.python.org/pypi/pip)

###a. OSX Additional Dependencies

Installing Lightblue-0.4 in OSX will require the following be installed:
* `PyObjC` which can be installed via [pip](https://pypi.python.org/pypi/pip)
* `Xcode 2.1 or later` to build LightAquaBlue framework

###b. Ubuntu Additional Dependencies

Installing Lightblue-0.4 in Ubuntu requires some extra dependencies be installed via `apt-get install`:
* `python-dev`
* `libopenobex1-dev`
* `python-tk` if you wish to use the GUI selection tool

###c. Debian Additional Dependencies

Support for lightblue is untested in Debian, however the following should be installed/completed for use with PySerial:
* Install rfcomm `sudo apt-get install rfcomm`
* Bind the device `sudo rfcomm bind 0 PEBBLE_BLUETOOTH_ADDRESS 1`
* Make the following code change to `pebble/pebble.py`:
   Change:

    	self._ser = serial.Serial("/dev/tty.Pebble"+id+"-SerialPortSe", 115200, timeout=2)

	to: 

    	self._ser = serial.Serial("/dev/rfcomm0", 115200, timeout=2)

* Note that you may have to run libpebble as root with `sudo python pebble.py` in Debian


##2. Install Libpebble and Lightblue

* To install libpebble, clone the current libpebble with lightblue support from `git@github.com:pebble/libpebble.git` to a location of your choosing
* To install lightblue clone `lightblue-0.4` from `https://github.com/pebble/lightblue-0.4` and then:
    * `cd lightblue-0.4`
    * `sudo python setup.py install`
* _NOTE_ in OSX 10.8.3, you should instead clone `lightblue-0.4` from `https://github.com/pipt/lightblue-0.4` which contains some fixes. The installation steps are the same as with `pebble/libpebble.git` 


##3. Testing the Connection
Note: you should have your bluetooth module enabled before continuing

###a. OSX
When using libpebble on OSX, it is recommended that `--lightblue` be utilized.

#####Using libpebble with --lightblue on OSX
* First install the OSX dependencies, general dependencies and lightblue
* From the `libpebble-dev` folder, execute the following: `./p.py --lightblue --pair get_time`
* Note that if no `--pebble_id` is specified before the command, you are provided with a GUI selection tool.
* Note that if a MAC address is supplied, initialization time is reduced. 
    * For example:  `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue get_time`
      where `00:11:22:33:44:55:66` is the Pebble's MAC Address, viewable on the Pebble from `settings`-->`about`
* You can obtain your pebble's MAC address after a successful connection in the libpebble stdout debug logs
* The `--pebble_id` can also be the 4 letter friendly name of your pebble but this will require that the Pebble is broadcasting.
* It is also possible to set the PEBBLE_ID environment variable as well:

      export PEBBLE_ID="00:11:22:33:44:55:66"
      ./p.py --lightblue get_time

#####Using libpebble without --lightblue on OSX (MAY CAUSE KERNEL PANICS)

* Pair your Pebble to your computer and make sure it's setup as a serial port. For example it could be exposed as `/dev/tty.Pebble123A-SerialPortSe`. You can accomplish this by using OSX's pairing utility in `System Preferences` --> `Bluetooth` -> `+` --> selecting your pebble `Pebble XXXX` then confirming the pairing code on the Pebble.
* Once you're paired and the serial port is setup, you can execute commands without the `--lightblue` flag, just ensure that the `--pebble_id` is the 4 letter friendly name of your Pebble, `123A` for example.
* A command to get the time might be: `./p.py --pebble_id 123A get_time`

### b. Ubuntu

_Automated pairing via `--pair` is not currently supported in Ubuntu_

* First install the Ubuntu dependencies, general dependencies and lightblue
* In Ubuntu's `Menu`-->`Settings`-->`Connectivity`-->`Bluetooth` dialog, pair with your Pebble
* From the `libpebble-dev` folder, execute the following: `./p.py --lightblue get_time`
* Note that if no `--pebble_id` is specified before the command, you are provided with a GUI selection tool.
* For example: `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue get_time`
* The `--pebble_id` can also be the 4 letter friendly name of your pebble but this require that the Pebble is broadcasting.

## Applications
* Note that applications each have a unique UUID which is used to launch on install/re-install, it should be visible in the source for your application. 
* Once an application is installed or re-installed it will be launched automatically. Disable this with `--nolaunch`
	* for example `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue reinstall brains.pbw --nolaunch`

#####Installing:
* From your libpebble directory, execute `p.py` with the argument `load <path-to-valid-app>` 
	* for example: `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue load brains.pbw`

#####Re-installing
* To re-install an application, execute `p.py` with the argument `reinstall <path-to-valid-app>`. This will attempt to remove the application by its UUID or, if that fails, the name of the application before installing it once more.
	* for example: `./p.py --pebble_id 00:11:22:33:44:55:66 --lightblue reinstall brains.pbw`

Functionality
-------------

The following are currently supported:

* Sending email, sms and ping notifications
* Installing, reinstalling and uninstalling applications
* Installing firmwares
* Launching applications by UUID
* Sending application messages
* Resetting device
* Setting/getting time
* Sending notifications
* Setting the currently playing track
* Getting the installed firmware version
* Getting and setting the pebble's time

REPL
----

A basic REPL is available, it is best used with ipython:

    `sudo ipython repl.py`

The variable `pebble` refers to the watch connection.  You can for example perform `pebble.get_time()` to get the time of the watch
