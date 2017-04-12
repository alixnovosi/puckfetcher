"""Main entry point for puckfetcher, used to repeatedly download podcasts from the command line."""
import argparse
import logging
import logging.handlers as lhandlers
import os
import sys
import textwrap
from typing import Any, Dict, List, Tuple

from clint.textui import prompt

import puckfetcher.constants as constants
import puckfetcher.config as config
import puckfetcher.error as error
import puckfetcher.util as util

def main() -> None:
    """Run puckfetcher on the command line."""

    parser = _setup_program_arguments()
    args = parser.parse_args()

    (cache_dir, config_dir, data_dir, log_dir) = _setup_directories(args)

    # pylint: disable=invalid-name
    LOG = _setup_logging(log_dir)

    try:
        conf = config.Config(config_dir=config_dir, cache_dir=cache_dir, data_dir=data_dir)
    except error.MalformedConfigError as exception:
        LOG.error("Unable to start puckfetcher - config error.")
        LOG.error(exception.desc)
        parser.exit()

    index = 1
    command_options = [{"selector": str(index), "prompt": "Exit.", "return": "exit"}]

    index += 1
    config_commands = conf.get_commands()
    for key in config_commands:
        value = conf.commands[key]
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
            _handle_command(command, conf, command_options, LOG)
            parser.exit()

    LOG.info("%s %s started!", __package__, constants.VERSION)

    while True:
        try:
            command = prompt.options("Choose a command", command_options)

            if command == "exit":
                parser.exit()

            _handle_command(command, conf, command_options, LOG)

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
def _handle_command(command: str, conf: config.Config,
                    command_options: List[Dict[str, Any]],
                    log: logging.Logger,
                    ) -> None:
    try:
        if command == config.Command.update.name:
            conf.update()

        elif command == config.Command.list.name:
            conf.list()

        elif command == config.Command.clear_session_summary:
            conf.clear_session_summary()

        elif command == config.Command.summarize.name:
            conf.summarize()
            input("Press enter when done.")

        elif command == config.Command.details.name:
            sub_index = _choose_sub(conf)
            conf.details(sub_index)
            input("Press enter when done.")

        elif command == config.Command.download_queue.name:
            sub_index = _choose_sub(conf)
            conf.download_queue(sub_index)

        elif command == config.Command.summarize_sub.name:
            sub_index = _choose_sub(conf)
            conf.summarize_sub(sub_index)
            input("Press enter when done.")

        # TODO this needs work.
        elif command == config.Command.enqueue.name:
            (sub_index, entry_nums) = _sub_list_command_wrapper(conf, command, log)
            conf.enqueue(sub_index, entry_nums)

        elif command == config.Command.mark.name:
            (sub_index, entry_nums) = _sub_list_command_wrapper(conf, command, log)
            conf.mark(sub_index, entry_nums)

        elif command == config.Command.unmark.name:
            (sub_index, entry_nums) = _sub_list_command_wrapper(conf, command, log)
            conf.unmark(sub_index, entry_nums)

        else:
            log.error("Unknown command. Allowed commands are:")
            for item in command_options:
                log.error("    {}: {}".format(item["return"], item["prompt"]))
            return

    except error.PuckError as e:
        log.error("Encountered error running command.")
        log.error(e.desc)


def _sub_list_command_wrapper(conf: config.Config, command: str, log: logging.Logger,
                              ) -> Tuple[int, List[int]]:
    sub_index = _choose_sub(conf)
    conf.details(sub_index)
    log.info("COMMAND - {}".format(command))
    return (sub_index, _choose_entries())

def _choose_sub(conf: config.Config) -> int:
    sub_names = conf.get_subs()

    subscription_options = []
    pad_num = len(str(len(sub_names)))
    for i, sub_name in enumerate(sub_names):
        subscription_options.append(
            {"selector": str(i + 1).zfill(pad_num), "prompt": sub_name, "return": i})

    return prompt.options("Choose a subscription:", subscription_options)

def _choose_entries() -> List[int]:
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

        num_list = util.parse_int_string(num_string)

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
def _setup_directories(args: argparse.Namespace) -> Tuple[str, str, str, str]:
    config_dir = vars(args)["config"]
    if not config_dir:
        config_dir = constants.APPDIRS.user_config_dir

    cache_dir = vars(args)["cache"]
    if not cache_dir:
        cache_dir = constants.APPDIRS.user_cache_dir
        log_dir = constants.APPDIRS.user_log_dir
    else:
        log_dir = os.path.join(cache_dir, "log")

    data_dir = vars(args)["data"]
    if not data_dir:
        data_dir = constants.APPDIRS.user_data_dir

    return (cache_dir, config_dir, data_dir, log_dir)


def _setup_program_arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download RSS feeds based on a config.",
                                     formatter_class=argparse.RawTextHelpFormatter)

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
                            summarize      - summarize entries downloaded this session
                            summarize_sub  - summarize recent entries for a particular sub
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
                            Data directory to use. Downloaded subscription entries will live here.
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
                        version="%(prog)s {}".format(constants.VERSION))

    return parser


def _setup_logging(log_dir: str) -> logging.Logger:
    log_filename = os.path.join(log_dir, "{}.log".format(__package__))

    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)

    if not os.path.isfile(log_filename):
        open(log_filename, "a", encoding=constants.ENCODING).close()

    logger = logging.getLogger("root")
    logger.setLevel(logging.DEBUG)

    # Provide a file handler that logs everything in a verbose format.
    file_handler = lhandlers.RotatingFileHandler(filename=log_filename,
                                                 maxBytes=1024000000, backupCount=10)
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
    if constants.VERBOSITY > 0:
        stream_handler.setLevel(logging.DEBUG)

    else:
        stream_handler.setLevel(logging.INFO)

    logger.addHandler(stream_handler)

    return logger

if __name__ == "__main__":
    main()
