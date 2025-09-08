#!/bin/bash
set -e

# Detect project root (one level above scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Starting RPA System with Resource Optimizations..."

# Ensure volumes exist and have correct ownership for UID 1001 (rpauser)
for svc in orchestrator worker1 worker2; do
    mkdir -p "$PROJECT_ROOT/volumes/$svc/data"
    mkdir -p "$PROJECT_ROOT/volumes/$svc/logs"
    chown -R 1001:1001 "$PROJECT_ROOT/volumes/$svc"
done

# Function: build image if it doesn't exist
build_if_missing() {
    local image=$1
    local path=$2

    if ! podman image exists "$image"; then
        echo "📦 Image $image not found. Building from $path..."
        podman build -t "$image" "$path"
    else
        echo "✅ Image $image already exists"
    fi
}

# Ensure orchestrator image exists
build_if_missing "localhost/rpa-orchestrator:latest" "$PROJECT_ROOT/containers/orchestrator"

# Ensure worker image exists
build_if_missing "localhost/rpa-worker:latest" "$PROJECT_ROOT/containers/worker"

# Create network if it doesn't exist
podman network exists rpa-network || podman network create --driver bridge --subnet 172.18.0.0/16 rpa-network

# Start orchestrator
echo "Starting orchestrator..."
podman run -d \
    --replace \
    --name rpa-orchestrator \
    --hostname orchestrator \
    --network rpa-network \
    -p 8620:8620 \
    --env-file "$PROJECT_ROOT/configs/orchestrator.env" \
    -v "$PROJECT_ROOT/volumes/orchestrator/data:/app/data:Z" \
    -v "$PROJECT_ROOT/volumes/orchestrator/logs:/app/logs:Z" \
    --restart unless-stopped \
    --memory=1200m \
    --cpus=0.7 \
    localhost/rpa-orchestrator:latest

# Start worker 1 with INCREASED RESOURCES for Chrome
echo "Starting worker 1 with optimized browser resources..."
podman run -d \
    --replace \
    --name rpa-worker1 \
    --hostname worker1 \
    --network rpa-network \
    -p 8621:8621 \
    --env-file "$PROJECT_ROOT/configs/worker.env" \
    -v "$PROJECT_ROOT/volumes/worker1/data:/app/data:Z" \
    -v "$PROJECT_ROOT/volumes/worker1/logs:/app/logs:Z" \
    --restart unless-stopped \
    --memory=2048m \
    --cpus=1.0 \
    --shm-size=2g \
    --security-opt seccomp=unconfined \
    --cap-add SYS_ADMIN \
    -e WAIT_TIMEOUT=30 \
    -e LOGIN_RETRY_ATTEMPTS=5 \
    -e CHROME_EXTRA_ARGS="--disable-dev-shm-usage,--disable-extensions,--disable-plugins,--disable-images,--disable-javascript-harmony-shipping,--memory-pressure-off" \
    localhost/rpa-worker:latest

# Start worker 2 with INCREASED RESOURCES for Chrome
echo "Starting worker 2 with optimized browser resources..."
podman run -d \
    --replace \
    --name rpa-worker2 \
    --hostname worker2 \
    --network rpa-network \
    -p 8622:8621 \
    --env-file "$PROJECT_ROOT/configs/worker.env" \
    -v "$PROJECT_ROOT/volumes/worker2/data:/app/data:Z" \
    -v "$PROJECT_ROOT/volumes/worker2/logs:/app/logs:Z" \
    --restart unless-stopped \
    --memory=2048m \
    --cpus=1.0 \
    --shm-size=2g \
    --security-opt seccomp=unconfined \
    --cap-add SYS_ADMIN \
    -e WAIT_TIMEOUT=30 \
    -e LOGIN_RETRY_ATTEMPTS=5 \
    -e CHROME_EXTRA_ARGS="--disable-dev-shm-usage,--disable-extensions,--disable-plugins,--disable-images,--disable-javascript-harmony-shipping,--memory-pressure-off" \
    localhost/rpa-worker:latest

echo "⏳ Waiting for services to start..."
sleep 30

# Health checks
echo "Health Check Results:"
for service in "orchestrator:8620" "worker1:8621" "worker2:8622"; do
    name=$(echo $service | cut -d: -f1)
    port=$(echo $service | cut -d: -f2)

    if curl -f -s http://localhost:$port/health > /dev/null 2>&1; then
        echo "✅ $name (port $port): Healthy"
    else
        echo "❌ $name (port $port): Unhealthy"
        echo "  Checking logs for rpa-$name:"
        podman logs --tail=20 rpa-$name 2>/dev/null || echo "  Could not retrieve logs"
    fi
done

# Resource monitoring
echo ""
echo "📊 Resource Usage:"
podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" rpa-orchestrator rpa-worker1 rpa-worker2

echo ""
echo "🎉 RPA System Status Check Complete!"
echo "Access URLs:"
echo "  📊 Orchestrator: http://localhost:8620"
echo "  🤖 Worker 1: http://localhost:8621"
echo "  🤖 Worker 2: http://localhost:8622"
echo ""
echo "💡 Resource Optimizations Applied:"
echo "  ✅ Increased worker memory: 1400m → 2048m"
echo "  ✅ Increased worker CPU: 0.6 → 1.0"
echo "  ✅ Increased shared memory: 512m → 2g"
echo "  ✅ Added Chrome performance flags"
echo "  ✅ Increased timeout: 15s → 30s"
