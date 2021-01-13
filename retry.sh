#!/bin/bash

source venv/bin/activate

MAX_ATTEMPTS=5
attempt_num=1
until python $1 || (( attempt_num == MAX_ATTEMPTS ))
do
    echo "Attempt $attempt_num failed! Trying again in $attempt_num seconds..."
    sleep $(( attempt_num++ ))
done

deactivate
