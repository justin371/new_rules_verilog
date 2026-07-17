import os
import sys

BIN_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.dirname(BIN_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if __package__:
    from .args_parse import parse_args as parse_args
else:
    from args_parse import parse_args as parse_args

__all__ = ["parse_args"]
