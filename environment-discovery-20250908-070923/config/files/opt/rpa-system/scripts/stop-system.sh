#!/bin/bash
echo "🛑 Stopping RPA System..."

podman stop rpa-orchestrator rpa-worker1 rpa-worker2 2>/dev/null || true
podman rm rpa-orchestrator rpa-worker1 rpa-worker2 2>/dev/null || true

echo "✅ RPA System stopped"
