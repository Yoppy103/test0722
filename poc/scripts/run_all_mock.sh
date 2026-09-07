#!/usr/bin/env bash
# モックサーバ相手に PoC 一式を通しで実行する（トライアル環境なしで動作確認できる）。
#
#   ./scripts/run_all_mock.sh                     # 正常系
#   MOCK_SMAREGI_GROUP_PRICE=off ./scripts/run_all_mock.sh   # 顧客グループ別価格が使えない場合
set -uo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-8899}"
MOCK="http://127.0.0.1:${PORT}"
OUT="${OUT:-out/mock}"

rm -rf "$OUT"; mkdir -p "$OUT"

python3 mock/mock_server.py --port "$PORT" &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null' EXIT

# 起動待ち（固定 sleep ではなく応答を見る）
for _ in $(seq 1 50); do
  curl -s -o /dev/null "${MOCK}/shop/login" && break
  sleep 0.2
done

run() { echo; echo "--------------------------------------------- $*"; python3 "$@"; }

run scripts/10_seed_smaregi.py    --mock "$MOCK" --out "$OUT"
run scripts/11_seed_bcart.py      --mock "$MOCK" --out "$OUT"
run scripts/00_probe_capabilities.py --mock "$MOCK" --out "$OUT"
run scripts/20_update_prices_smaregi.py --mock "$MOCK" --out "$OUT"
run scripts/21_update_prices_bcart.py   --mock "$MOCK" --out "$OUT"
run scripts/30_verify_reflection.py     --mock "$MOCK" --out "$OUT" --shop-url "$MOCK"
run scripts/40_make_report.py           --out "$OUT"

echo
echo "=== 完了: ${OUT}/REPORT.md ==="
