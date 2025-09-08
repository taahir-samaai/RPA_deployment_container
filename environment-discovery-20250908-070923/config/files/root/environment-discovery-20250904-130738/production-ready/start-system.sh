#!/bin/bash
set -e

# Determine project root (one level above scripts/)
PROJECT_ROOT="/opt"

echo "🚀 Starting RPA System..."

# Ensure volumes exist
mkdir -p "/volumes/data"
mkdir -p "/volumes/logs"

# Function to build image if missing
build_if_missing() {
    local image=
    local path=

    if ! podman image exists ""; then
        echo "📦 Image  not found. Building from ..."
        podman build -t "" ""
    else
        echo "✅ Image  already exists"
    fi
}

# Ensure orchestrator image exists
build_if_missing "localhost/rpa-orchestrator:latest" "/containers/orchestrator"

# Ensure worker image exists
build_if_missing "localhost/rpa-worker:latest" "/containers/worker"

# Create network if it doesn't exist
podman network exists rpa-network || podman network create --driver bridge --subnet 172.18.0.0/16 rpa-network

# Start orchestrator
echo "Starting orchestrator..."
podman run -d     --replace     --name rpa-orchestrator     --hostname orchestrator     --network rpa-network     -p 8620:8620     --env-file "/configs/orchestrator.env"     -v "/volumes/data:/app/data:Z"     -v "/volumes/logs:/app/logs:Z"     --restart unless-stopped     --memory=1200m     --cpus=0.7     localhost/rpa-orchestrator:latest

# Start worker 1
echo "Starting worker 1..."
podman run -d     --replace     --name rpa-worker1     --hostname worker1     --network rpa-network     -p 8621:8621     --env-file "/configs/worker.env"     -v "/volumes/data:/app/data:Z"     -v "/volumes/logs:/app/logs:Z"     --restart unless-stopped     --memory=1400m     --cpus=0.6     --shm-size=512m     --security-opt seccomp=unconfined     --cap-add SYS_ADMIN     localhost/rpa-worker:latest

# Start worker 2
echo "Starting worker 2..."
podman run -d     --replace     --name rpa-worker2     --hostname worker2     --network rpa-network     -p 8622:8621     --env-file "/configs/worker.env"     -v "/volumes/data:/app/data:Z"     -v "/volumes/logs:/app/logs:Z"     --restart unless-stopped     --memory=1400m     --cpus=0.6     --shm-size=512m     --security-opt seccomp=unconfined     --cap-add SYS_ADMIN     localhost/rpa-worker:latest

echo "⏳ Waiting for services to start..."
sleep 30

# Health checks
echo "Health Check Results:"
for service in "orchestrator:8620" "worker1:8621" "worker2:8622"; do
    name=
    port=

    if curl -f -s http://localhost:/health > /dev/null 2>&1; then
        echo "✅  (port ): Healthy"
    else
        echo "❌  (port ): Unhealthy"
        echo "  Checking logs for rpa-:"
        podman logs --tail=5 rpa- 2>/dev/null || echo "  Could not retrieve logs"
    fi
done

echo ""
echo "🎉 RPA System Status Check Complete!"
echo "Access URLs:"
echo "  📊 Orchestrator: http://localhost:8620"
echo "  🤖 Worker 1: http://localhost:8621"
echo "  🤖 Worker 2: http://localhost:8622"
