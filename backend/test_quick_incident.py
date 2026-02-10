#!/usr/bin/env python3
"""
Test Quick Incident Creation

Demonstrates the one-click workflow:
1. Specify service name
2. Auto-detect/simulate anomalies
3. Auto-generate hypotheses
4. Get results immediately

Perfect for UI integration!
"""
import asyncio
import sys

import httpx


BASE_URL = "http://localhost:8000"


async def test_quick_incident():
    """Test the quick incident creation endpoint."""

    print("=" * 70)
    print("Testing Quick Incident Creation (One-Click Workflow)")
    print("=" * 70)
    print()

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ========================================
        # Example 1: Minimal Request
        # ========================================
        print("Example 1: Minimal Request (Just Service Name)")
        print("-" * 70)
        print()

        request = {
            "service_name": "payment-service",
            # That's it! Everything else is auto-generated
        }

        print("Sending request:")
        print(f"  Service: {request['service_name']}")
        print()
        print("⏳ Creating incident and analyzing with LLM...")
        print("   (This takes 10-30 seconds)")
        print()

        response = await client.post(
            f"{BASE_URL}/api/v1/quick-incident",
            json=request
        )

        if response.status_code != 201:
            print(f"❌ Failed: {response.status_code}")
            print(response.text)
            return 1

        incident = response.json()

        print("✅ Complete!")
        print()
        print(f"Incident Created:")
        print(f"  ID: {incident['id']}")
        print(f"  Title: {incident['title']}")
        print(f"  Status: {incident['status']}")
        print(f"  Severity: {incident['severity']}")
        print()

        # Display hypotheses
        hypotheses = incident.get("hypotheses", [])
        print(f"🧠 Generated {len(hypotheses)} Hypotheses:")
        print()

        for hyp in hypotheses:
            print(f"  Hypothesis #{hyp['rank']}:")
            print(f"    Confidence: {hyp['confidence_score']:.1%}")
            print(f"    Category: {hyp['category']}")
            print(f"    Description: {hyp['description'][:80]}...")
            print()

        # Display actions
        actions = incident.get("actions", [])
        if actions:
            print(f"🎯 Recommended Actions:")
            print()
            for action in actions:
                print(f"  • {action['name']}")
                print(f"    Risk: {action['risk_level']} (score: {action['risk_score']:.2f})")
                print(f"    Status: {action['status']}")
                print()

        # ========================================
        # Example 2: With Custom Metrics
        # ========================================
        print()
        print("=" * 70)
        print("Example 2: With Custom Metrics")
        print("-" * 70)
        print()

        request = {
            "service_name": "order-service",
            "severity": "high",
            "metrics_snapshot": {
                "cpu_usage_percent": 92.5,
                "memory_usage_mb": 7800,
                "response_time_ms": 3500,
                "error_rate_percent": 2.8,
                "active_connections": 1450
            },
            "context": {
                "recent_deployments": "v3.1.0 deployed 30 minutes ago",
                "dependencies": ["postgres", "redis", "payment-gateway"]
            }
        }

        print("Sending request with custom metrics:")
        print(f"  Service: {request['service_name']}")
        print(f"  Severity: {request['severity']}")
        print(f"  Metrics: {len(request['metrics_snapshot'])} metrics provided")
        print()
        print("⏳ Analyzing...")
        print()

        response = await client.post(
            f"{BASE_URL}/api/v1/quick-incident",
            json=request
        )

        if response.status_code != 201:
            print(f"❌ Failed: {response.status_code}")
            print(response.text)
            return 1

        incident = response.json()

        print("✅ Complete!")
        print()
        print(f"Incident Created:")
        print(f"  ID: {incident['id']}")
        print(f"  Service: {incident['affected_service']}")
        print(f"  Hypotheses: {len(incident.get('hypotheses', []))}")
        print(f"  Actions: {len(incident.get('actions', []))}")
        print()

        # ========================================
        # Summary
        # ========================================
        print("=" * 70)
        print("✅ Quick Incident Workflow Complete!")
        print("=" * 70)
        print()
        print("What happened:")
        print("  1. ✅ Sent service name + optional metrics")
        print("  2. ✅ System auto-detected/simulated anomalies")
        print("  3. ✅ LLM generated hypotheses automatically")
        print("  4. ✅ System recommended actions")
        print("  5. ✅ Got complete incident with all data")
        print()
        print("All in ONE API call! Perfect for UI integration.")
        print()
        print("API Endpoint:")
        print("  POST /api/v1/quick-incident")
        print()
        print("Minimal request:")
        print('  {"service_name": "payment-service"}')
        print()
        print("Try it in API docs:")
        print("  http://localhost:8000/docs#/Quick%20Actions/create_and_analyze_incident_api_v1_quick_incident_post")
        print()

        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(test_quick_incident())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
