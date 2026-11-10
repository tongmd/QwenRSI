#!/usr/bin/env bash
set -euo pipefail
# Run from the checkout. Explicitly provide the Python executable and pinned base model path.
QWENRSI_PYTHON=${QWENRSI_PYTHON:-.venv/bin/python}
QWENRSI_MODEL=${QWENRSI_MODEL:-models/Qwen3.5-4B}
QWENRSI_RUN_ID=${QWENRSI_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export QWENRSI_CODE_REVISION=${QWENRSI_CODE_REVISION:-$(git rev-parse HEAD 2>/dev/null || cat CODE_REVISION)}
mkdir -p runs
OUT="runs/$QWENRSI_RUN_ID"
mkdir "$OUT"
trap 'code=$?; printf "failed exit=%s\n" "$code" > "$OUT/STATUS"; exit "$code"' ERR
printf 'waiting-for-base-model\n' > "$OUT/STATUS"
for _ in $(seq 1 240); do
  if [ -f "$QWENRSI_MODEL/model.safetensors-00001-of-00002.safetensors" ] && \
     [ -f "$QWENRSI_MODEL/model.safetensors-00002-of-00002.safetensors" ]; then
    break
  fi
  sleep 10
done
test -f "$QWENRSI_MODEL/model.safetensors-00002-of-00002.safetensors"
"$QWENRSI_PYTHON" -c 'import json,sys,torch,transformers,triton; print(json.dumps({"python":sys.version,"torch":torch.__version__,"transformers":transformers.__version__,"triton":triton.__version__,"gpu":torch.cuda.get_device_name(0)},indent=2))' > "$OUT/environment.json"
printf 'evolving\n' > "$OUT/STATUS"
"$QWENRSI_PYTHON" -m qwenrsi.cli evolve examples/baseline.c --model "$QWENRSI_MODEL" \
    --iterations 3 --out "$OUT/evolution"
SELECTED=$(cat "$OUT/evolution/SELECTED")
CONTROLLER="$OUT/evolution/$SELECTED"
printf 'auditing-circuit\n' > "$OUT/STATUS"
"$QWENRSI_PYTHON" -m qwenrsi.cli audit-circuit "$CONTROLLER" \
    --samples 32 --out "$OUT/circuit-audit.json"
"$QWENRSI_PYTHON" -m qwenrsi.cli eval "$CONTROLLER" --backend cuda --count 16 \
    --out "$OUT/circuit-workflows.json"
"$QWENRSI_PYTHON" -m qwenrsi.cli build examples/verified.c --out "$OUT/human-comparison"
"$QWENRSI_PYTHON" -m qwenrsi.cli eval "$OUT/human-comparison" --seed 3301 --count 256 \
    --out "$OUT/human-comparison/results.json"
printf 'python-repair-pilot\n' > "$OUT/STATUS"
"$QWENRSI_PYTHON" -m qwenrsi.cli coding-eval "$CONTROLLER" --model "$QWENRSI_MODEL" \
    --tasks examples/coding_tasks.json --backend cuda --out "$OUT/coding-selected"
"$QWENRSI_PYTHON" -m qwenrsi.cli coding-eval "$OUT/evolution/v000" --model "$QWENRSI_MODEL" \
    --tasks examples/coding_tasks.json --backend reference --out "$OUT/coding-baseline"
printf 'exporting\n' > "$OUT/STATUS"
"$QWENRSI_PYTHON" -m qwenrsi.cli export "$CONTROLLER" --out "$OUT/model" \
    --base-model Qwen/Qwen3.5-4B
printf 'complete\n' > "$OUT/STATUS"
