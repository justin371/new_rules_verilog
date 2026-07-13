#!/usr/bin/env python
"""Add new functionality to allow logger to exit."""

import logging
import sys
from datetime import datetime

CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
ERROR = logging.ERROR
WARNING = logging.WARNING
WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG
NOTSET = logging.NOTSET

# Override standard level display names to be fixed width
LEVEL_NAMES = {'INFO': '%I', 'DEBUG': '%D', 'ERROR': '%E', 'WARNING': '%W', 'CRITICAL': '%F'}

COLOR_RED = '\033[0;31m'
COLOR_NC = '\033[0m'

# pylint: disable=bad-whitespace
LEVEL_TO_COLOR = {
    INFO: ("", ""),
    DEBUG: ("", ""),
    ERROR: (COLOR_RED, COLOR_NC),
    WARNING: (COLOR_RED, COLOR_NC),
    CRITICAL: (COLOR_RED, COLOR_NC),
}
# pylint: enable=bad-whitespace


class CmnLogger(logging.getLoggerClass()):
    """Extended logger that tracks error counts."""

    def __init__(self, *args, **kwargs):
        self.warn_count = 0
        self.error_count = 0
        super(CmnLogger, self).__init__(*args, **kwargs)
        self.reset_stopwatch()
        self._last_message_was_summary = False

    def exit_if_warnings_or_errors(self, *args, **kwargs):
        """Log a critical message if any errors or warning have occurred."""
        if self.warn_count or self.error_count:
            self.critical(*args, **kwargs)

    def debug(self, *args, **kwargs): # pylint: disable=missing-docstring
        self._last_message_was_summary = False
        super(CmnLogger, self).debug(*args, **kwargs)

    def info(self, *args, **kwargs): # pylint: disable=missing-docstring
        self._last_message_was_summary = False
        super(CmnLogger, self).info(*args, **kwargs)

    def warning(self, *args, **kwargs): # pylint: disable=missing-docstring
        self.warn_count += 1
        self._last_message_was_summary = False
        super(CmnLogger, self).warning(*args, **kwargs)

    def warn(self, *args, **kwargs): # pylint: disable=missing-docstring
        self.warning(*args, **kwargs)

    def error(self, *args, **kwargs): # pylint: disable=missing-docstring
        self.error_count += 1
        self._last_message_was_summary = False
        super(CmnLogger, self).error(*args, **kwargs)

    def critical(self, *args, **kwargs):
        """Script will exit with bad status if called."""
        self._last_message_was_summary = False
        super(CmnLogger, self).critical(*args, **kwargs)
        sys.exit(1)

    def summary(self, *args, **kwargs):
        """Add some decoration to make a line pop a bit more."""
        if not self._last_message_was_summary:
            self.info('-' * 72)
        self.info(*args, **kwargs)
        self.info('-' * 72)
        self._last_message_was_summary = True

    def reset_stopwatch(self):
        self._start_time = datetime.now()

    def stop_stopwatch(self):
        self._stop_time = datetime.now()

    @property
    def start_time(self):
        return self._start_time

    @property
    def stop_time(self):
        return self._stop_time

    @property
    def duration(self):
        return self.stop_time - self.start_time

    @property
    def duration_in_microseconds(self):
        return self.duration.seconds * (10**6) + self.duration.microseconds

    @property
    def timestamp(self):
        return datetime.now()

    @property
    def timestamp_delta(self):
        return datetime.now() - self._start_time

    @property
    def timestamp_in_microseconds(self):
        delta = self.timestamp_delta
        return delta.seconds * (10**6) + delta.microseconds


class CmnFormatter(logging.Formatter):
    """Provide hook for translation from record level to color."""

    def __init__(self, *args, **kwargs):
        self.use_color = kwargs['use_color']
        del kwargs['use_color']
        logging.Formatter.__init__(self, *args, **kwargs)

    def format(self, record):
        if self.use_color:
            record.color_start, record.color_end = LEVEL_TO_COLOR.get(record.levelno, ("", ""))
        else:
            record.color_start, record.color_end = "", ""
        # record.levelname = LEVEL_NAMES[record.levelname]
        return super(CmnFormatter, self).format(record)


def build_logger(name, level=logging.INFO, use_color=False, filehandler=None):
    """Create a logger, console handler and formatter.
    Do this in one function to allow for more uniformity across tools.
    """
    logging.setLoggerClass(CmnLogger)

    # Override standard level display names to be fixed width
    logging.addLevelName(INFO, "%I") # pylint: disable=bad-whitespace
    logging.addLevelName(DEBUG, "%D") # pylint: disable=bad-whitespace
    logging.addLevelName(ERROR, "%E") # pylint: disable=bad-whitespace
    logging.addLevelName(WARNING, "%W") # pylint: disable=bad-whitespace
    logging.addLevelName(CRITICAL, "%F") # pylint: disable=bad-whitespace

    log = logging.getLogger(name)
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    log.propagate = False
    if filehandler:
        log.setLevel(DEBUG)
    else:
        log.setLevel(level)

    formatter = CmnFormatter('%(color_start)s%(levelname)s:%(name)s: %(message)s%(color_end)s', use_color=use_color)

    shandler = logging.StreamHandler()
    shandler.setFormatter(formatter)
    shandler.setLevel(level)
    log.addHandler(shandler)

    if filehandler:
        # Change mode to 'w' to overwrite the file instead of appending
        fhandler = logging.FileHandler(filehandler, mode='w')
        fhandler.setFormatter(formatter)
        log.addHandler(fhandler)

    return log


def _simple_test():
    """Testing only
    Runs a simple sequence for manual comparison
    """
    log = build_logger("main")
    log.debug("This message shouldn't print based on default level of info.")
    log.info("Message 1 prints.")
    log.exit_if_warnings_or_errors("Will not exit due to lack of previous errors")
    log.info("Message 2 prints.")
    log.error("Message 3 is an error and it will print.")
    log.exit_if_warnings_or_errors("Message 4: exiting due to errors. "
                                   "This is the last message to print.")
    log.info("Will not get to this point.")
    # Expected output
    # INFO:main:Message 1 prints.
    # INFO:main:Message 2 prints.
    # ERROR:main:Message 3 is an error and it will print.
    # CRITICAL:main:Message 4: exiting due to errors. This is the last message to print.


if __name__ == '__main__':
    _simple_test()
