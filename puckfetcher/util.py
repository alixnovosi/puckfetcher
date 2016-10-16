# -*- coding: utf-8 -*-
"""Utility methods for Python packages (written with puckfetcher in mind)."""
# NOTE - Python 2 shim.
from __future__ import unicode_literals

import logging
import os
import time

import requests
from clint.textui import progress

LOG = logging.getLogger("root")

LAST_CALLED = {}

def ensure_dir(directory):
    """Create a directory if it doesn't exist."""
    if not os.path.isdir(directory):
        LOG.debug("Directory %s does not exist, creating it.", directory)
        os.makedirs(directory)

def expand(directory):
    """Apply expanduser and expandvars to directory to expand '~' and env vars."""
    temp = os.path.expanduser(directory)
    return os.path.expandvars(temp)

def generate_downloader(headers, args):
    """Create function to download with rate limiting and text progress."""

    def _downloader(url, dest):

        @rate_limited(30, args)
        def _rate_limited_download():

            # Create parent directory of file, and its parents, if they don't exist.
            parent = os.path.dirname(dest)
            if not os.path.exists(parent):
                os.makedirs(parent)

            response = requests.get(url, headers=headers, stream=True)
            LOG.info("Downloading from '%s'.", url)
            LOG.info("Trying to save to '%s'.", dest)

            total_length = int(response.headers.get("content-length"))
            expected_size = (total_length / 1024) + 1
            chunks = response.iter_content(chunk_size=1024)

            open(dest, "a").close()
            # per http://stackoverflow.com/a/20943461
            with open(dest, "wb") as stream:
                for chunk in progress.bar(chunks, expected_size=expected_size):
                    if not chunk:
                        return
                    stream.write(chunk)
                    stream.flush()

        _rate_limited_download()

    return _downloader

def max_clamp(val, limit):
    """Clamp int to limit."""
    return min(val, limit)

def parse_int_string(int_string):
    """
    Given a string like "1 23 4-8 32 1", return a unique list of those integers in the string and
    the integers in the ranges in the string.
    Non-numbers ignored. Not necessarily sorted
    """
    cleaned = " ".join(int_string.strip().split())
    cleaned = cleaned.replace(" - ", "-")
    cleaned = cleaned.replace(",", " ")

    tokens = cleaned.split(" ")
    indices = set()
    for token in tokens:
        if "-" in token:
            endpoints = token.split("-")
            if len(endpoints) != 2:
                LOG.info("Dropping token %s as invalid - weird range.", token)
                continue

            start = int(endpoints[0])
            end = int(endpoints[1]) + 1

            indices = indices.union(indices, set(range(start, end)))

        else:
            try:
                indices.add(int(token))
            except ValueError:
                LOG.info("Dropping token %s as invalid - not an int.", token)

    return list(indices)

# Modified from https://stackoverflow.com/a/667706
def rate_limited(max_per_hour, *args):
    """Decorator to limit function to N calls/hour."""
    min_interval = 3600.0 / float(max_per_hour)

    def _decorate(func):
        things = [func.__name__]
        things.extend(args)
        key = "".join(things)
        LOG.debug("Rate limiter called for %s.", key)
        if key not in LAST_CALLED:
            LOG.debug("Initializing entry for %s.", key)
            LAST_CALLED[key] = 0.0

        def _rate_limited_function(*args, **kargs):
            last_called = LAST_CALLED[key]
            now = time.time()
            elapsed = now - last_called
            remaining = min_interval - elapsed
            LOG.debug("Rate limiter last called for '%s' at %s.", key, last_called)
            LOG.debug("Remaining cooldown time for '%s' is %s.", key, remaining)

            if remaining > 0 and last_called > 0.0:
                LOG.info("Self-enforced rate limit hit, sleeping %s seconds.", remaining)
                time.sleep(remaining)

            LAST_CALLED[key] = time.time()
            ret = func(*args, **kargs)
            LOG.debug("Updating rate limiter last called for %s to %s.", key, now)
            return ret

        return _rate_limited_function
    return _decorate

def sanitize(filename):
    """
    Remove disallowed characters from potential filename. Currently only guaranteed on Linux and
    OS X.
    """
    return filename.replace("/", "-")
