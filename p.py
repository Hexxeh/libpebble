#!/usr/bin/env python

import argparse
import pebble as libpebble
import sys
import time

def cmd_ping(pebble, args):
    pebble.ping(cookie=0xDEADBEEF)

def cmd_load(pebble, args):
    pebble.install_app(args.watch_app)

def cmd_logcat(pebble, args):
    print 'Listening for logs...'
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

            print 'Removed app'
            return

def main():
    add_pbl_id_arg = lambda x: x.add_argument('pebble_id', metavar='PEBBLE_ID', type=str, help='the last 4 digits of the target Pebble\'s MAC address')

    parser = argparse.ArgumentParser(description='a utility belt for pebble development')

    subparsers = parser.add_subparsers(help='commands', dest='which')

    ping_parser = subparsers.add_parser('ping', help='send a ping message')
    add_pbl_id_arg(ping_parser)
    ping_parser.set_defaults(func=cmd_ping)

    load_parser = subparsers.add_parser('load', help='load an app onto a connected watch')
    add_pbl_id_arg(load_parser)
    load_parser.add_argument('watch_app', metavar='FILE', type=str, help='a compiled app bundle')
    load_parser.set_defaults(func=cmd_load)

    logcat_parser = subparsers.add_parser('logcat', help='view logs sent from the connected watch')
    add_pbl_id_arg(logcat_parser)
    logcat_parser.set_defaults(func=cmd_logcat)

    list_apps_parser = subparsers.add_parser('list', help='list installed apps')
    add_pbl_id_arg(list_apps_parser)
    list_apps_parser.set_defaults(func=cmd_list_apps)

    rm_app_parser = subparsers.add_parser('rm', help='remove installed apps')
    add_pbl_id_arg(rm_app_parser)
    rm_app_parser.add_argument('app_index', metavar='IDX', type=int, help='the app index to delete')
    rm_app_parser.set_defaults(func=cmd_rm_app)

    args = parser.parse_args()
    pebble = libpebble.Pebble(args.pebble_id)
    args.func(pebble, args)

if __name__ == '__main__':
    main()
