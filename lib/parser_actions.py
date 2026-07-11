#!/usr/bin/env python

import argparse


class TestAction(argparse.Action):

    class TestArg():

        def __init__(self, btiglob):
            self.btiglob = btiglob
            self.tag = set()
            self.ntag = set()

        def __repr__(self):
            return "TestArg(btiglob='{}', tags={}, ntags={})".format(self.btiglob, self.tag, self.ntag)

    def __call__(self, parser, namespace, values, option_string=None):
        ta = self.__class__.TestArg(values)
        getattr(namespace, self.dest).append(ta)


class TagAction(argparse.Action):

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            last_test = namespace.tests[-1]
        except IndexError:
            return # The return is actually more graceful than the explicit value error
            # It relies upon argparse to catch the missing option and throw a better formatted error
            # raise ValueError("Attempted to use a test tag filter without any tests specified. Did you forget the '-t' flag?")
        l = getattr(last_test, self.dest)
        l.add(values)


class GlobalTagAction(argparse.Action):

    def __call__(self, parser, namespace, values, option_string=None):
        gt = getattr(namespace, self.dest)
        gt.add(values)


class XpropAction(argparse.Action):
    legal_xprop_options = {
        'C': 'C - Compute as ternary (CAT)',
        'F': 'F - Forward only X (FOX)',
        'D': 'D - Disable xprop',
    }

    def __call__(self, parser, args, values, option_string=None):
        if values in ['C', 'F']:
            setattr(args, self.dest, values)
        elif values == 'D':
            setattr(args, self.dest, None)
        else:
            parser.error("Illegal xprop value {}, only the following are allowed:\n  {}".format(
                values, "\n  ".join(["{} : {}".format(ii, jj) for ii, jj in self.legal_xprop_options.items()])))


class CovAction(argparse.Action):
    legal_coverage_options = {
        'B': 'Block - For enabling block coverage',
        'E': 'Expr - For enabling expression coverage',
        'F': 'Fsm - For enabling fsm coverage',
        'T': 'Toggle - For enabling toggle coverage',
        'U': 'fUnctional - For enabling functional coverage',
        'A': 'All - For enabling all supported coverage types'
    }

    @classmethod
    def format_options(cls, indent=2):
        return f"\n{' '*indent}".join(["{} : {}".format(ii, jj) for ii, jj in cls.legal_coverage_options.items()])

    def __call__(self, parser, args, values, option_string=None):
        cov_options = values.split(':')
        for cov_option in cov_options:
            if cov_option not in self.legal_coverage_options:
                parser.error(
                    "Illegal XRUN coverage value {}\nRequires a colon-separated list of the following values:\n  {}".
                    format(cov_option, self.format_options()))
        setattr(args, self.dest, values)


class CMAction(argparse.Action):
    legal_coverage_options = {
        'line': 'Line - For enabling line coverage',
        'cond': 'Condition - For enabling condition coverage',
        'fsm': 'Fsm - For enabling fsm coverage',
        'tgl': 'Toggle - For enabling toggle coverage',
        'branch': 'Branch - For enabling branch coverage',
        'assert': 'Assert - For enabling assert coverage',
        'A': 'All - For enabling all supported coverage types'
    }

    @classmethod
    def format_options(cls, indent=2):
        return f"\n{' '*indent}".join(["{} : {}".format(ii, jj) for ii, jj in cls.legal_coverage_options.items()])

    def __call__(self, parser, args, values, option_string=None):
        cov_options = values.split('+')
        for cov_option in cov_options:
            if cov_option not in self.legal_coverage_options:
                parser.error(
                    "Illegal VCS coverage value {}\nRequires a plus-separated list of the following values:\n  {}".
                    format(cov_option, self.format_options()))
        setattr(args, self.dest, values)
