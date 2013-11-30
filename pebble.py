#!/usr/bin/env python

import argparse
import logging
import sys

import pebble.PblAnalytics as PblAnalytics

# Catch any missing python dependencies so we can send an event to analytics
try:
    import pebble as libpebble
    from pebble.PblProjectCreator   import (PblProjectCreator, 
                                            InvalidProjectException, 
                                            OutdatedProjectException)
    from pebble.PblProjectConverter import PblProjectConverter
    from pebble.PblBuildCommand     import PblBuildCommand, PblCleanCommand
    from pebble.LibPebblesCommand   import *
except Exception as e:
    logging.basicConfig(format='[%(levelname)-8s] %(message)s', 
                    level = logging.DEBUG)
    PblAnalytics.missing_python_dependency_evt(str(e))
    raise

class PbSDKShell:
    commands = []

    def __init__(self):
        self.commands.append(PblProjectCreator())
        self.commands.append(PblProjectConverter())
        self.commands.append(PblBuildCommand())
        self.commands.append(PblCleanCommand())
        self.commands.append(PblInstallCommand())
        self.commands.append(PblInstallFWCommand())
        self.commands.append(PblPingCommand())
        self.commands.append(PblListCommand())
        self.commands.append(PblRemoteCommand())
        self.commands.append(PblRemoveCommand())
        self.commands.append(PblCurrentAppCommand())
        self.commands.append(PblListUuidCommand())
        self.commands.append(PblLogsCommand())
        self.commands.append(PblReplCommand())
        self.commands.append(PblScreenshotCommand())
        self.commands.append(PblLaunchApp())

    def _get_version(self):
        try:
            from pebble.VersionGenerated import SDK_VERSION
            return SDK_VERSION
        except:
            return "'Development'"
        

    def main(self):
        parser = argparse.ArgumentParser(description = 'Pebble SDK Shell')
        parser.add_argument('--debug', action="store_true", 
                            help="Enable debugging output")
        parser.add_argument('--version', action='version', 
                            version='PebbleSDK %s' % self._get_version())
        subparsers = parser.add_subparsers(dest="command", title="Command", 
                                           description="Action to perform")
        for command in self.commands:
            subparser = subparsers.add_parser(command.name, help = command.help)
            command.configure_subparser(subparser)
        args = parser.parse_args()

        log_level = logging.INFO
        if args.debug:
            log_level = logging.DEBUG

        logging.basicConfig(format='[%(levelname)-8s] %(message)s', 
                            level = log_level)

        return self.run_action(args.command, args)

    def run_action(self, action, args):
        # Find the extension that was called
        command = [x for x in self.commands if x.name == args.command][0]

        try:
            retval = command.run(args)
            if retval:
                PblAnalytics.cmd_fail_evt(args.command, 'unknown error')
            else:
                cmdName = args.command
                if cmdName == 'install' and args.logs is True:
                    cmdName = 'install --logs'
                PblAnalytics.cmd_success_evt(cmdName)
            return retval
                
        except libpebble.PebbleError as e:
            PblAnalytics.cmd_fail_evt(args.command, 'pebble error')
            if args.debug:
                raise e
            else:
                logging.error(e)
                return 1
            
        except ConfigurationException as e:
            PblAnalytics.cmd_fail_evt(args.command, 'configuration error')
            logging.error(e)
            return 1
        
        except InvalidProjectException as e:
            PblAnalytics.cmd_fail_evt(args.command, 'invalid project')
            logging.error("This command must be run from a Pebble project "
                          "directory")
            return 1
        
        except OutdatedProjectException as e:
            PblAnalytics.cmd_fail_evt(args.command, 'outdated project')
            logging.error("The Pebble project directory is using an outdated "
                          "version of the SDK!")
            logging.error("Try running `pebble convert-project` to update the "
                          "project")
            return 1
        
        except NoCompilerException as e:
            PblAnalytics.missing_tools_evt()
            logging.error("The compiler/linker tools could not be found. "
                          "Insure that the arm-cs-tools directory is present "
                          "in the Pebble SDK directory (%s)" % 
                          PblCommand().sdk_path(args))
            return 1
        
        except BuildErrorException as e:
            PblAnalytics.cmd_fail_evt(args.command, 'compilation error')
            logging.error("A compilation error occurred")
            return 1
        
        except AppTooBigException as e:
            PblAnalytics.cmd_fail_evt(args.command, 'application too big')
            logging.error("The built application is too big")
            return 1
        
        except Exception as e:
            PblAnalytics.cmd_fail_evt(args.command, 'unhandled exception: %s' %
                                 str(e))
            logging.error(str(e))
            return 1


if __name__ == '__main__':
    retval = PbSDKShell().main()
    if retval is None:
        retval = 0
    sys.exit(retval)

