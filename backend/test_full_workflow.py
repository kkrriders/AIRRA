#!/usr/bin/env python3
"""
Complete AIRRA Workflow Test

Demonstrates:
1. Creating an incident
2. Listing incidents
3. Triggering LLM analysis
4. Viewing generated hypotheses
5. Viewing recommended actions
"""
import asyncio
import sys
from datetime import datetime

import httpx


BASE_URL = "http://localhost:8000"


async def main():
    """Test the complete incident workflow."""

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ========================================
        # STEP 1: Create an Incident
        # ========================================
        print("=" * 70)
        print("STEP 1: Creating a Test Incident")
        print("=" * 70)

        incident_data = {
            "title": "High CPU and Memory on payment-service",
            "description": "Payment service showing high resource usage with slow responses",
            "severity": "high",
            "affected_service": "payment-service",
            "affected_components": ["payment-api", "payment-processor"],
            "detected_at": datetime.utcnow().isoformat(),
            "detection_source": "manual_test",
            "metrics_snapshot": {
                "cpu_usage_percent": 89.5,
                "memory_usage_percent": 78.3,
                "response_time_p95_ms": 2500,
                "error_rate": 0.025,
                "request_rate": 1250
            },
            "context": {
                "tier": "tier_1",
                "team": "payments",
                "recent_deployments": "v2.3.1 deployed 2 hours ago",
                "dependencies": ["postgres", "redis", "payment-gateway"]
            }
        }

        response = await client.post(f"{BASE_URL}/api/v1/incidents/", json=incident_data)

        if response.status_code != 201:
            print(f"❌ Failed to create incident: {response.status_code}")
            print(response.text)
            return 1

        incident = response.json()
        incident_id = incident["id"]

        print(f"✅ Created Incident")
        print(f"   ID: {incident_id}")
        print(f"   Title: {incident['title']}")
        print(f"   Service: {incident['affected_service']}")
        print(f"   Severity: {incident['severity']}")
        print(f"   Status: {incident['status']}")
        print()

        # ========================================
        # STEP 2: List All Incidents
        # ========================================
        print("=" * 70)
        print("STEP 2: Listing All Incidents")
        print("=" * 70)

        response = await client.get(f"{BASE_URL}/api/v1/incidents/")

        if response.status_code == 200:
            incidents_list = response.json()
            print(f"✅ Found {incidents_list['total']} incident(s)")
            for inc in incidents_list['items'][:3]:  # Show first 3
                print(f"   • {inc['title']} ({inc['status']})")
        print()

        # ========================================
        # STEP 3: Trigger LLM Analysis
        # ========================================
        print("=" * 70)
        print("STEP 3: Triggering LLM Hypothesis Generation")
        print("=" * 70)
        print("⏳ Analyzing incident with LLM...")
        print("   This will take 10-30 seconds...")
        print()

        response = await client.post(
            f"{BASE_URL}/api/v1/incidents/{incident_id}/analyze"
        )

        if response.status_code != 200:
            print(f"❌ Analysis failed: {response.status_code}")
            print(response.text)
            return 1

        analysis_result = response.json()

        print(f"✅ Analysis Complete!")
        print(f"   Status: {analysis_result['status']}")
        print(f"   Hypotheses Generated: {analysis_result['hypotheses_generated']}")
        print(f"   Action Recommended: {analysis_result['action_recommended']}")
        print(f"   LLM Tokens Used: {analysis_result['tokens_used']}")
        print()

        # ========================================
        # STEP 4: View Incident with Hypotheses
        # ========================================
        print("=" * 70)
        print("STEP 4: Viewing Generated Hypotheses & Actions")
        print("=" * 70)

        response = await client.get(f"{BASE_URL}/api/v1/incidents/{incident_id}")

        if response.status_code != 200:
            print(f"❌ Failed to get incident details: {response.status_code}")
            return 1

        incident_detail = response.json()

        # Display Hypotheses
        hypotheses = incident_detail.get("hypotheses", [])
        print(f"\n🧠 Generated {len(hypotheses)} Hypothesis(es):\n")

        for hyp in hypotheses:
            print(f"{'=' * 70}")
            print(f"Hypothesis #{hyp['rank']}")
            print(f"{'=' * 70}")
            print(f"Confidence:  {hyp['confidence_score']:.1%}")
            print(f"Category:    {hyp['category']}")
            print(f"Description: {hyp['description']}")
            print()
            print(f"Supporting Signals:")
            for signal in hyp['supporting_signals']:
                print(f"  • {signal}")
            print()

            # Show first 300 chars of reasoning
            reasoning = hyp.get('llm_reasoning', 'N/A')
            print(f"LLM Reasoning:")
            print(f"  {reasoning[:300]}...")
            print()

        # Display Actions
        actions = incident_detail.get("actions", [])
        if actions:
            print(f"\n{'=' * 70}")
            print(f"🎯 Recommended Actions ({len(actions)}):")
            print(f"{'=' * 70}\n")

            for action in actions:
                print(f"Action: {action['name']}")
                print(f"  Type:        {action['action_type']}")
                print(f"  Risk Level:  {action['risk_level']} (score: {action['risk_score']:.2f})")
                print(f"  Target:      {action['target_service']}")
                print(f"  Status:      {action['status']}")
                print(f"  Requires Approval: {action['requires_approval']}")
                print(f"  Mode:        {action['execution_mode']}")
                print()

        # ========================================
        # Summary
        # ========================================
        print("=" * 70)
        print("✅ WORKFLOW COMPLETE!")
        print("=" * 70)
        print()
        print("What happened:")
        print("  1. ✅ Created incident")
        print("  2. ✅ Listed all incidents")
        print(f"  3. ✅ LLM analyzed and generated {len(hypotheses)} hypotheses")
        print(f"  4. ✅ Generated {len(actions)} recommended action(s)")
        print()
        print("Next Steps:")
        print("  • View in API docs: http://localhost:8000/docs")
        print("  • View in frontend: http://localhost:3000")
        print(f"  • Direct link: http://localhost:3000/incidents/{incident_id}")
        print()
        print("To approve actions:")
        print(f"  POST /api/v1/approvals/{actions[0]['id']}/approve" if actions else "  (No actions to approve)")
        print()

        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
