#!/usr/bin/env python

import argparse
import pebble as libpebble
import sys
import time

MAX_ATTEMPTS = 5

def cmd_ping(pebble, args):
    pebble.ping(cookie=0xDEADBEEF)

def cmd_load(pebble, args):
    pebble.install_app(args.app_bundle)

def cmd_load_fw(pebble, args):
    pebble.install_firmware(args.fw_bundle)
    time.sleep(5)
    print 'resetting to apply firmware update...'
    pebble.reset()

def cmd_logcat(pebble, args):
    print 'listening for logs...'
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return

def cmd_list_apps(pebble, args):
    for app in pebble.get_appbank_status()['apps']:
        print '[{}] {}'.format(app['index'], app['name'])

def cmd_rm_app(pebble, args):
    for app in pebble.get_appbank_status()['apps']:
        if app['index'] == args.app_index:
            pebble.remove_app(app["id"], app["index"])

            print 'removed app'
            return

def cmd_reset(pebble, args):
    pebble.reset()

def cmd_notification_email(pebble, args):
    pebble.notification_email(args.sender, args.subject, args.body)

def cmd_notification_sms(pebble, args):
    pebble.notification_sms(args.sender, args.body)

def cmd_get_time(pebble, args):
    print pebble.get_time()

def cmd_set_time(pebble, args):
    pebble.set_time(args.timestamp)

def main():
    parser = argparse.ArgumentParser(description='a utility belt for pebble development')
    parser.add_argument('--pebble_id', type=str, help='the last 4 digits of the target Pebble\'s MAC address')

    subparsers = parser.add_subparsers(help='commands', dest='which')

    ping_parser = subparsers.add_parser('ping', help='send a ping message')
    ping_parser.set_defaults(func=cmd_ping)

    load_parser = subparsers.add_parser('load', help='load an app onto a connected watch')
    load_parser.add_argument('app_bundle', metavar='FILE', type=str, help='a compiled app bundle')
    load_parser.set_defaults(func=cmd_load)

    load_fw_parser = subparsers.add_parser('load_fw', help='load new firmware onto a connected watch')
    load_fw_parser.add_argument('fw_bundle', metavar='FILE', type=str, help='a compiled app bundle')
    load_fw_parser.set_defaults(func=cmd_load_fw)

    logcat_parser = subparsers.add_parser('logcat', help='view logs sent from a connected watch')
    logcat_parser.set_defaults(func=cmd_logcat)

    list_apps_parser = subparsers.add_parser('list', help='list installed apps')
    list_apps_parser.set_defaults(func=cmd_list_apps)

    rm_app_parser = subparsers.add_parser('rm', help='remove installed apps')
    rm_app_parser.add_argument('app_index', metavar='IDX', type=int, help='the app index to delete')
    rm_app_parser.set_defaults(func=cmd_rm_app)

    reset_parser = subparsers.add_parser('reset', help='reset the watch remotely')
    reset_parser.set_defaults(func=cmd_reset)

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

    args = parser.parse_args()

    attempts = 0
    while True:
        if attempts > MAX_ATTEMPTS:
            raise 'Could not connect to Pebble'
        try:
            pebble = libpebble.Pebble(args.pebble_id)
            break
        except libpebble.PebbleError:
            time.sleep(5)
            attempts += 1

    args.func(pebble, args)

if __name__ == '__main__':
    main()
