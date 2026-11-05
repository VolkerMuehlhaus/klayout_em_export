#!/usr/bin/env bash
# Sparse checkout of the IHP-Open-PDK KLayout pcell library into tests/pdk (Linux, or Git Bash on Windows).
# Usage: tests/setup_pdk.sh [commit-ish]   default: the commit the tests were last run with
# Only libs.tech/klayout/python, tech/*.lyp,*.lyt and the LVS deck tech/lvs (without its testing/) are checked
# out. The submodules pycell4klayout-api and pypreprocessor are fetched at the commits the PDK pins.
set -euo pipefail
cd "$(dirname "$0")"
REV="${1:-5e6d592e}"
if [ -e pdk ]; then echo "tests/pdk exists, delete it first"; exit 1; fi

git clone --filter=blob:none --sparse --no-checkout https://github.com/IHP-GmbH/IHP-Open-PDK pdk
cd pdk
MSYS_NO_PATHCONV=1 git sparse-checkout set --no-cone \
    '/ihp-sg13g2/libs.tech/klayout/python/' \
    '/ihp-sg13g2/libs.tech/klayout/tech/*.lyp' \
    '/ihp-sg13g2/libs.tech/klayout/tech/*.lyt' \
    '/ihp-sg13g2/libs.tech/klayout/tech/lvs/' \
    '!/ihp-sg13g2/libs.tech/klayout/tech/lvs/testing/'
git checkout -q "$REV"
echo "PDK at $(git log --oneline -1)"

PY=ihp-sg13g2/libs.tech/klayout/python
P4K=$(git ls-tree HEAD "$PY/pycell4klayout-api" | awk '{print $3}')
PPP=$(git ls-tree HEAD "$PY/pypreprocessor" | awk '{print $3}')

fetch() {  # url commit target
    git init -q "$3"
    git -C "$3" fetch -q --depth 1 "$1" "$2"
    git -C "$3" checkout -q FETCH_HEAD
}
fetch https://github.com/IHP-GmbH/pycell4klayout-api "$P4K" ../_p4k
fetch https://github.com/IHP-GmbH/pypreprocessor "$PPP" ../_ppp
cp -r ../_p4k/source "$PY/pycell4klayout-api/"
mkdir -p "$PY/pypreprocessor"
cp -r ../_ppp/pypreprocessor "$PY/pypreprocessor/"
rm -rf ../_p4k ../_ppp
echo "pycell4klayout-api $P4K, pypreprocessor $PPP"
