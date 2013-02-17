import argparse
import pebble as libpebble
import code
import readline
import rlcompleter

def start_repl(pebble_id):
    pebble = libpebble.Pebble(pebble_id)
    readline.set_completer(rlcompleter.Completer(locals()).complete)
    readline.parse_and_bind('tab:complete')
    code.interact(local=locals())

parser = argparse.ArgumentParser(description='An interactive environment for libpebble.')
parser.add_argument('pebble_id', metavar='PEBBLE_ID', type=str, help='the last 4 digits of the target Pebble\'s MAC address')
args = parser.parse_args()

start_repl(args.pebble_id)
