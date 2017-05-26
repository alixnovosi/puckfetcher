"""Constants used for the puckfetcher application."""
import appdirs
import pkg_resources  # type: ignore

APPDIRS = appdirs.AppDirs("puckfetcher")

URL = "https://github.com/andrewmichaud/puckfetcher"

VERSION = pkg_resources.require(__package__)[0].version

USER_AGENT = __package__ + "/" + VERSION + " +" + URL
USER_AGENT = f"{__package__}/{VERSION} +{URL}"

VERBOSITY = 0

ENCODING = "UTF-8"
