#!/bin/bash

source /usr/local/trading/.venv/bin/activate

if [[ ":$PYTHONPATH:" != *":/usr/local/trading:"* ]]; then
    export PYTHONPATH="$PYTHONPATH:/usr/local/trading"
fi

# SP-356: the orchestrator is a module (vpa.reports.daily_market_report), not a
# script path, so run it from /usr/local/trading where the module path resolves.
# Capture its exit status immediately so the copy step below cannot clobber it
# (Req 10.2, 10.4 — Rundeck sees the orchestrator's own exit code).
cd /usr/local/trading
python -m vpa.reports.daily_market_report
status=$?

# SP-356 (Req 1.5, 1.6): deliver the Consolidated_Daily_Report to the share
# deterministically BY NAME, not "latest file wins". The orchestrator writes it
# to vpa/log/consolidated_report_YYYYMMDD.txt, so copy THAT specific file for
# today's date. Overridable via VPA_SHARE_DIR so a future relocation is a single
# env change.
share_dir="${VPA_SHARE_DIR:-/mnt/data/my_share}"
report_file="/usr/local/trading/vpa/log/consolidated_report_$(date +%Y%m%d).txt"
if [[ -f "$report_file" ]]; then
    cp "$report_file" "$share_dir"
fi

# Exit with the orchestrator's own status (Req 10.2, 10.4) so Rundeck's job
# status reflects whether the report was produced, not the copy result.
exit $status
