from app.services.volume_stats import (
    estimate_full_day_volume,
    volume_label,
    volume_ratio,
)


def test_estimate_extrapolates_by_elapsed_fraction():
    # 半天走了一半量 → 预估全天翻倍
    assert estimate_full_day_volume(500_000, 0.5) == 1_000_000


def test_estimate_after_close_returns_actual():
    assert estimate_full_day_volume(3_000_000, 1.0) == 3_000_000


def test_estimate_none_when_premarket_or_no_data():
    assert estimate_full_day_volume(100, None) is None
    assert estimate_full_day_volume(None, 0.5) is None
    assert estimate_full_day_volume(0, 0.5) is None
    assert estimate_full_day_volume(100, 0) is None


def test_volume_ratio_basic():
    assert volume_ratio(2_000_000, 1_000_000) == 2.0


def test_volume_ratio_none_on_missing_or_zero():
    assert volume_ratio(None, 1_000_000) is None
    assert volume_ratio(1_000_000, None) is None
    assert volume_ratio(1_000_000, 0) is None


def test_volume_label_thresholds():
    assert volume_label(1.5) == "放量"
    assert volume_label(3.0) == "放量"
    assert volume_label(0.7) == "缩量"
    assert volume_label(0.3) == "缩量"
    assert volume_label(1.0) == "正常"
    assert volume_label(None) is None
