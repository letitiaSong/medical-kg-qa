#!/usr/bin/env bash
# 一键跑通离线全流程（不需要 TuGraph / API Key）
# 用法：bash scripts/run_all.sh [python可执行文件]
set -euo pipefail

PY="${1:-python}"
export PYTHONIOENCODING=utf-8

run() {
  echo
  echo "======================================================================"
  echo "[$1] $2"
  echo "======================================================================"
  # shellcheck disable=SC2086
  $PY $2
}

run "1/8 环境自检"    "scripts/00_check_env.py"
run "2/8 清洗 + 抽取" "scripts/01_preprocess.py"
run "3/8 构图 + 入图" "scripts/02_build_graph.py --mock"
run "4/8 入图验证"    "scripts/03_verify_graph.py --mock"
run "5/8 生成测试集"  "scripts/build_testset.py"
run "6/8 评测对比"    "scripts/05_evaluate.py --mock"
run "7/8 批量问答"    "scripts/04_ask.py --mock --fake"
run "8/8 问答演示"    "cli.py --mock --llm fake --demo"

echo
echo "全部完成。产物在 outputs/ 与 data/graph/，报告见 docs/实验报告.docx"