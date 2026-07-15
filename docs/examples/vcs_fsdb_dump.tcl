# VCS UCLI FSDB example. Edit scopes, depths, and times for the failing test.
# SIMRESULTS is exported by simmer and keeps waves.fsdb in the expected result directory.
set wave_fid [dump -file "$::env(SIMRESULTS)/waves.fsdb" -type FSDB]

# Optional filters must precede the first dump -add command.
# dump -suppress_instance hdl_top.dut.memory_subsystem

# Depth 0 means all hierarchy below this scope; depth 1 means this scope only.
dump -add hdl_top.dut -fid $wave_fid -depth 0 -aggregates -fsdb_opt +packedmda+struct+parameter
dump -add hdl_top.env.agent -fid $wave_fid -depth 2 -aggregates -fsdb_opt +packedmda+struct+parameter

# Capture only the 1000 ns through 50000 ns interval.
dump -disable -fid $wave_fid
stop -absolute 1000ns -command {dump -enable -fid $wave_fid} -continue
stop -absolute 50000ns -command {dump -disable -fid $wave_fid; dump -flush $wave_fid} -continue

run
dump -flush $wave_fid
# UCLI cannot close one FSDB by ID; an ID-less close closes all open dump files.
dump -close
exit
