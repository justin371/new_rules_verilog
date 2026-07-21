# Default VCS lint options for verilog_rtl_lint_test.
# Projects can override the rulefile_vcs attribute to replace this policy.
+lint=all,noVCDE
+warn=all
# Standalone lint tops intentionally leave their external interface ports open.
-suppress=SV-UIP
