#!/bin/bash
# invest-research 健康检查，不通则重启服务

# 投研任务运行期间跳过检查，避免误杀长时间任务
LOCK_FILE="/tmp/invest-research-running.lock"
if [ -f "$LOCK_FILE" ]; then
    echo "$(date): 投研任务运行中，跳过健康检查" >> /var/log/invest-research-health.log
else
    resp=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:8001/api/health")
    if [ "$resp" != "200" ]; then
        echo "$(date): 健康检查失败(HTTP $resp)，重启服务" >> /var/log/invest-research-health.log
        systemctl restart invest-research
    else
        echo "$(date): OK" >> /var/log/invest-research-health.log
    fi
fi
# 日志保留最近200行
tail -200 /var/log/invest-research-health.log > /tmp/ir-health.tmp && mv /tmp/ir-health.tmp /var/log/invest-research-health.log
