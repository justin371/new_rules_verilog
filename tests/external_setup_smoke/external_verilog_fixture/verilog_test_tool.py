#!/usr/bin/env python3

import os
import sys


def main():
    filelist_index = sys.argv.index("-f") + 1
    filelist = sys.argv[filelist_index]
    top_source = sys.argv[-1]
    if not os.path.isfile(filelist):
        raise RuntimeError("external filelist is unavailable: {}".format(filelist))
    if not os.path.isfile(top_source):
        raise RuntimeError("external top source is unavailable: {}".format(top_source))


if __name__ == "__main__":
    main()
