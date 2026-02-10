#!/usr/bin/env python3
"""
Direct test of LLM hypothesis generation (no Prometheus required).

This script tests the hypothesis generator directly with synthetic anomaly data.

Run from backend directory:
    python test_hypothesis_direct.py
"""
import asyncio
import sys
from datetime import datetime

from app.core.perception.anomaly_detector import AnomalyDetection
from app.core.reasoning.hypothesis_generator import HypothesisGenerator
from app.services.llm_client import get_llm_client


async def main():
    """Test hypothesis generation with mock anomaly data."""

    print("=" * 60)
    print("Testing LLM Hypothesis Generation")
    print("=" * 60)
    print()

    # Create synthetic anomalies
    anomalies = [
        AnomalyDetection(
            metric_name="http_requests_total",
            current_value=1250.5,
            expected_value=500.0,
            deviation_sigma=4.2,
            confidence=0.92,
            timestamp=datetime.utcnow(),
            context={
                "labels": {
                    "service": "payment-service",
                    "status": "500",
                    "method": "POST"
                }
            }
        ),
        AnomalyDetection(
            metric_name="http_request_duration_seconds",
            current_value=3.5,
            expected_value=0.5,
            deviation_sigma=5.8,
            confidence=0.95,
            timestamp=datetime.utcnow(),
            context={
                "labels": {
                    "service": "payment-service",
                    "endpoint": "/api/v1/payments",
                    "quantile": "0.95"
                }
            }
        ),
        AnomalyDetection(
            metric_name="process_resident_memory_bytes",
            current_value=8589934592,  # 8GB
            expected_value=2147483648,  # 2GB
            deviation_sigma=3.5,
            confidence=0.88,
            timestamp=datetime.utcnow(),
            context={
                "labels": {
                    "service": "payment-service",
                    "pod": "payment-service-7d4f8b"
                }
            }
        )
    ]

    print(f"📊 Created {len(anomalies)} synthetic anomalies:")
    for anomaly in anomalies:
        print(f"  • {anomaly.metric_name}: {anomaly.current_value:.2f} "
              f"(expected: {anomaly.expected_value:.2f}, σ: {anomaly.deviation_sigma:.1f})")
    print()

    # Initialize LLM client
    print("🔧 Initializing LLM client...")
    try:
        llm_client = get_llm_client()
        print(f"✅ LLM client initialized successfully")
        print()
    except Exception as e:
        print(f"❌ Failed to initialize LLM client: {str(e)}")
        print("\nMake sure your .env file has the correct API keys:")
        print("  AIRRA_LLM_PROVIDER=openrouter")
        print("  AIRRA_OPENROUTER_API_KEY=your-key-here")
        print("  AIRRA_LLM_MODEL=google/gemini-2.0-flash-thinking-exp:free")
        return 1

    # Generate hypotheses
    print("🧠 Generating hypotheses using LLM...")
    print("⏳ This may take 10-30 seconds...")
    print()

    try:
        generator = HypothesisGenerator(llm_client)

        service_context = {
            "tier": "critical",
            "dependencies": ["postgres", "redis", "payment-gateway"],
            "recent_deployments": "v2.3.1 deployed 2 hours ago"
        }

        hypotheses_response, llm_response = await generator.generate(
            anomalies=anomalies,
            service_name="payment-service",
            service_context=service_context
        )

        print("✅ Hypotheses generated successfully!")
        print()
        print("=" * 60)
        print(f"LLM Usage:")
        print(f"  Model: {llm_response.model}")
        print(f"  Prompt tokens: {llm_response.prompt_tokens}")
        print(f"  Completion tokens: {llm_response.completion_tokens}")
        print(f"  Total tokens: {llm_response.total_tokens}")
        print("=" * 60)
        print()

        print(f"📝 Overall Assessment:")
        print(f"  {hypotheses_response.overall_assessment}")
        print()

        print(f"🎯 Generated {len(hypotheses_response.hypotheses)} Hypotheses:")
        print()

        for i, hyp in enumerate(hypotheses_response.hypotheses, 1):
            print(f"Hypothesis #{i}")
            print(f"  📊 Confidence: {hyp.confidence_score:.2%}")
            print(f"  🏷️  Category: {hyp.category}")
            print(f"  📄 Description: {hyp.description}")
            print()
            print(f"  🔍 Evidence:")
            for evidence in hyp.evidence:
                print(f"    • {evidence.signal_name} ({evidence.signal_type})")
                print(f"      Observation: {evidence.observation}")
                print(f"      Relevance: {evidence.relevance:.2%}")
            print()
            print(f"  💭 Reasoning:")
            # Wrap reasoning text
            reasoning_lines = hyp.reasoning.split('\n')
            for line in reasoning_lines:
                if line.strip():
                    print(f"    {line.strip()}")
            print()
            print("-" * 60)
            print()

        print("=" * 60)
        print("✅ Test completed successfully!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"❌ Hypothesis generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
