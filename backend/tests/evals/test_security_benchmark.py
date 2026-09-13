from tests.evals.security_benchmark import run


def test_adversarial_controls_block_all_curated_cases():
    report = run()
    # 50 injection + 30 secret + 20 unsafe-action + 50 RAG-poisoning +
    # 7 approval-bypass (every ActionStatus except APPROVED).
    assert report.cases == 157
    assert report.block_rate == 1.0
