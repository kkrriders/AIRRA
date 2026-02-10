import random
import time
from datetime import datetime

from flask import Flask, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest

app = Flask(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['service', 'endpoint']
)

MEMORY_USAGE = Gauge(
    'process_resident_memory_bytes',
    'Memory usage in bytes',
    ['service']
)

CPU_USAGE = Gauge(
    'process_cpu_seconds_total',
    'CPU usage',
    ['service']
)

ERROR_RATE = Gauge(
    'error_rate',
    'Error rate',
    ['service']
)

# Service state
service_name = "payment-service"
normal_mode = True
incident_mode = False

# Baseline metrics
baseline_memory = 2 * 1024 * 1024 * 1024  # 2GB
baseline_cpu = 0.35
baseline_latency = 0.5
baseline_error_rate = 0.001


@app.route('/')
def home():
    """Service home page."""
    return {
        "service": service_name,
        "status": "running",
        "mode": "incident" if incident_mode else "normal",
        "endpoints": {
            "metrics": "/metrics",
            "health": "/health",
            "trigger_incident": "/trigger-incident",
            "resolve_incident": "/resolve-incident"
        }
    }


@app.route('/health')
def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint."""
    # Update metrics based on mode
    if incident_mode:
        # Simulate incident: high memory, high CPU, slow responses
        memory = baseline_memory * random.uniform(3.5, 4.5)  # 7-9GB
        cpu = baseline_cpu * random.uniform(2.0, 3.0)  # 70-105%
        latency = baseline_latency * random.uniform(5.0, 8.0)  # 2.5-4s
        error_rate = baseline_error_rate * random.uniform(15.0, 30.0)  # 1.5-3%
    else:
        # Normal operation with small variations
        memory = baseline_memory * random.uniform(0.9, 1.1)
        cpu = baseline_cpu * random.uniform(0.9, 1.1)
        latency = baseline_latency * random.uniform(0.8, 1.2)
        error_rate = baseline_error_rate * random.uniform(0.5, 2.0)

    # Update gauges
    MEMORY_USAGE.labels(service=service_name).set(memory)
    CPU_USAGE.labels(service=service_name).set(cpu)
    ERROR_RATE.labels(service=service_name).set(error_rate)

    # Simulate some requests
    for _ in range(random.randint(5, 15)):
        status = "500" if random.random() < error_rate else "200"
        REQUEST_COUNT.labels(
            service=service_name,
            method="POST",
            endpoint="/api/v1/payments",
            status=status
        ).inc()

        REQUEST_DURATION.labels(
            service=service_name,
            endpoint="/api/v1/payments"
        ).observe(latency + random.uniform(-0.1, 0.1))

    return Response(generate_latest(), mimetype='text/plain')


@app.route('/trigger-incident')
def trigger_incident():
    """Trigger an incident (simulate high load/memory leak)."""
    global incident_mode
    incident_mode = True
    return {
        "status": "incident_triggered",
        "message": "Service will now show high memory/CPU usage",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.route('/resolve-incident')
def resolve_incident():
    """Resolve the incident (return to normal)."""
    global incident_mode
    incident_mode = False
    return {
        "status": "incident_resolved",
        "message": "Service returned to normal operation",
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == '__main__':
    print("=" * 70)
    print(f"Starting Mock {service_name}")
    print("=" * 70)
    print()
    print("Endpoints:")
    print("  • Home:              http://localhost:5001/")
    print("  • Metrics:           http://localhost:5001/metrics")
    print("  • Health:            http://localhost:5001/health")
    print("  • Trigger Incident:  http://localhost:5001/trigger-incident")
    print("  • Resolve Incident:  http://localhost:5001/resolve-incident")
    print()
    print("Add to Prometheus config:")
    print("  - job_name: 'payment-service'")
    print("    static_configs:")
    print("      - targets: ['localhost:5001']")
    print()

    app.run(host='0.0.0.0', port=5001, debug=True)
