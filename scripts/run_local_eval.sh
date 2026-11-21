#!/usr/bin/env bash
# Runs the full evaluation with local Ollama models and saves the reports in results/.
# Usage: bash scripts/run_local_eval.sh [--push]
set -euo pipefail
cd "$(dirname "$0")/.."

command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com/download"; exit 1; }
ollama list >/dev/null 2>&1 || { echo "Start the Ollama app, then run this again."; exit 1; }

PY=${PYTHON:-python3}
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt

python -m ayw demo-data

MODELS=(${MODELS:-qwen2.5-coder:3b qwen2.5-coder:7b})
for m in "${MODELS[@]}"; do
  ollama pull "$m"
  python -m ayw eval --model "$m" --adversarial
done
# Ablation: whole schema in the prompt instead of retrieved tables
python -m ayw eval --model "${MODELS[0]}" --no-retrieval

echo; echo "Reports written to results/:"; ls -1 results

if [ "${1:-}" = "--push" ]; then
  git add results
  git commit -m "Add evaluation results for local models"
  git push
fi
