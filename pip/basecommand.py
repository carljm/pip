
""" Base Command class, and related routines """

import os
import sys
import time
import copy
import socket
import optparse
import traceback

from pip.log import logger
from pip.download import urlopen
from pip.baseparser import ConfigOptionParser, UpdatingDefaultsHelpFormatter
from pip.exceptions import (BadCommand, InstallationError, UninstallationError,
                            CommandError)
from pip.backwardcompat import StringIO, walk_packages
from pip.status_codes import SUCCESS, ERROR, UNKNOWN_ERROR, VIRTUALENV_NOT_FOUND


__all__ = 'Command'

# for backwards compatibiliy
get_proxy = urlopen.get_proxy

class Command(object):
    name = None
    usage = None
    hidden = False

    def __init__(self, main_parser):
        assert self.name

        prog = os.path.basename(sys.argv[0])

        parser_kw = {
            'usage'             : self.usage,
            'prog'              : '%s %s' % (prog, self.name),
            'add_help_option'   : False,
            'formatter'         : UpdatingDefaultsHelpFormatter(),
            'name'              : self.name,
        }

        self.main_parser = main_parser

        self.parser = ConfigOptionParser(**parser_kw)
        self.command_group = optparse.OptionGroup(self.parser, 'Command options')

        # Re-add all options and option groups (quite lame :\ )
        for group in main_parser.option_groups:
            #self._copy_options(self.parser, group.option_list)
            self._copy_option_group(self.parser, group)

        self._copy_options(self.parser, main_parser.option_list)

    def _copy_options(self, parser, options):
        for option in options:
            if not option.dest or option.dest == 'help':
                continue
            parser.add_option(option)

    def _copy_option_group(self, parser, group):
        new_group = optparse.OptionGroup(parser, group.title)
        self._copy_options(new_group, group.option_list)

        parser.add_option_group(new_group)

    def merge_options(self, initial_options, options):
        # Make sure we have all global options carried over
        for attr in ('log', 'proxy', 'require_venv',
                     'log_explicit_levels', 'log_file',
                     'timeout', 'default_vcs', 'skip_requirements_regex',
                     'no_input'):

            val = getattr(initial_options, attr) or getattr(options, attr)
            setattr(options, attr, val)

        options.quiet += initial_options.quiet
        options.verbose += initial_options.verbose

    def setup_logging(self):
        pass

    def main(self, args, initial_options):
        options, args = self.parser.parse_args(args)
        self.merge_options(initial_options, options)

        level = 1 # Notify
        level += options.verbose
        level -= options.quiet
        level = logger.level_for_integer(4-level)
        complete_log = []
        logger.consumers.extend(
            [(level, sys.stdout),
             (logger.DEBUG, complete_log.append)])
        if options.log_explicit_levels:
            logger.explicit_levels = True

        self.setup_logging()

        if options.require_venv:
            # If a venv is required check if it can really be found
            if not os.environ.get('VIRTUAL_ENV'):
                logger.fatal('Could not find an activated virtualenv (required).')
                sys.exit(VIRTUALENV_NOT_FOUND)

        if options.log:
            log_fp = open_logfile(options.log, 'a')
            logger.consumers.append((logger.DEBUG, log_fp))
        else:
            log_fp = None

        socket.setdefaulttimeout(options.timeout or None)

        urlopen.setup(proxystr=options.proxy, prompting=not options.no_input)

        exit = SUCCESS
        store_log = False
        try:
            status = self.run(options, args)
            # FIXME: all commands should return an exit status
            # and when it is done, isinstance is not needed anymore
            if isinstance(status, int):
                exit = status
        except (InstallationError, UninstallationError):
            e = sys.exc_info()[1]
            logger.fatal(str(e))
            logger.info('Exception information:\n%s' % format_exc())
            store_log = True
            exit = ERROR
        except BadCommand:
            e = sys.exc_info()[1]
            logger.fatal(str(e))
            logger.info('Exception information:\n%s' % format_exc())
            store_log = True
            exit = ERROR
        except CommandError:
            e = sys.exc_info()[1]
            logger.fatal('ERROR: %s' % e)
            logger.info('Exception information:\n%s' % format_exc())
            exit = ERROR
        except KeyboardInterrupt:
            logger.fatal('Operation cancelled by user')
            logger.info('Exception information:\n%s' % format_exc())
            store_log = True
            exit = ERROR
        except:
            logger.fatal('Exception:\n%s' % format_exc())
            store_log = True
            exit = UNKNOWN_ERROR
        if log_fp is not None:
            log_fp.close()
        if store_log:
            log_fn = options.log_file
            text = '\n'.join(complete_log)
            logger.fatal('Storing complete log in %s' % log_fn)
            log_fp = open_logfile(log_fn, 'w')
            log_fp.write(text)
            log_fp.close()
        return exit


def format_exc(exc_info=None):
    if exc_info is None:
        exc_info = sys.exc_info()
    out = StringIO()
    traceback.print_exception(*exc_info, **dict(file=out))
    return out.getvalue()


def open_logfile(filename, mode='a'):
    """Open the named log file in append mode.

    If the file already exists, a separator will also be printed to
    the file to separate past activity from current activity.
    """
    filename = os.path.expanduser(filename)
    filename = os.path.abspath(filename)
    dirname = os.path.dirname(filename)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    exists = os.path.exists(filename)

    log_fp = open(filename, mode)
    if exists:
        log_fp.write('%s\n' % ('-'*60))
        log_fp.write('%s run on %s\n' % (sys.argv[0], time.strftime('%c')))
    return log_fp
