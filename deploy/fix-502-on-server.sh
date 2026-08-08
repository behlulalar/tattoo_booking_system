#!/usr/bin/env bash
# SADECE Roof Tattoo — diğer sistemlere dokunmaz
# Sunucuda: bash /opt/roof_tattoo/deploy/fix-502-on-server.sh
exec bash "$(dirname "$0")/fix-roof-only-on-server.sh" "$@"
