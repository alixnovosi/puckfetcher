"""Tests for the subscription module."""

import os

from future.utils import viewitems

import pytest

import puckfetcher.error as PE
import puckfetcher.subscription as SUB

RSS_ADDRESS = "valid"
PERM_REDIRECT = "301"
TEMP_REDIRECT = "302"
NOT_FOUND = "404"
GONE = "410"

ERROR_CASES = [TEMP_REDIRECT, PERM_REDIRECT, NOT_FOUND, GONE]


def test_empty_url_cons(strdir):
    """
    Constructing a subscription with an empty URL should throw a MalformedSubscriptionError.
    """
    with pytest.raises(PE.MalformedSubscriptionError) as exception:
        SUB.Subscription(url="", name="emptyConstruction", directory=strdir)

    assert exception.value.desc == "No URL provided."

def test_none_url_cons(strdir):
    """
    Constructing a subscription with a URL that is None should throw a MalformedSubscriptionError.
    """
    with pytest.raises(PE.MalformedSubscriptionError) as exception:
        SUB.Subscription(name="noneConstruction", directory=strdir)

    assert exception.value.desc == "No URL provided."

def test_empty_name_cons(strdir):
    """
    Constructing a subscription with an empty name should throw a MalformedSubscriptionError.
    """
    with pytest.raises(PE.MalformedSubscriptionError) as exception:
        SUB.Subscription(url="foo", name="", directory=strdir)

    assert exception.value.desc == "No name provided."

def test_none_name_cons(strdir):
    """
    Constructing a subscription with a name that is None should throw a MalformedSubscriptionError.
    """
    with pytest.raises(PE.MalformedSubscriptionError) as exception:
        SUB.Subscription(url="foo", name=None, directory=strdir)

    assert exception.value.desc == "No name provided."

def test_get_feed_max(strdir):
    """If we try more than MAX_RECURSIVE_ATTEMPTS to retrieve a URL, we should fail."""
    test_sub = SUB.Subscription(url=PERM_REDIRECT, name="tooManyAttemptsTest", directory=strdir)

    test_sub.get_feed(attempt_count=SUB.MAX_RECURSIVE_ATTEMPTS+1)

    assert test_sub.feed_state.feed == {}
    assert test_sub.feed_state.entries == []

def test_temporary_redirect(strdir):
    """
    If we are redirected temporarily to a valid RSS feed, we should successfully parse that
    feed and not change our url. The originally provided URL should be unchanged.
    """
    _test_url_helper(strdir, TEMP_REDIRECT, "302Test", TEMP_REDIRECT, TEMP_REDIRECT)

def test_permanent_redirect(strdir):
    """
    If we are redirected permanently to a valid RSS feed, we should successfully parse that
    feed and change our url. The originally provided URL should be unchanged.
    """
    _test_url_helper(strdir, PERM_REDIRECT, "301Test", RSS_ADDRESS, PERM_REDIRECT)

def test_not_found_fails(strdir):
    """If the URL is Not Found, we should not change the saved URL."""
    _test_url_helper(strdir, NOT_FOUND, "404Test", NOT_FOUND, NOT_FOUND)

def test_gone_fails(strdir):
    """If the URL is Gone, the current url should be set to None, and we should return None."""

    test_sub = SUB.Subscription(url=GONE, name="410Test", directory=strdir)

    test_sub.use_backlog = True
    test_sub.backlog_limit = 1
    test_sub.use_title_as_filename = False

    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    test_sub.get_feed()

    assert test_sub.url is None
    assert test_sub.original_url == GONE

def test_new_attempt_update(strdir):
    """Attempting update on a new subscription (no backlog) should download nothing."""
    test_dir = strdir
    test_sub = SUB.Subscription(url="foo", name="foo", directory=test_dir)
    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    test_sub.attempt_update()
    assert len(os.listdir(test_dir)) == 0

def test_attempt_update_new_entry(strdir):
    """Attempting update on a podcast with a new entry should download the new entry only."""
    test_dir = strdir
    test_sub = SUB.Subscription(url=RSS_ADDRESS, name="bar", directory=test_dir)
    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    assert len(os.listdir(test_dir)) == 0

    test_sub.feed_state.latest_entry_number = 9

    test_sub.attempt_update()
    assert test_sub.feed_state.latest_entry_number == 10
    assert len(os.listdir(test_dir)) == 1
    _check_hi_contents(0, test_dir)

def test_attempt_download_backlog(strdir):
    """Should download full backlog if backlog limit set to None."""
    test_sub = SUB.Subscription(url=RSS_ADDRESS, name="testfeed", directory=strdir)
    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    test_sub.use_backlog = True
    test_sub.backlog_limit = None
    test_sub.use_title_as_filename = False

    test_sub.attempt_update()

    assert len(test_sub.feed_state.entries) == 10
    assert len(os.listdir(test_sub.directory)) == 10
    for i in range(1, 9):
        _check_hi_contents(i, test_sub.directory)

def test_attempt_download_partial_backlog(strdir):
    """Should download partial backlog if limit is specified."""
    test_sub = SUB.Subscription(url=RSS_ADDRESS, name="testfeed", backlog_limit=5, directory=strdir)

    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    # TODO find a cleaner way to set these.
    # Maybe test_subscription should handle these attributes missing better?
    # Maybe have a cleaner way to hack them in in tests?
    test_sub.use_backlog = True
    test_sub.backlog_limit = 4
    test_sub.use_title_as_filename = False
    test_sub.attempt_update()

    for i in range(0, 4):
        _check_hi_contents(i, test_sub.directory)

def test_mark(sub_with_entries):
    """Should mark subscription entries correctly."""
    assert len(sub_with_entries.feed_state.entries) > 0

    test_nums = [2, 3, 4, 5]
    bad_nums = [-1, -12, 10000]
    all_nums = bad_nums + test_nums + bad_nums

    for test_num in test_nums:
        assert test_num not in sub_with_entries.feed_state.entries_state_dict

    sub_with_entries.mark(all_nums)

    assert len(sub_with_entries.feed_state.entries_state_dict) > 0
    for test_num in test_nums:
        zero_indexed_num = test_num-1
        assert zero_indexed_num in sub_with_entries.feed_state.entries_state_dict
        assert sub_with_entries.feed_state.entries_state_dict[zero_indexed_num]

    for bad_num in bad_nums:
        assert bad_num not in sub_with_entries.feed_state.entries_state_dict

def test_unmark(sub_with_entries):
    """Should unmark subscription entries correctly."""
    assert len(sub_with_entries.feed_state.entries) > 0

    test_nums = [2, 3, 4, 5]
    bad_nums = [-1, -12, 10000]
    all_nums = bad_nums + test_nums + bad_nums

    for num in test_nums:
        sub_with_entries.feed_state.entries_state_dict[num-1] = True

    sub_with_entries.unmark(all_nums)

    assert len(sub_with_entries.feed_state.entries_state_dict) > 0
    for test_num in test_nums:
        zero_indexed_num = test_num-1
        assert zero_indexed_num in sub_with_entries.feed_state.entries_state_dict
        assert not sub_with_entries.feed_state.entries_state_dict[zero_indexed_num]

    for bad_num in bad_nums:
        assert bad_num not in sub_with_entries.feed_state.entries_state_dict

    # def _get_dest(self, url, title, directory):
    #
    #     # URL example: "https://www.example.com/foo.mp3?test=1"
    #
    #     # Cut everything but filename and (possibly) query params.
    #     # URL example: "foo.mp3?test=1"
    #     url_end = url.split("/")[-1]
    #
    #     # URL example: "foo.mp3?test=1"
    #     # Cut query params.
    #     # I think I could assume there's only one '?' after the file extension, but after being
    #     # surprised by query parameters, I want to be extra careful.
    #     # URL example: "foo.mp3"
    #     url_filename = url_end.split("?")[0]
    #
    #     filename = url_filename
    #
    #     if platform.system() == "Windows":
    #         LOG.error(textwrap.dedent(
    #             """\
    #             Sorry, we can't guarantee valid filenames on Windows if we use RSS
    #             subscription titles.
    #             We'll support it eventually!
    #             Using URL filename.\
    #             """))
    #
    #     elif self.use_title_as_filename:
    #         ext = os.path.splitext(url_filename)[1][1:]
    #         filename = "{}.{}".format(title, ext) # It's an owl!
    #
    #     # Remove characters we can't allow in filenames.
    #     filename = Util.sanitize(filename)
    #
    #     return os.path.join(directory, filename)


def test_url_with_qparams():
    """Test that the _get_dest helper handles query parameters properly."""
    test_sub = SUB.Subscription(url="test", name="test", directory="test")

    test_sub.use_title_as_filename = True

    # pylint: disable=protected-access
    filename = test_sub._get_dest("https://www.example.com?foo=1/bar.mp3?baz=2", "puck", "/test")
    assert filename == "/test/puck.mp3"

    test_sub.use_title_as_filename = False

    # pylint: disable=protected-access
    filename = test_sub._get_dest("https://www.example.com?foo=1/bar.mp3?baz=2", "puck", "/test")
    assert filename == "/test/bar.mp3"

def test_url_sanitize():
    """Test that the _get_dest helper sanitizes correctly on non-Windows."""
    test_sub = SUB.Subscription(url="test", name="test", directory="test")

    test_sub.use_title_as_filename = True

    # pylint: disable=protected-access
    filename = test_sub._get_dest("https://www.example.com?foo=1/bar.mp3?baz=2", "p/////uck",
                                  "/test")
    assert filename == "/test/p-----uck.mp3"

    # pylint: disable=protected-access
    filename = test_sub._get_dest("https://www.example.com?foo=1/bar.mp3?baz=2", u"p🤔🤔🤔🤔uck",
                                  "/test")
    assert filename == u"/test/p🤔🤔🤔🤔uck.mp3"


# Helpers.
def _test_url_helper(strdir, given, name, expected_current, expected_original):
    test_sub = SUB.Subscription(url=given, name=name, directory=strdir)

    test_sub.downloader = generate_fake_downloader()
    test_sub.parser = generate_feedparser()

    test_sub.get_feed()

    assert test_sub.url == expected_current
    assert test_sub.original_url == expected_original

def _check_hi_contents(filename_num, directory):
    file_path = os.path.join(directory, "hi0{}.txt".format(filename_num))
    with open(file_path, "r") as enclosure:
        data = enclosure.read().replace('\n', '')
        assert data == "hi"

def generate_fake_downloader():
    """Fake downloader for test purposes."""

    def _downloader(url=None, dest=None):
        contents = "hi"

        open(dest, "a").close()
        # per http://stackoverflow.com/a/20943461
        with open(dest, "w") as stream:
            stream.write(contents)
            stream.flush()

    return _downloader

def generate_feedparser():
    """Feedparser wrapper without rate_limiting, for testing."""

    # pylint: disable=unused-argument
    def _fake_parser(url, etag, last_modified):

        fake_parsed = {}
        entries = []
        href = ""
        for i in range(0, 10):
            entry = {}
            entry["title"] = "hi"

            entry["enclosures"] = [{"href": "hi0{}.txt".format(i)}]

            entries.append(entry)

        if url in ERROR_CASES:
            status = int(url)

            if url == PERM_REDIRECT or url == TEMP_REDIRECT:
                href = RSS_ADDRESS

        else:
            status = 200

        fake_parsed["entries"] = entries
        fake_parsed["href"] = href
        fake_parsed["status"] = status

        return fake_parsed

    return _fake_parser


# Fixtures.
@pytest.fixture(scope="function")
def strdir(tmpdir):
    """Create temp directory, in string format."""
    return str(tmpdir.mkdir("foo"))


@pytest.fixture(scope="function")
def sub(strdir):
    """Create a test subscription."""
    test_sub = SUB.Subscription(url="test", name="test", directory=strdir)

    return test_sub

@pytest.fixture(scope="function")
def sub_with_entries(sub):
    """Create a test subscription with faked entries."""
    sub.feed_state.entries = list(range(0, 20))

    sub.downloader = generate_fake_downloader()

    return sub
