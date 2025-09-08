#!/bin/bash
echo "📊 RPA System Status"
echo "===================="

echo ""
echo "Container Status:"
podman ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(NAMES|rpa-)"

echo ""
echo "Resource Usage:"
podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null | grep -E "(NAME|rpa-)" || echo "No running containers"

echo ""
echo "Network Status:"
if podman network exists rpa-network; then
    echo "✅ RPA Network: Active"
else
    echo "❌ RPA Network: Not found"
fi
