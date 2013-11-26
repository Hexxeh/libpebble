#!/usr/bin/env python

import argparse
import os
import pebble as libpebble
import subprocess
import sys
import time

MAX_ATTEMPTS = 5

def cmd_ping(pebble, args):
    pebble.ping(cookie=0xDEADBEEF)

def cmd_load(pebble, args):
    pebble.install_app(args.app_bundle, args.nolaunch)

def cmd_load_fw(pebble, args):
    pebble.install_firmware(args.fw_bundle)
    time.sleep(5)
    print 'resetting to apply firmware update...'
    pebble.reset()

def cmd_launch_app(pebble, args):
    pebble.launcher_message(args.app_uuid, "RUNNING")

def cmd_app_msg_send_string(pebble, args):
		pebble.app_message_send_string(args.app_uuid, args.key, args.tuple_string)

def cmd_app_msg_send_uint(pebble, args):
		pebble.app_message_send_uint(args.app_uuid, args.key, args.tuple_uint)

def cmd_app_msg_send_int(pebble, args):
		pebble.app_message_send_int(args.app_uuid, args.key, args.tuple_int)

def cmd_app_msg_send_bytes(pebble, args):
		pebble.app_message_send_byte_array(args.app_uuid, args.key, args.tuple_bytes)

def cmd_remote(pebble, args):
    def do_oscacript(command):
        cmd = "osascript -e 'tell application \""+args.app_name+"\" to "+command+"'"
        try:
            return subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError:
            print "Failed to send message to "+args.app_name+", is it running?"
            return False

    def music_control_handler(endpoint, resp):
        events = {
            "PLAYPAUSE": "playpause",
            "PREVIOUS": "previous track",
            "NEXT": "next track"
        }
        do_oscacript(events[resp])
        update_metadata()

    def update_metadata():
        artist = do_oscacript("artist of current track as string")
        title = do_oscacript("name of current track as string")
        album = do_oscacript("album of current track as string")

        if not artist or not title or not album:
            pebble.set_nowplaying_metadata("No Music Found", "", "")
        else:
            pebble.set_nowplaying_metadata(title, album, artist)

    pebble.register_endpoint("MUSIC_CONTROL", music_control_handler)

    print 'waiting for music control events'
    try:
        while True:
            update_metadata()
            time.sleep(5)
    except KeyboardInterrupt:
        return

def cmd_logcat(pebble, args):
    print 'listening for logs...'
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return

def cmd_list_apps(pebble, args):
    apps = pebble.get_appbank_status()
    if apps is not False:
        for app in apps['apps']:
            print '[{}] {}'.format(app['index'], app['name'])
    else:
        print "no apps"

def cmd_rm_app(pebble, args):
    try:
        uuid = args.app_index_or_hex_uuid.decode('hex')
        if len(uuid) == 16:
            pebble.remove_app_by_uuid(uuid, uuid_is_string=False)
            print 'removed app'
            return 0
    except:
        pass
    try:
        idx = int(args.app_index_or_hex_uuid)
        for app in pebble.get_appbank_status()['apps']:
            if app['index'] == idx:
                pebble.remove_app(app["id"], app["index"])
                print 'removed app'
                return 0
    except:
        print 'Invalid arguments. Use bank index or hex app UUID (16 bytes / 32 hex digits)'

def cmd_reinstall_app(pebble, args):
    pebble.reinstall_app(args.app_bundle, args.nolaunch)

def cmd_reset(pebble, args):
    pebble.reset()

def cmd_set_nowplaying_metadata(pebble, args):
    pebble.set_nowplaying_metadata(args.track, args.album, args.artist)

def cmd_notification_email(pebble, args):
    pebble.notification_email(args.sender, args.subject, args.body)

def cmd_notification_sms(pebble, args):
    pebble.notification_sms(args.sender, args.body)

def cmd_get_time(pebble, args):
    print pebble.get_time()

def cmd_set_time(pebble, args):
    pebble.set_time(args.timestamp)

def cmd_set_time_now(pebble, args):
    pebble.set_time(time.time() - time.timezone + time.daylight*3600)

def cmd_set_time_mdyhms(pebble, args):
    t = time.strptime(args.mdyhms,"%m/%d/%Y %H:%M:%S")
    pebble.set_time(time.mktime(t) - time.timezone)

def main():
    parser = argparse.ArgumentParser(description='a utility belt for pebble development')
    parser.add_argument('--pebble_id', type=str, help='the last 4 digits of the target Pebble\'s MAC address. \nNOTE: if \
                        --lightblue is set, providing a full MAC address (ex: "A0:1B:C0:D3:DC:93") won\'t require the pebble \
                        to be discoverable and will be faster')

    parser.add_argument('--lightblue', action="store_true", help='use LightBlue bluetooth API')
    parser.add_argument('--pair', action="store_true", help='pair to the pebble from LightBlue bluetooth API before connecting.')

    subparsers = parser.add_subparsers(help='commands', dest='which')

    ping_parser = subparsers.add_parser('ping', help='send a ping message')
    ping_parser.set_defaults(func=cmd_ping)

    launch_parser = subparsers.add_parser('launch_app', help='launch an app on the watch by its UUID')
    launch_parser.add_argument('app_uuid', metavar='UUID', type=str, help='a valid UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C')
    launch_parser.set_defaults(func=cmd_launch_app)

    msg_send_string_parser = subparsers.add_parser('msg_send_string', help='sends a string via app message')
    msg_send_string_parser.add_argument('app_uuid', metavar='UUID', type=str, help='a valid UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C')
    msg_send_string_parser.add_argument('key', type=int, help='a valid tuple key for the app')
    msg_send_string_parser.add_argument('tuple_string', type=str, help='a string to send along')
    msg_send_string_parser.set_defaults(func=cmd_app_msg_send_string)

    msg_send_int_parser = subparsers.add_parser('msg_send_int', help='sends an int via app message')
    msg_send_int_parser.add_argument('app_uuid', metavar='UUID', type=str, help='a valid UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C')
    msg_send_int_parser.add_argument('key', type=int, help='a valid tuple key for the app')
    msg_send_int_parser.add_argument('tuple_int', type=int, help='an int to send along')
    msg_send_int_parser.set_defaults(func=cmd_app_msg_send_int)

    msg_send_uint_parser = subparsers.add_parser('msg_send_uint', help='sends a uint via app message')
    msg_send_uint_parser.add_argument('app_uuid', metavar='UUID', type=str, help='a valid UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C')
    msg_send_uint_parser.add_argument('key', type=int, help='a valid tuple key for the app')
    msg_send_uint_parser.add_argument('tuple_uint', type=int, help='a uint to send along')
    msg_send_uint_parser.set_defaults(func=cmd_app_msg_send_uint)

    msg_send_bytes_parser = subparsers.add_parser('msg_send_bytes', help='sends a byte array via app message')
    msg_send_bytes_parser.add_argument('app_uuid', metavar='UUID', type=str, help='a valid UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C')
    msg_send_bytes_parser.add_argument('key', type=int, help='a valid tuple key for the app')
    msg_send_bytes_parser.add_argument('tuple_bytes', type=str, help='a byte array to send along')
    msg_send_bytes_parser.set_defaults(func=cmd_app_msg_send_bytes)

    load_parser = subparsers.add_parser('load', help='load an app onto a connected watch')
    load_parser.add_argument('--nolaunch', action="store_false", help='do not launch the application after install')
    load_parser.add_argument('app_bundle', metavar='FILE', type=str, help='a compiled app bundle')
    load_parser.set_defaults(func=cmd_load)

    load_fw_parser = subparsers.add_parser('load_fw', help='load new firmware onto a connected watch')
    load_fw_parser.add_argument('fw_bundle', metavar='FILE', type=str, help='a compiled app bundle')
    load_fw_parser.set_defaults(func=cmd_load_fw)

    logcat_parser = subparsers.add_parser('logcat', help='view logs sent from a connected watch')
    logcat_parser.set_defaults(func=cmd_logcat)

    list_apps_parser = subparsers.add_parser('list', help='list installed apps')
    list_apps_parser.set_defaults(func=cmd_list_apps)

    rm_app_parser = subparsers.add_parser('rm', help='remove installed app')
    rm_app_parser.add_argument('app_index_or_hex_uuid', metavar='IDX or UUID in the form of: 54D3008F0E46462C995C0D0B4E01148C', type=str, help='the app index or UUID to delete')
    rm_app_parser.set_defaults(func=cmd_rm_app)

    reinstall_app_parser = subparsers.add_parser('reinstall', help='reinstall then launch an installed app')
    reinstall_app_parser.add_argument('app_bundle', metavar='FILE', type=str, help='a compiled app bundle')
    reinstall_app_parser.add_argument('--nolaunch', action="store_false", help='do not launch the application after install')
    reinstall_app_parser.set_defaults(func=cmd_reinstall_app)

    reset_parser = subparsers.add_parser('reset', help='reset the watch remotely')
    reset_parser.set_defaults(func=cmd_reset)

    set_nowplaying_metadata_parser = subparsers.add_parser('playing', help='set current music playing')
    set_nowplaying_metadata_parser.add_argument('track', type=str)
    set_nowplaying_metadata_parser.add_argument('album', type=str)
    set_nowplaying_metadata_parser.add_argument('artist', type=str)
    set_nowplaying_metadata_parser.set_defaults(func=cmd_set_nowplaying_metadata)

    notification_email_parser = subparsers.add_parser('email', help='send an "Email Notification"')
    notification_email_parser.add_argument('sender', type=str)
    notification_email_parser.add_argument('subject', type=str)
    notification_email_parser.add_argument('body', type=str)
    notification_email_parser.set_defaults(func=cmd_notification_email)

    notification_sms_parser = subparsers.add_parser('sms', help='send an "SMS Notification"')
    notification_sms_parser.add_argument('sender', type=str)
    notification_sms_parser.add_argument('body', type=str)
    notification_sms_parser.set_defaults(func=cmd_notification_sms)

    get_time_parser = subparsers.add_parser('get_time', help='get the time stored on a connected watch')
    get_time_parser.set_defaults(func=cmd_get_time)

    set_time_parser = subparsers.add_parser('set_time', help='set the time stored on a connected watch')
    set_time_parser.add_argument('timestamp', type=int, help='time stamp to be sent')
    set_time_parser.set_defaults(func=cmd_set_time)

    set_time_now_parser = subparsers.add_parser('set_time_now', help='set the time stored on a connected watch to the current time')
    set_time_now_parser.set_defaults(func=cmd_set_time_now)

    set_time_mdyhms_parser = subparsers.add_parser('set_time_mdyhms', help='set the time stored on a connected watch to the time in "mm/dd/yyyy hh:mm:ss"')
    set_time_mdyhms_parser.add_argument('mdyhms', type=str, help='eg. "04/20/2020 10:45:00"')
    set_time_mdyhms_parser.set_defaults(func=cmd_set_time_mdyhms)

    remote_parser = subparsers.add_parser('remote', help='control a music app on this PC using Pebble')
    remote_parser.add_argument('app_name', type=str, help='title of application to be controlled')
    remote_parser.set_defaults(func=cmd_remote)


    args = parser.parse_args()

    attempts = 0
    while True:
        if attempts > MAX_ATTEMPTS:
            raise 'Could not connect to Pebble'
        try:
            pebble_id = args.pebble_id
            if pebble_id is None and "PEBBLE_ID" in os.environ:
                pebble_id = os.environ["PEBBLE_ID"]
            pebble = libpebble.Pebble(pebble_id, args.lightblue, args.pair)
            break
        except:
            time.sleep(5)
            attempts += 1

    try:
        args.func(pebble, args)
    except Exception as e:
        pebble.disconnect()
        raise e
        return

    pebble.disconnect()

if __name__ == '__main__':
    main()
