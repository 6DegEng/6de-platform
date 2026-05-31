"""Unit tests for modules.calculator.single_ply_attachment.

Golden values from `Single Ply Attachment Calc.xlsx` (project 260304 - Buena Vista,
sheet `Single Ply Attachment`). Each test cites the source cell.
"""
from __future__ import annotations

import math

import pytest

from modules.calculator.single_ply_attachment import (
    CalcInputs,
    WindInputs,
    ZoneSpacing,
    calculate,
    compute_allowable_fastener_value,
    compute_design_pressure,
    compute_kh,
    compute_qh,
    compute_required_x_max,
    compute_tributary_area,
    render_text_memo,
)


TOL = 1e-9


# ---------------------------------------------------------------------------
# Cell-level parity (single-formula functions)
# ---------------------------------------------------------------------------
class TestExposureKh:
    """ASCE 7-22 Table 26.10-1 / Eq. 26.10-1."""

    def test_kh_exposure_B_h30(self):
        # D19 with D12='B', D13=30 → 0.7005911248354256
        assert compute_kh("B", 30.0) == pytest.approx(0.7005911248354256, abs=TOL)

    def test_kh_exposure_C_h30(self):
        # Hand-checked against ASCE 7-22 T26.10-1: 2.01*(30/900)^(2/9.5)
        expected = 2.01 * (30.0 / 900.0) ** (2.0 / 9.5)
        assert compute_kh("C", 30.0) == pytest.approx(expected, abs=TOL)

    def test_kh_exposure_D_h60(self):
        expected = 2.01 * (60.0 / 700.0) ** (2.0 / 11.5)
        assert compute_kh("D", 60.0) == pytest.approx(expected, abs=TOL)

    def test_kh_below_15ft_uses_15(self):
        # Per ASCE 7-22: z = max(h, 15 ft)
        assert compute_kh("B", 10.0) == compute_kh("B", 15.0)
        assert compute_kh("C", 5.0) == compute_kh("C", 15.0)

    def test_kh_invalid_exposure(self):
        with pytest.raises(ValueError):
            compute_kh("A", 30.0)  # type: ignore[arg-type]


class TestQh:
    def test_qh_workbook_defaults(self):
        # H19 with D17=175, D18=0.85, H17=1, H18=1, D19=0.7005911248
        # → 46.687392559032766
        kh = compute_kh("B", 30.0)
        wind = WindInputs()
        assert compute_qh(kh, wind) == pytest.approx(46.687392559032766, abs=TOL)

    def test_qh_scales_with_v_squared(self):
        kh = compute_kh("B", 30.0)
        wind_low = WindInputs(basic_wind_speed_mph=100.0)
        wind_high = WindInputs(basic_wind_speed_mph=200.0)
        qh_low = compute_qh(kh, wind_low)
        qh_high = compute_qh(kh, wind_high)
        # Doubling V should quadruple qh
        assert qh_high / qh_low == pytest.approx(4.0, rel=1e-9)


class TestDesignPressure:
    def test_zone_1_prime_default(self):
        # C39 = qh * (GCp_1' - GCpi) = 46.6874 * (-0.9 - 0.18) → -50.422...
        qh = 46.687392559032766
        assert compute_design_pressure(qh, gcp=-0.9, gcpi=0.18) == pytest.approx(
            -50.422383963755394, abs=TOL
        )

    def test_zone_3_default(self):
        qh = 46.687392559032766
        assert compute_design_pressure(qh, gcp=-3.2, gcpi=0.18) == pytest.approx(
            -157.80338684953077, abs=TOL
        )


class TestTributaryArea:
    def test_pa_defaults(self):
        # F34 = |6 * 45| / 144 = 1.875
        assert compute_tributary_area(6.0, 45.0) == pytest.approx(1.875, abs=TOL)

    def test_negative_inputs_use_abs(self):
        assert compute_tributary_area(-6.0, -45.0) == pytest.approx(1.875, abs=TOL)


class TestAllowableFastenerValue:
    def test_defaults(self):
        # F35 = |MDP| * X_PA = 52.5 * 1.875 = 98.4375
        assert compute_allowable_fastener_value(-52.5, 1.875) == pytest.approx(
            98.4375, abs=TOL
        )


class TestRequiredXMax:
    def test_zone_1_prime(self):
        # G39 = fv / |P| = 98.4375 / 50.4224 → 1.9522579509679436
        assert compute_required_x_max(98.4375, -50.422383963755394) == pytest.approx(
            1.9522579509679436, abs=TOL
        )

    def test_zero_pressure_returns_inf(self):
        assert compute_required_x_max(98.4375, 0.0) == math.inf


# ---------------------------------------------------------------------------
# Full-calc parity (end-to-end against workbook example)
# ---------------------------------------------------------------------------
class TestFullCalcParity:
    """Run with default CalcInputs (mirrors the workbook example) and
    check every output cell against the xlsx values."""

    @pytest.fixture
    def results(self):
        return calculate(CalcInputs())

    def test_kh(self, results):
        assert results.kh == pytest.approx(0.7005911248354256, abs=TOL)

    def test_qh(self, results):
        assert results.qh_psf == pytest.approx(46.687392559032766, abs=TOL)

    def test_tributary_x_pa(self, results):
        assert results.tributary_x_pa_sf == pytest.approx(1.875, abs=TOL)

    def test_allowable_fv(self, results):
        assert results.allowable_fastener_value_lbf == pytest.approx(98.4375, abs=TOL)

    @pytest.mark.parametrize(
        "idx,zone,p_expected,xmax_expected",
        [
            (0, "Zone 1'", -50.422383963755394, 1.9522579509679436),
            (1, "Zone 1",  -87.7722980109816,   1.1215098867262656),
            (2, "Zone 2",  -115.78473354640126, 0.8501768496150723),
            (3, "Zone 3",  -157.80338684953077, 0.6237983985341358),
        ],
    )
    def test_zone_outputs(self, results, idx, zone, p_expected, xmax_expected):
        z = results.zones[idx]
        assert z.zone_name == zone
        assert z.design_pressure_psf == pytest.approx(p_expected, abs=TOL)
        assert z.required_x_max_sf == pytest.approx(xmax_expected, abs=TOL)
        assert z.status == "OK"

    def test_validation_extrapolation(self, results):
        # F45 → 3.005778797133919 (just over the 300% gate, xlsx flags "No")
        assert results.validation.extrapolation_ratio == pytest.approx(
            3.005778797133919, abs=TOL
        )
        assert results.validation.extrapolation_ok is False

    def test_validation_min_spacing(self, results):
        # Default FS = 5 in.o.c. across all zones; xlsx flags below 6
        assert results.validation.min_fastener_spacing_in == 5.0
        assert results.validation.min_spacing_ok is False

    def test_validation_max_dc(self, results):
        # F47 → 0.9782120345702104, overall OK
        assert results.validation.max_demand_capacity == pytest.approx(
            0.9782120345702104, abs=TOL
        )
        assert results.validation.overall_ok is True


# ---------------------------------------------------------------------------
# Sensitivity / edge cases
# ---------------------------------------------------------------------------
class TestSensitivity:
    def test_lower_wind_speed_reduces_all_zone_pressures(self):
        baseline = calculate(CalcInputs())
        low_wind = calculate(CalcInputs(wind=WindInputs(basic_wind_speed_mph=100.0)))
        for b, lw in zip(baseline.zones, low_wind.zones):
            assert abs(lw.design_pressure_psf) < abs(b.design_pressure_psf)

    def test_exposure_c_higher_kh_than_b_at_low_heights(self):
        """ASCE 7-22: at h=30 ft, Kh(C) > Kh(B) (rougher exposure → higher gust)."""
        assert compute_kh("C", 30.0) > compute_kh("B", 30.0)

    def test_passing_spacing_makes_all_zones_ok(self):
        # Tighten all spacings to 4x4 → very small tributary area, must pass
        inputs = CalcInputs(
            zone_spacing={
                "Zone 1'": ZoneSpacing(4.0, 12.0),
                "Zone 1": ZoneSpacing(4.0, 12.0),
                "Zone 2": ZoneSpacing(4.0, 12.0),
                "Zone 3": ZoneSpacing(4.0, 12.0),
            }
        )
        r = calculate(inputs)
        assert all(z.status == "OK" for z in r.zones)
        assert r.validation.overall_ok is True

    def test_failing_spacing_flags_status(self):
        # Wildly loose: 12x60 in all zones → must fail at least Zone 3
        inputs = CalcInputs(
            zone_spacing={
                "Zone 1'": ZoneSpacing(12.0, 60.0),
                "Zone 1": ZoneSpacing(12.0, 60.0),
                "Zone 2": ZoneSpacing(12.0, 60.0),
                "Zone 3": ZoneSpacing(12.0, 60.0),
            }
        )
        r = calculate(inputs)
        assert any("FAIL" in z.status for z in r.zones)
        assert r.validation.overall_ok is False

    def test_missing_zone_spacing_raises(self):
        bad = CalcInputs(zone_spacing={"Zone 1'": ZoneSpacing(5.0, 27.5)})
        with pytest.raises(ValueError):
            calculate(bad)


# ---------------------------------------------------------------------------
# Memo rendering
# ---------------------------------------------------------------------------
class TestMemoRender:
    def test_text_memo_contains_key_sections(self):
        inputs = CalcInputs()
        results = calculate(inputs)
        memo = render_text_memo(inputs, results)
        for section in [
            "PROJECT INFORMATION",
            "BUILDING INFORMATION",
            "WIND PRESSURE",
            "PRODUCT APPROVAL",
            "CALCULATED FASTENER SPACING - RESULTS",
            "VALIDATION CHECKS",
        ]:
            assert section in memo

    def test_text_memo_includes_computed_values(self):
        results = calculate(CalcInputs())
        memo = render_text_memo(CalcInputs(), results)
        assert "46.69" in memo  # qh
        assert "98.44" in memo  # fv (rounded display)
