libpebble
=========

Interact with your Pebble from any device. Currently tested on OS X, should also work on Linux and Windows though. You'll need PySerial installed.


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
* Getting device data (serial, BT MAC etc)

Thanks
------

* Pebble for making an awesome watch.
* RaYmAn for helping me figure out how the PutBytesClient worked.
* Overv for helping me pick apart the Android different message factories in the Android app.
