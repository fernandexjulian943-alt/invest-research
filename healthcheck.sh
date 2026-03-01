#!/bin/bash
# invest-research 健康检查，不通则重启服务
resp=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://localhost:8001/api/stock/quote?code=000001")
if [ "$resp" != "200" ]; then
    echo "$(date): 健康检查失败(HTTP $resp)，重启服务" >> /var/log/invest-research-health.log
    systemctl restart invest-research
else
    echo "$(date): OK" >> /var/log/invest-research-health.log
fi
# 日志保留最近200行
tail -200 /var/log/invest-research-health.log > /tmp/ir-health.tmp && mv /tmp/ir-health.tmp /var/log/invest-research-health.log
