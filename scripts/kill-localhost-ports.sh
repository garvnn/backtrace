#!/usr/bin/env bash
# Kill processes on common dev ports (3000 = React, 8000 = FastAPI)
set -e
for port in 3000 8000; do
  pid=$(lsof -ti :$port 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "Killing PID(s) $pid on port $port"
    kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
  else
    echo "Nothing listening on port $port"
  fi
done
echo "Done."
