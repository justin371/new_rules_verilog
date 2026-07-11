import io
import logging
import unittest

from lib.cmn_logging import CmnFormatter, build_logger


class CmnLoggingTest(unittest.TestCase):

    def test_color_formatting_uses_numeric_level_after_display_name_override(self):
        logging.addLevelName(logging.INFO, "%I")
        record = logging.LogRecord("unit", logging.INFO, __file__, 1, "hello", (), None)
        formatter = CmnFormatter("%(color_start)s%(levelname)s:%(message)s%(color_end)s", use_color=True)

        self.assertEqual("%I:hello", formatter.format(record))

    def test_rebuilding_logger_does_not_duplicate_handlers(self):
        logger = build_logger("cmn_logging_test", use_color=True)
        logger.handlers[0].setStream(io.StringIO())
        logger.warning("warning")
        logger = build_logger("cmn_logging_test", use_color=True)

        self.assertEqual(1, logger.warn_count)
        self.assertEqual(1, len(logger.handlers))


if __name__ == "__main__":
    unittest.main()
