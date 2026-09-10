from tests.evals.security_benchmark import run


def test_adversarial_controls_block_all_curated_cases():
    report = run()
    assert report.cases == 100
    assert report.block_rate == 1.0
