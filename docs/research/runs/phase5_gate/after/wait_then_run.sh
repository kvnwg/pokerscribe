#!/bin/sh
# Start the post-gate script once the gate process has written its last line.
until grep -q '^exit ' /root/bp/gate/err.log 2>/dev/null || [ -f /root/bp/gate/standard-k200/done.json -a -z "$(pgrep -f 'blueprint-gate gate')" ]; do sleep 20; done
sleep 5
exec /root/bp/after/run.sh > /root/bp/after/run.log 2>&1
