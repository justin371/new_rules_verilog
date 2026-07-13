def validate_explicit_switches(switches, owner, selected, parser):
    if switches:
        parser.error("The following switches are {}-only and cannot be used with {}: {}. "
                     "Stopping before Bazel starts.".format(owner, selected, ", ".join(switches)))
