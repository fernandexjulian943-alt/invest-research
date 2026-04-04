#!/bin/bash
# 交互式研究功能 — API 冒烟测试
# 用法: bash tests/test_interactive_api.sh [host:port]
# 默认: localhost:8001

BASE="${1:-localhost:8001}"
PASS=0
FAIL=0
TASK_ID=""

green() { echo -e "\033[32m✅ $1\033[0m"; ((PASS++)); }
red() { echo -e "\033[31m❌ $1\033[0m"; ((FAIL++)); }

echo "=== 交互式研究 API 冒烟测试 ==="
echo "目标: $BASE"
echo ""

# 测试 1: 创建交互式研究（股票代码）
echo "--- 测试 1: POST /api/research/interactive（股票代码 600519）"
RESP=$(curl -s -X POST "http://$BASE/api/research/interactive" \
  -H "Content-Type: application/json" \
  -d '{"stock_code": "600519"}')
TASK_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)
if [[ ${#TASK_ID} -eq 12 ]]; then
  green "创建成功，task_id=$TASK_ID"
else
  red "创建失败，响应: $RESP"
fi

# 等待后端处理
sleep 3

# 测试 2: 查询任务状态
echo "--- 测试 2: GET /api/research/$TASK_ID/status"
RESP=$(curl -s "http://$BASE/api/research/$TASK_ID/status")
STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
STOCK=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stock_code',''))" 2>/dev/null)
if [[ "$STATUS" == "company_loaded" || "$STATUS" == "strategy_proposed" ]]; then
  green "状态正常: status=$STATUS, stock_code=$STOCK"
else
  red "状态异常: $RESP"
fi

# 等待策略生成
if [[ "$STATUS" == "company_loaded" ]]; then
  echo "    等待策略生成..."
  for i in {1..20}; do
    sleep 3
    RESP=$(curl -s "http://$BASE/api/research/$TASK_ID/status")
    STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    if [[ "$STATUS" == "strategy_proposed" ]]; then
      break
    fi
  done
fi

# 测试 3: 确认策略（无修改）
echo "--- 测试 3: POST /api/research/$TASK_ID/confirm-strategy（无修改）"
RESP=$(curl -s -X POST "http://$BASE/api/research/$TASK_ID/confirm-strategy" \
  -H "Content-Type: application/json" \
  -d '{"edits": {}, "auto_weekly": false}')
OK=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok',''))" 2>/dev/null)
if [[ "$OK" == "True" ]]; then
  green "策略确认成功"
else
  red "策略确认失败: $RESP"
fi

# 测试 4: 创建交互式研究（公司名称）
echo "--- 测试 4: POST /api/research/interactive（公司名称'贵州茅台'）"
RESP=$(curl -s -X POST "http://$BASE/api/research/interactive" \
  -H "Content-Type: application/json" \
  -d '{"stock_code": "贵州茅台"}')
TASK_ID2=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)
if [[ ${#TASK_ID2} -eq 12 ]]; then
  green "中文名称解析成功，task_id=$TASK_ID2"
else
  red "中文名称解析失败: $RESP"
fi

# 测试 5: 查询不存在的 task_id
echo "--- 测试 5: GET /api/research/000000000000/status（不存在的任务）"
RESP=$(curl -s -o /dev/null -w "%{http_code}" "http://$BASE/api/research/000000000000/status")
if [[ "$RESP" == "404" || "$RESP" == "400" ]]; then
  green "错误处理正确，HTTP $RESP"
else
  red "未正确处理不存在的任务，HTTP $RESP"
fi

echo ""
echo "=== 结果: $PASS 通过 / $FAIL 失败 ==="
