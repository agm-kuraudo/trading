#!/bin/bash
#
# Daily SPY VPA scan launcher (invoked by the Rundeck job on the Pi).
#
# SP-353: this script must propagate app_runner.py's exit status so a genuine scan
# failure reports RED in Rundeck. Previously the final command was the report `cp`,
# so the script always exited 0 even when `python app_runner.py` crashed with a
# traceback (e.g. the get_ohlcv OutOfMemory) — the failure was reported green and a
# stalled data feed could go unnoticed. We now capture the python exit code, still
# attempt the best-effort report copy, then exit with the captured code.

set -uo pipefail

source /usr/local/trading/.venv/bin/activate

# Use ${PYTHONPATH:-} so `set -u` does not abort when PYTHONPATH is unset (it is
# often unset under the Rundeck job's environment).
if [[ ":${PYTHONPATH:-}:" != *":/usr/local/trading:"* ]]; then
    export PYTHONPATH="${PYTHONPATH:-}:/usr/local/trading"
fi

cd /usr/local/trading/vpa
python app_runner.py
vpa_status=$?

# Best-effort: copy the latest report to the share regardless of the scan outcome,
# but never let the copy mask a scan failure. Guard against an empty log dir so a
# missing report doesn't itself crash the script and hide the real status.
cd /usr/local/trading/vpa/log/
last_updated_file=$(ls -t 2>/dev/null | head -n 1)
if [[ -n "$last_updated_file" ]]; then
    cp "$last_updated_file" /usr/local/my_share || true
fi

# Propagate the scan's exit status so Rundeck sees red when the scan failed.
exit "$vpa_status"
