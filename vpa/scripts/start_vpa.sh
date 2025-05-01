#!/bin/bash

source /usr/local/trading/venv/bin/activate

if [[ ":$PYTHONPATH:" != *":/usr/local/trading:"* ]]; then
    export PYTHONPATH="$PYTHONPATH:/usr/local/trading"
fi

cd /usr/local/trading/vpa
python app_runner.py

cd /usr/local/trading/vpa/log/
last_updated_file=$(ls -t | head -n 1)
cp "$last_updated_file" /home/mypi/shared
