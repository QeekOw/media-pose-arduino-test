# One-time Board setup. Run push-to-board.ps1 first. Needs no sudo.
# Installs uv, a standalone Python 3.12, and rebuilds ~/pose-venv (deleting any earlier one).
. "$PSScriptRoot\board.ps1"

$remote = @'
set -e
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.12.17/install.sh | sh
rm -rf ~/pose-venv
uv venv --python 3.12 ~/pose-venv
uv pip install --python ~/pose-venv/bin/python -r ~/bench/requirements-board.txt
~/pose-venv/bin/python -c "import sys, mediapipe; print('python', sys.version.split()[0], 'mediapipe', mediapipe.__version__)"
'@
$remote.Replace("`r", "") | ssh $BoardHost "bash -s"
if ($LASTEXITCODE -ne 0) { throw "board setup failed" }
