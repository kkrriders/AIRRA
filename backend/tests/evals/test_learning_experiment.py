from tests.evals.learning_experiment import run


def test_verified_feedback_does_not_reduce_held_out_accuracy():
    report = run()
    assert report.train_incidents == report.held_out_incidents == 120
    assert report.learned_top1_accuracy >= report.cold_top1_accuracy
    assert report.learned_top3_accuracy >= report.cold_top3_accuracy
