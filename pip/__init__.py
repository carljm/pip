#!/usr/bin/env python
# encoding: utf-8

import os
import re
import sys
import optparse
import subprocess

from pip.backwardcompat import walk_packages
from pip.exceptions import InstallationError
from pip.log import logger
from pip.util import get_installed_distributions
from pip.baseparser import create_main_parser
from pip.commands import commands, get_similar_commands, get_summaries
from pip.exceptions import CommandError, PipError
from pip.commands import commands, get_similar_commands, get_summaries


def autocomplete():
    """Command and option completion for the main option parser (and options)
    and its subcommands (and options).

    Enable by sourcing one of the completion shell scripts (bash or zsh).
    """
    # Don't complete if user hasn't sourced bash_completion file.
    if 'PIP_AUTO_COMPLETE' not in os.environ:
        return
    cwords = os.environ['COMP_WORDS'].split()[1:]
    cword = int(os.environ['COMP_CWORD'])
    try:
        current = cwords[cword-1]
    except IndexError:
        current = ''
    load_all_commands()
    subcommands = [cmd for cmd, cls in commands.items() if not cls.hidden]
    options = []
    # subcommand
    try:
        subcommand_name = [w for w in cwords if w in subcommands][0]
    except IndexError:
        subcommand_name = None
    # subcommand options
    if subcommand_name:
        # special case: 'help' subcommand has no options
        if subcommand_name == 'help':
            sys.exit(1)
        # special case: list locally installed dists for uninstall command
        if subcommand_name == 'uninstall' and not current.startswith('-'):
            installed = []
            lc = current.lower()
            for dist in get_installed_distributions(local_only=True):
                if dist.key.startswith(lc) and dist.key not in cwords[1:]:
                    installed.append(dist.key)
            # if there are no dists installed, fall back to option completion
            if installed:
                for dist in installed:
                    print(dist)
                sys.exit(1)
        subcommand = commands.get(subcommand_name)
        options += [(opt.get_opt_string(), opt.nargs)
                    for opt in subcommand.parser.option_list
                    if opt.help != optparse.SUPPRESS_HELP]
        # filter out previously specified options from available options
        prev_opts = [x.split('=')[0] for x in cwords[1:cword-1]]
        options = [(x, v) for (x, v) in options if x not in prev_opts]
        # filter options by current input
        options = [(k, v) for k, v in options if k.startswith(current)]
        for option in options:
            opt_label = option[0]
            # append '=' to options which require args
            if option[1]:
                opt_label += '='
            print(opt_label)
    else:
        # show options of main parser only when necessary
        if current.startswith('-') or current.startswith('--'):
            subcommands += [opt.get_opt_string()
                            for opt in parser.option_list
                            if opt.help != optparse.SUPPRESS_HELP]
        print(' '.join([x for x in subcommands if x.startswith(current)]))
    sys.exit(1)


############################################################
## Writing freeze files


class FrozenRequirement(object):

    def __init__(self, name, req, editable, comments=()):
        self.name = name
        self.req = req
        self.editable = editable
        self.comments = comments

    _rev_re = re.compile(r'-r(\d+)$')
    _date_re = re.compile(r'-(20\d\d\d\d\d\d)$')

    @classmethod
    def from_dist(cls, dist, dependency_links, find_tags=False):
        location = os.path.normcase(os.path.abspath(dist.location))
        comments = []
        from pip.vcs import vcs, get_src_requirement
        if vcs.get_backend_name(location):
            editable = True
            req = get_src_requirement(dist, location, find_tags)
            if req is None:
                logger.warn('Could not determine repository location of %s' % location)
                comments.append('## !! Could not determine repository location')
                req = dist.as_requirement()
                editable = False
        else:
            editable = False
            req = dist.as_requirement()
            specs = req.specs
            assert len(specs) == 1 and specs[0][0] == '=='
            version = specs[0][1]
            ver_match = cls._rev_re.search(version)
            date_match = cls._date_re.search(version)
            if ver_match or date_match:
                svn_backend = vcs.get_backend('svn')
                if svn_backend:
                    svn_location = svn_backend(
                        ).get_location(dist, dependency_links)
                if not svn_location:
                    logger.warn(
                        'Warning: cannot find svn location for %s' % req)
                    comments.append('## FIXME: could not find svn URL in dependency_links for this package:')
                else:
                    comments.append('# Installing as editable to satisfy requirement %s:' % req)
                    if ver_match:
                        rev = ver_match.group(1)
                    else:
                        rev = '{%s}' % date_match.group(1)
                    editable = True
                    req = '%s@%s#egg=%s' % (svn_location, rev, cls.egg_name(dist))
        return cls(dist.project_name, req, editable, comments)

    @staticmethod
    def egg_name(dist):
        name = dist.egg_name()
        match = re.search(r'-py\d\.\d$', name)
        if match:
            name = name[:match.start()]
        return name

    def __str__(self):
        req = self.req
        if self.editable:
            req = '-e %s' % req
        return '\n'.join(list(self.comments)+[str(req)])+'\n'

############################################################
## Requirement files


def version_control():
    # Import all the version control support modules:
    from pip import vcs
    for importer, modname, ispkg in \
            walk_packages(path=vcs.__path__, prefix=vcs.__name__+'.'):
        __import__(modname)


def bootstrap():
    """
    Bootstrapping function to be called from install-pip.py script.
    """
    return main(['install', '--upgrade', 'pip'])


def parseopts(args):
    parser = create_main_parser()

    # create command listing
    command_summaries = get_summaries()

    description = ['Commands:']
    description.extend(['  %-20s %s' % (i, j) for i,j in command_summaries])

    parser.description = '\n'.join(description)

    options, args = parser.parse_args(args)

    if options.version:
        # TODO: pip install -V does not work yet
        sys.stdout.write(parser.version)
        sys.stdout.write(os.linesep)
        sys.exit()

    # pip || pip help || pip --help -> print_help()
    if options.help or not args or (args[0] == 'help' and len(args) == 1):
        parser.print_help()
        sys.exit()

    if not args:
        msg = 'You must give a command (use "pip --help" to see a list of commands)'
        raise CommandError

    command = args[0].lower()

    if command not in commands:
        guess = get_similar_commands(command)

        msg = ['unknown command "%s"' % command]
        if guess:
           msg.append('maybe you meant "%s"' % guess)

        raise CommandError(' - '.join(msg)) # TODO:

    return command, options, args, parser


def main(initial_args=None):
    if initial_args is None:
        initial_args = sys.argv[1:]

    autocomplete()
    version_control()

    try:
        cmd_name, options, args, parser = parseopts(initial_args)
    except PipError:
        e = sys.exc_info()[1]
        sys.stderr.write(str(e))
        sys.stderr.write(os.linesep)
        sys.exit(1)

    command = commands[cmd_name](parser) # Instantiate Command

    return command.main(args[1:], options)


if __name__ == '__main__':
    exit = main()
    if exit:
        sys.exit(exit)
