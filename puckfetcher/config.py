# -*- coding: utf-8 -*-
"""Module describing a Config object, which controls how an instance of puckfetcher acts."""
# NOTE - Python 2 shim.
from __future__ import unicode_literals

import collections
import logging
import os
from enum import Enum

import umsgpack
import yaml
# Python 2/PyPy shim - unicode_literals breaks yaml loading for some reason on those versions.
from yaml import SafeLoader

import puckfetcher.error as Error
import puckfetcher.subscription as Subscription
import puckfetcher.util as Util

LOG = logging.getLogger("root")


class Config(object):
    """Class holding config options."""

    def __init__(self, config_dir, cache_dir, data_dir):

        _validate_dirs(config_dir, cache_dir, data_dir)

        self.config_file = os.path.join(config_dir, "config.yaml")
        LOG.debug("Using config file '%s'.", self.config_file)

        self.cache_file = os.path.join(cache_dir, "puckcache")
        LOG.debug("Using cache file '%s'.", self.cache_file)

        self.settings = {
            "directory": data_dir,
            "backlog_limit": 1,
            "use_title_as_filename": False
        }

        self.state_loaded = False
        self.subscriptions = []

        # This map is used to match user subs to cache subs, in case names or URLs (but not both)
        # have changed.
        self.cache_map = {"by_name": {}, "by_url": {}}

    # "Public" class functions.
    def load_state(self):
        """Load config file, and load subscription cache if we haven't yet."""
        self._load_user_settings()
        self._load_cache_settings()

        if self.subscriptions != []:
            # Iterate through subscriptions to merge user settings and cache.
            subs = []
            for sub in self.subscriptions:

                # Pull out settings we need for merging metadata, or to preserve over the cache.
                name = sub.name
                url = sub.url
                directory = sub.directory

                # Match cached sub to current sub and take its settings.
                # If the user has changed either we can still match the sub and update settings
                # correctly.
                # If they update neither, there's nothing we can do.
                if name in self.cache_map["by_name"]:
                    LOG.debug("Found sub with name %s in cached subscriptions, merging.", name)
                    sub = self.cache_map["by_name"][name]

                elif url in self.cache_map["by_url"]:
                    LOG.debug("Found sub with url %s in cached subscriptions, merging.", url)
                    sub = self.cache_map["by_url"][url]

                sub.update(directory=directory, name=name, url=url, set_original=True,
                           config_dir=self.settings["directory"])

                sub.default_missing_fields(self.settings)

                subs.append(sub)

            self.subscriptions = subs

        LOG.debug("Successful load.")
        self.state_loaded = True

    def get_subs(self):
        """Provie list of subscription names. Load state if we haven't."""
        _ensure_loaded(self)
        return map(lambda sub: sub.name, self.subscriptions)

    def update(self):
        """Update all subscriptions once. Return True if we successfully updated."""
        _ensure_loaded(self)

        num_subs = len(self.subscriptions)
        for i, sub in enumerate(self.subscriptions):
            LOG.info("Working on sub number %s/%s - '%s'", i + 1, num_subs, sub.name)
            update_successful = sub.attempt_update()

            if not update_successful:
                LOG.info("Unsuccessful update for sub '%s'.", sub.name)
            else:
                LOG.info("Updated sub '%s' successfully.", sub.name)

            self.subscriptions[i] = sub
            self.save_cache()

    def list(self):
        """Load state and list subscriptions. Return if loading succeeded."""
        _ensure_loaded(self)

        num_subs = len(self.subscriptions)
        LOG.info("%s subscriptions loaded.", num_subs)
        for i, sub in enumerate(self.subscriptions):
            LOG.info(sub.get_status(i, num_subs))

        LOG.debug("Load + list completed, no issues.")

    def details(self, sub_index):
        """Get details on one sub, including last update date and what entries we have."""
        try:
            self._validate_command(sub_index)
        except Error.BadCommandError as exception:
            LOG.error(exception)
            return

        num_subs = len(self.subscriptions)
        sub = self.subscriptions[sub_index]
        sub.get_details(sub_index, num_subs)

        LOG.debug("Load + detail completed, no issues.")

    def enqueue(self, sub_index, nums):
        """Add item(s) to a sub's download queue."""
        try:
            self._validate_list_command(sub_index, nums)
        except Error.BadCommandError as exception:
            LOG.error(exception)
            return

        sub = self.subscriptions[sub_index]
        # Implicitly mark subs we're manually adding to the queue as undownloaded. User shouldn't
        # have to manually do that.
        sub.unmark(nums)
        enqueued_nums = sub.enqueue(nums)

        LOG.info("Added items %s to queue successfully.", enqueued_nums)
        self.save_cache()

    def mark(self, sub_index, nums):
        """Mark items as downloaded by a subscription."""
        try:
            self._validate_list_command(sub_index, nums)
        except Error.BadCommandError as exception:
            LOG.error(exception)
            return

        sub = self.subscriptions[sub_index]
        marked_nums = sub.mark(nums)

        LOG.info("Marked items %s as downloaded successfully.", marked_nums)
        self.save_cache()

    def unmark(self, sub_index, nums):
        """Unmark items as downloaded by a subscription."""
        try:
            self._validate_list_command(sub_index, nums)
        except Error.BadCommandError as exception:
            LOG.error(exception)
            return

        sub = self.subscriptions[sub_index]
        unmarked_nums = sub.unmark(nums)

        LOG.info("Unmarked items %s successfully.", unmarked_nums)
        self.save_cache()

    def download_queue(self, sub_index):
        """Download one sub's download queue."""
        # TODO I don't like this pattern - handle the error higher up or something.
        try:
            self._validate_command(sub_index)
        except Error.BadCommandError as exception:
            LOG.error(exception)
            return

        sub = self.subscriptions[sub_index]
        sub.download_queue()

        LOG.info("Queue downloading complete, no issues.")
        self.save_cache()

    def save_cache(self):
        """Write current in-memory config to cache file."""
        LOG.info("Writing settings to cache file '%s'.", self.cache_file)
        with open(self.cache_file, "wb") as stream:
            dicts = [Subscription.Subscription.encode_subscription(s) for s in self.subscriptions]
            packed = umsgpack.packb(dicts)
            stream.write(packed)

    # "Private" functions (messy internals).
    def _validate_list_command(self, sub_index, nums):
        if nums is None or len(nums) <= 0:
            raise Error.BadCommandError("Invalid list of nums {}.".format(nums))

        self._validate_command(sub_index)

    def _validate_command(self, sub_index):
        if sub_index < 0 or sub_index > len(self.subscriptions):
            raise Error.BadCommandError("Invalid sub index {}.".format(sub_index))

        _ensure_loaded(self)

    def _load_cache_settings(self):
        """Load settings from cache to self.cached_settings."""

        successful = _ensure_file(self.cache_file)

        if not successful:
            LOG.debug("Unable to load cache.")
            return

        with open(self.cache_file, "rb") as stream:
            LOG.debug("Opening subscription cache to retrieve subscriptions.")
            data = stream.read()

        if data == b"":
            LOG.debug("Received empty string from cache.")
            return False

        for encoded_sub in umsgpack.unpackb(data):
            try:
                decoded_sub = Subscription.Subscription.decode_subscription(encoded_sub)

            except Error.MalformedSubscriptionError as exception:
                LOG.debug("Encountered error in subscription decoding:")
                LOG.debug(exception)
                LOG.debug("Skipping this sub.")
                continue

            self.cache_map["by_name"][decoded_sub.name] = decoded_sub
            self.cache_map["by_url"][decoded_sub.original_url] = decoded_sub

        return True

    def _load_user_settings(self):
        """Load user settings from config file."""
        successful = _ensure_file(self.config_file)

        if not successful:
            LOG.error("Unable to load user config file.")
            return

        self.subscriptions = []

        # Python 2/PyPy shim, per
        # https://stackoverflow.com/questions/2890146/how-to-force-pyyaml-to-load-strings-as-unicode-objects
        # Override the default string handling function to always return unicode objects.
        def construct_yaml_str(self, node):
            """Override to force PyYAML to handle unicode on Python 2."""
            return self.construct_scalar(node)

        SafeLoader.add_constructor("tag:yaml.org,2002:python/unicode", construct_yaml_str)

        with open(self.config_file, "r") as stream:
            LOG.debug("Opening config file to retrieve settings.")
            yaml_settings = yaml.safe_load(stream)

        pretty_settings = yaml.dump(yaml_settings, width=1, indent=4)
        LOG.debug("Settings retrieved from user config file: %s", pretty_settings)

        if yaml_settings is not None:

            # Update self.settings, but only currently valid settings.
            for name, value in yaml_settings.items():
                if name == "subscriptions":
                    pass
                elif name not in self.settings:
                    LOG.debug("Setting %s is not a valid setting, ignoring.", name)
                else:
                    self.settings[name] = value

            fail_count = 0
            for i, yaml_sub in enumerate(yaml_settings.get("subscriptions", [])):
                sub = Subscription.Subscription.parse_from_user_yaml(yaml_sub, self.settings)

                if sub is None:
                    LOG.debug("Unable to parse user YAML for sub # %s - something is wrong.",
                              i + 1)
                    fail_count += 1
                    continue

                self.subscriptions.append(sub)

            if fail_count > 0:
                LOG.error("Some subscriptions from config file couldn't be parsed - check logs.")

        return True

# "Public" functions.
def get_commands():
    """Provide commands that can be used on this config."""
    return collections.OrderedDict((
        (Command.update,
         "Update all subscriptions. Will also download sub queues."),
        (Command.list,
         "List current subscriptions and their status."),
        (Command.details,
         "Provide details on one subscription's entries and queue status."),
        (Command.enqueue,
         "Add to a sub's download queue. Items will be skipped if already in queue, or " +
         "invalid."),
        (Command.mark,
         "Mark a subscription entry as downloaded."),
        (Command.unmark,
         "Mark a subscription entry as not downloaded. Will not queue for download."),
        (Command.download_queue, "Download a subscription's full queue. Files with the same " +
         "name as a to-be-downloaded entry will be overridden.")))

# "Private" functions.
def _ensure_loaded(config):
    if not config.state_loaded:
        LOG.debug("State not loaded from config file and cache - loading!")
        config.load_state()

def _ensure_file(file_path):
    if os.path.exists(file_path) and not os.path.isfile(file_path):
        LOG.debug("Given file exists but isn't a file!")
        return False

    elif not os.path.isfile(file_path):
        LOG.debug("Creating empty file at '%s'.", file_path)
        open(file_path, "a").close()

    return True

def _validate_dirs(config_dir, cache_dir, data_dir):
    for directory in [config_dir, cache_dir, data_dir]:
        if os.path.isfile(directory):
            msg = "Provided directory '{}' is actually a file!".format(directory)
            raise Error.MalformedConfigError(msg)

        Util.ensure_dir(directory)


class Command(Enum):
    """Commands a Config can perform."""
    update = 100
    list = 400
    details = 500
    enqueue = 600
    mark = 700
    unmark = 750
    download_queue = 800
