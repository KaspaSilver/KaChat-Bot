#!/bin/sh
# KaChat Bot: start as root only long enough to hand /state to the bot user, then run as it
# (BOT-008: the container holds hot wallet keys). /conf/bots.json is the panel's (read-only
# here); an older panel left it readable only by root, so until the panel is updated the bot
# keeps running as root rather than stop every bot, and says so.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p /state
    chown -R bot:bot /state 2>/dev/null || true
    if [ ! -e /conf/bots.json ] || setpriv --reuid=bot --regid=bot --init-groups test -r /conf/bots.json; then
        exec setpriv --reuid=bot --regid=bot --init-groups "$@"
    fi
    echo "kachat-bot: /conf/bots.json is not readable by the bot user yet; running as root until the Kaspa Quick Start panel is updated" >&2
fi
exec "$@"
