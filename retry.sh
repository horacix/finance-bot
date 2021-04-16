#!/bin/bash

source venv/bin/activate

python mint-refresh.py
sleep 120

MAX_ATTEMPTS=5
attempt_num=1
until python $1 || (( attempt_num == MAX_ATTEMPTS ))
do
    echo "Attempt $attempt_num failed! Trying again in $attempt_num minutes..."
    sleep $(( 60 * attempt_num++ ))
    killall chromedriver
    killall chromium-browse
done

killall chromedriver
killall chromium-browse

deactivate
