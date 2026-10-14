#!/bin/bash

source /usr/local/trading/.venv/bin/activate

if [[ ":$PYTHONPATH:" != *":/usr/local/trading:"* ]]; then
    export PYTHONPATH="$PYTHONPATH:/usr/local/trading"
fi

cd /usr/local/trading/vpa
python app_all_shares.py

# SP-374: the Log_Share was relocated onto the USB (/mnt/data/my_share) by SP-338,
# so copy the daily report there (not the old /usr/local/my_share, which was removed).
# Overridable via VPA_SHARE_DIR so a future relocation is a single env change.
share_dir="${VPA_SHARE_DIR:-/mnt/data/my_share}"
cd /usr/local/trading/vpa/log/
last_updated_file=$(ls -t | head -n 1)

cp "$last_updated_file" "$share_dir"
