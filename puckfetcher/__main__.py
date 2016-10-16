# -*- coding: utf-8 -*-
"""Main entry point for puckfetcher, used to repeatedly download podcasts from the command line."""
# NOTE - Python 2 shims.
from __future__ import unicode_literals

import argparse
from argparse import RawTextHelpFormatter
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import textwrap
# NOTE - Python 2 shim.
# pylint: disable=redefined-builtin
from builtins import input

from clint.textui import prompt
# NOTE - Python 2 shim.
from future.utils import viewitems

import puckfetcher.constants as CONSTANTS
import puckfetcher.config as Config
import puckfetcher.error as Error
import puckfetcher.util as Util

def main():
    """Run puckfetcher on the command line."""

    parser = _setup_program_arguments()
    args = parser.parse_args()

    (cache_dir, config_dir, data_dir, log_dir) = _setup_directories(args)

    # pylint: disable=invalid-name
    LOG = _setup_logging(log_dir)

    try:
        config = Config.Config(config_dir=config_dir, cache_dir=cache_dir, data_dir=data_dir)
    except Error.MalformedConfigError as exception:
        LOG.error("Unable to start puckfetcher - config error.")
        LOG.error(exception)
        parser.exit()

    index = 1
    command_options = [{"selector": str(index), "prompt": "Exit.", "return": "exit"}]

    index += 1
    config_commands = Config.get_commands()
    for (key, value) in viewitems(config_commands):
        command_options.append({"selector": str(index), "prompt": value, "return": key.name})
        index += 1

    # See if we got a command-line command.
    config_dir = vars(args)["config"]
    command = vars(args)["command"]
    if command:
        if command == "exit":
            parser.exit()

        elif command == "menu":
            pass

        else:
            _handle_command(command, config, command_options, LOG)
            parser.exit()

    LOG.info("%s %s started!", __package__, CONSTANTS.VERSION)

    while True:
        try:
            command = prompt.options("Choose a command", command_options)

            if command == "exit":
                parser.exit()

            _handle_command(command, config, command_options, LOG)

        # TODO look into replacing with
        # https://stackoverflow.com/questions/1112343/how-do-i-capture-sigint-in-python
        except KeyboardInterrupt:
            LOG.critical("Received KeyboardInterrupt, exiting.")
            break

        except EOFError:
            LOG.critical("Received EOFError, exiting.")
            break

    parser.exit()

# TODO find a way to simplify and/or push logic into Config.
def _handle_command(command, config, command_options, log):
    if command == Config.Command.update.name:
        config.update()

    elif command == Config.Command.list.name:
        config.list()

    elif command == Config.Command.details.name:
        sub_index = _choose_sub(config)
        config.details(sub_index)
        input("Press enter when done.")

    elif command == Config.Command.download_queue.name:
        sub_index = _choose_sub(config)
        config.download_queue(sub_index)

    # TODO this needs work.
    elif command == Config.Command.enqueue.name:
        (sub_index, entry_nums) = _sub_list_command_wrapper(config, command, log)
        config.enqueue(sub_index, entry_nums)

    elif command == Config.Command.mark.name:
        (sub_index, entry_nums) = _sub_list_command_wrapper(config, command, log)
        config.mark(sub_index, entry_nums)

    elif command == Config.Command.unmark.name:
        (sub_index, entry_nums) = _sub_list_command_wrapper(config, command, log)
        config.unmark(sub_index, entry_nums)

    else:
        log.error("Unknown command. Allowed commands are:")
        for command in command_options:
            log.error("    {}: {}".format(command["return"], command["prompt"]))
        return

def _sub_list_command_wrapper(config, command, log):
    sub_index = _choose_sub(config)
    config.details(sub_index)
    log.info("COMMAND - {}".format(command))
    return (sub_index, _choose_entries())

def _choose_sub(config):
    sub_names = config.get_subs()
    if sub_names is None:
        return

    subscription_options = []
    pad_num = len(str(len(list(sub_names))))
    for i, sub_name in enumerate(sub_names):
        subscription_options.append(
            {"selector": str(i + 1).zfill(pad_num), "prompt": sub_name, "return": i})

    return prompt.options("Choose a subscription:", subscription_options)

def _choose_entries():
    done = False
    while not done:
        num_string = input(textwrap.dedent(
            """
            Provide numbers of entries for this command.
            Invalid numbers will be ignored.
            Press enter with an empty line to go back to command menu.
            """))

        if len(num_string) == 0:
            done = True
            num_list = None
            break

        num_list = Util.parse_int_string(num_string)

        while True:
            answer = input(textwrap.dedent(
                """\
                Happy with {}?
                (If indices are too big/small, they'll be pulled out later.)
                (No will let you try again)
                [Yes/yes/y or No/no/n]
                """.format(num_list)))

            if len(answer) < 1:
                continue

            ans = answer.lower()[0]
            if ans == "y":
                done = True
                break

            elif ans == "n":
                break

    return num_list


# Helpers.
def _setup_directories(args):
    config_dir = vars(args)["config"]
    if not config_dir:
        config_dir = CONSTANTS.APPDIRS.user_config_dir

    cache_dir = vars(args)["cache"]
    if not cache_dir:
        cache_dir = CONSTANTS.APPDIRS.user_cache_dir
        log_dir = CONSTANTS.APPDIRS.user_log_dir
    else:
        log_dir = os.path.join(cache_dir, "log")

    data_dir = vars(args)["data"]
    if not data_dir:
        data_dir = CONSTANTS.APPDIRS.user_data_dir

    return (cache_dir, config_dir, data_dir, log_dir)


def _setup_program_arguments():
    parser = argparse.ArgumentParser(description="Download RSS feeds based on a config.",
                                     formatter_class=RawTextHelpFormatter)

    parser.add_argument("command", metavar="command", type=str,
                        help=textwrap.dedent(
                            """\
                            Command to run, one of:
                            exit           - exit
                            update         - update all subscriptions to get newest entries list,
                                             and force queue download
                            list           - list current subscriptions
                            details        - provide details on entries for a subscription
                            enqueue        - add to download queue for subscription
                            mark           - mark entry downloaded for subcription
                            unmark         - mark entry as not downloaded for a subscription
                            download_queue - cause subscription to download full queue
                            menu           - provide these options in a menu\
                            """))

    parser.add_argument("--cache", "-a", dest="cache",
                        help=textwrap.dedent(
                            """\
                            Cache directory to use. The '{0}' directory will be created here, and
                            the 'puckcache' and '{0}.log' files will be stored there.
                            '$XDG_CACHE_HOME' will be used if nothing is provided.\
                            """.format(__package__)))

    parser.add_argument("--config", "-c", dest="config",
                        help=textwrap.dedent(
                            """\
                            Config directory to use. The '{0}' directory will be created here. Put
                            your 'config.yaml' file here to configure {0}. A default file will be
                            created for you with default settings if you do not provide one.
                            '$XDG_CONFIG_HOME' will be used if nothing is provided.\
                            """.format(__package__)))

    parser.add_argument("--data", "-d", dest="data",
                        help=textwrap.dedent(
                            """\
                            Data directory to use. The '{0}' directory will be created here. Put
                            your 'config.yaml' file here to configure {0}. A default file will be
                            created for you with default settings if you do not provide one.
                            The 'directory' setting in the config file will also affect the data
                            directory, but this flag takes precedent.
                            '$XDG_DATA_HOME' will be used if nothing is provided.
                            """.format(__package__)))

    parser.add_argument("--verbose", "-v", action="count",
                        help=textwrap.dedent(
                            """\
                            How verbose to be. If this is unused, only normal program output will
                            be logged. If there is one v, DEBUG output will be logged, and logging
                            will happen both to the log file and to stdout. If there is more than
                            one v, more debug output will happen. Some things will never be logged
                            no matter how much you vvvvvvvvvv.
                            """))

    parser.add_argument("--version", "-V", action="version",
                        version="%(prog)s {}".format(CONSTANTS.VERSION))

    return parser


def _setup_logging(log_dir):
    log_filename = os.path.join(log_dir, "{}.log".format(__package__))

    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)

    if not os.path.isfile(log_filename):
        open(log_filename, "a").close()

    logger = logging.getLogger("root")
    logger.setLevel(logging.DEBUG)

    # Provide a file handler that logs everything in a verbose format.
    file_handler = RotatingFileHandler(filename=log_filename, maxBytes=1024000000, backupCount=10)
    verbose_form = logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s")
    file_handler.setFormatter(verbose_form)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Provide a stdout handler that only logs things the use (theoretically) cares about (INFO and
    # above).
    stream_handler = logging.StreamHandler(sys.stdout)
    simple_form = logging.Formatter(fmt="%(message)s")
    stream_handler.setFormatter(simple_form)

    # If VERBOSITY is above zero, log to stream at DEBUG.
    if CONSTANTS.VERBOSITY > 0:
        stream_handler.setLevel(logging.DEBUG)

    else:
        stream_handler.setLevel(logging.INFO)

    logger.addHandler(stream_handler)

    return logger

if __name__ == "__main__":
    main()
