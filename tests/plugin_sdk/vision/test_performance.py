from examples.vision_benchmark import run


def test_measurement_schema(tmp_path):
    report = run(tmp_path, samples=1)
    assert len(report["cases"]) == 6
    for case in report["cases"]:
        assert set(case["raw"]) == {
            "decode_ms",
            "preprocess_ms",
            "match_ms",
            "postprocess_ms",
            "total_ms",
        }
        assert all(len(values) == 1 and values[0] >= 0 for values in case["raw"].values())
    assert len(report["memory_run"]["samples"]) == 11
