# Mock Services for AIRRA Testing

Simple mock microservices for testing AIRRA without real infrastructure.

## What's Included

- **payment-service**: Mock service with Prometheus metrics
- Simulates normal operation and incidents
- Can trigger incidents on demand

## Quick Start

### Option 1: Run Locally (Python)

```bash
cd mock-services

# Install dependencies
pip install flask prometheus-client

# Run the service
python payment-service.py
```

Access at: http://localhost:5001

### Option 2: Run with Docker

```bash
cd mock-services
docker build -t mock-payment-service .
docker run -p 5001:5001 mock-payment-service
```

## Using the Mock Service

### 1. View Metrics
```bash
curl http://localhost:5001/metrics
```

### 2. Trigger an Incident
```bash
curl http://localhost:5001/trigger-incident
```

This will cause:
- ⬆️ Memory usage to spike (7-9GB)
- ⬆️ CPU usage to spike (70-105%)
- ⬆️ Response time to increase (2.5-4s)
- ⬆️ Error rate to increase (1.5-3%)

### 3. Check Prometheus

Add to your `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'payment-service'
    static_configs:
      - targets: ['localhost:5001']
        labels:
          service: 'payment-service'
```

### 4. Watch AIRRA Detect It

1. Trigger incident: `curl http://localhost:5001/trigger-incident`
2. Wait 60 seconds (for anomaly monitor to detect)
3. Check AIRRA: `curl http://localhost:8000/api/v1/incidents/`
4. Analyze: `POST /api/v1/incidents/{id}/analyze`

### 5. Resolve Incident
```bash
curl http://localhost:5001/resolve-incident
```

## Creating More Mock Services

Copy `payment-service.py` and modify:

```python
service_name = "order-service"  # Change name
# Change port
app.run(host='0.0.0.0', port=5002)
```

## Do You Need This?

**NO!** AIRRA works fine with simulated data.

**Use mock services if**:
- You want realistic Prometheus integration
- You want to test automatic anomaly detection
- You want to demo the full system

**Skip mock services if**:
- Just testing LLM hypothesis generation ✅
- Just testing API endpoints ✅
- Early stage development ✅
