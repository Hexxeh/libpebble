#!/usr/bin/env python

import argparse
import pebble as libpebble
import code
import readline
import rlcompleter

def start_repl(pebble_id, lightblue, pair):
    pebble = libpebble.Pebble(pebble_id, using_lightblue=lightblue, pair_first=pair)
    readline.set_completer(rlcompleter.Completer(locals()).complete)
    readline.parse_and_bind('tab:complete')
    code.interact(local=locals())

parser = argparse.ArgumentParser(description='An interactive environment for libpebble.')
parser.add_argument('pebble_id', metavar='PEBBLE_ID', type=str, help='the last 4 digits of the target Pebble\'s MAC address, or a complete MAC address')
parser.add_argument('--pair', action="store_true", help='pair to the pebble from LightBlue bluetooth API before connecting.')
parser.add_argument('--lightblue', action="store_true", help='use LightBlue bluetooth API')
args = parser.parse_args()

start_repl(args.pebble_id, args.lightblue, args.pair)
