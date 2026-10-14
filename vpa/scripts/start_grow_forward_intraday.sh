#!/bin/bash

source /usr/local/trading/.venv/bin/activate

if [[ ":$PYTHONPATH:" != *":/usr/local/trading:"* ]]; then
    export PYTHONPATH="$PYTHONPATH:/usr/local/trading"
fi

cd /usr/local/trading
python -m vpa.scripts.grow_forward_intraday
exit $?
