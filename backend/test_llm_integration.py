#!/usr/bin/env python3
"""
Test script for LLM Hypothesis Generation.

This script demonstrates the end-to-end flow:
1. Create a test incident
2. Trigger LLM analysis
3. View generated hypotheses

Run from backend directory:
    python test_llm_integration.py
"""
import asyncio
import sys
from datetime import datetime

import httpx


BASE_URL = "http://localhost:8000"


async def main():
    """Test the LLM hypothesis generation flow."""

    async with httpx.AsyncClient() as client:
        # Step 1: Create a test incident
        print("=" * 60)
        print("Step 1: Creating test incident...")
        print("=" * 60)

        incident_data = {
            "title": "High CPU usage on payment-service",
            "description": "Payment service showing elevated CPU usage with increased response times",
            "severity": "high",
            "affected_service": "payment-service",
            "affected_components": ["payment-api", "payment-processor"],
            "detected_at": datetime.utcnow().isoformat(),
            "detection_source": "prometheus",
            "metrics_snapshot": {
                "cpu_usage": 85.5,
                "memory_usage": 72.3,
                "response_time_p95": 2500,
                "error_rate": 0.02
            },
            "context": {
                "tier": "critical",
                "dependencies": ["postgres", "redis", "payment-gateway"],
                "recent_deployments": "v2.3.1 deployed 2 hours ago"
            }
        }

        response = await client.post(f"{BASE_URL}/api/v1/incidents/", json=incident_data)

        if response.status_code != 201:
            print(f"❌ Failed to create incident: {response.status_code}")
            print(response.text)
            return

        incident = response.json()
        incident_id = incident["id"]
        print(f"✅ Created incident: {incident_id}")
        print(f"   Service: {incident['affected_service']}")
        print(f"   Severity: {incident['severity']}")
        print(f"   Status: {incident['status']}")
        print()

        # Step 2: Trigger LLM analysis
        print("=" * 60)
        print("Step 2: Triggering LLM analysis...")
        print("=" * 60)
        print("⏳ Calling LLM to generate hypotheses (this may take 10-30 seconds)...")
        print()

        response = await client.post(
            f"{BASE_URL}/api/v1/incidents/{incident_id}/analyze",
            timeout=60.0  # LLM can take time
        )

        if response.status_code != 200:
            print(f"❌ Analysis failed: {response.status_code}")
            print(response.text)
            return

        analysis_result = response.json()
        print(f"✅ Analysis completed!")
        print(f"   Hypotheses generated: {analysis_result['hypotheses_generated']}")
        print(f"   Action recommended: {analysis_result['action_recommended']}")
        print(f"   LLM tokens used: {analysis_result['tokens_used']}")
        print()

        # Step 3: Retrieve and display hypotheses
        print("=" * 60)
        print("Step 3: Viewing generated hypotheses...")
        print("=" * 60)

        response = await client.get(f"{BASE_URL}/api/v1/incidents/{incident_id}")

        if response.status_code != 200:
            print(f"❌ Failed to retrieve incident: {response.status_code}")
            return

        incident_detail = response.json()
        hypotheses = incident_detail.get("hypotheses", [])

        if not hypotheses:
            print("⚠️  No hypotheses found")
            return

        print(f"\n🧠 Generated {len(hypotheses)} Hypothesis(es):\n")

        for i, hyp in enumerate(hypotheses, 1):
            print(f"Hypothesis #{i} (Rank: {hyp['rank']})")
            print(f"  Confidence: {hyp['confidence_score']:.2%}")
            print(f"  Category: {hyp['category']}")
            print(f"  Description: {hyp['description']}")
            print(f"  Reasoning: {hyp.get('llm_reasoning', 'N/A')[:200]}...")
            print(f"  Supporting Signals: {', '.join(hyp['supporting_signals'])}")
            print()

        # Display recommended actions
        actions = incident_detail.get("actions", [])
        if actions:
            print("🎯 Recommended Actions:\n")
            for action in actions:
                print(f"  • {action['name']}")
                print(f"    Type: {action['action_type']}")
                print(f"    Risk: {action['risk_level']} (score: {action['risk_score']:.2f})")
                print(f"    Target: {action['target_service']}")
                print(f"    Status: {action['status']}")
                print(f"    Requires Approval: {action['requires_approval']}")
                print()

        print("=" * 60)
        print("✅ Test completed successfully!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. View in API docs: http://localhost:8000/docs")
        print("  2. View in frontend: http://localhost:3000")
        print(f"  3. Direct link: http://localhost:3000/incidents/{incident_id}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
