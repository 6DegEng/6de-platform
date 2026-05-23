"""Single-ply mechanically-attached roof membrane fastener calc.

Implements the ASCE 7-22 Chapter 26 + 30 wind pressure procedure and the
RAS 137 rational-analysis fastener check for low-slope (slope ≤ 7°) single-ply
membrane roofs at mean roof heights ≤ 60 ft.

Ported from `Single Ply Attachment Calc.xlsx` (project 260304 - Buena Vista).
Cell references in the docstrings refer to the source workbook for traceability.

References
----------
- ASCE 7-22 Ch. 26 (general wind provisions) and Ch. 30 (C&C wind pressures)
- FBC 2023 (8th Edition) - RAS 137 (rational analysis for mechanical attachment)
- ASCE 7-22 Table 26.10-1 (velocity pressure exposure coefficient Kh)
- ASCE 7-22 Fig. 30.3-2A (GCp values for low-slope membrane roofs)
- ASCE 7-22 Table 26.13-1 (internal pressure coefficient GCpi)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Exposure-category constants (ASCE 7-22 Table 26.10-1, Eq. 26.10-1)
# ---------------------------------------------------------------------------
# zg = nominal height of the atmospheric boundary layer (ft)
# alpha = 3-second gust speed power-law exponent
_EXPOSURE_PARAMS: dict[str, tuple[float, float]] = {
    "B": (1200.0, 7.0),
    "C": (900.0, 9.5),
    "D": (700.0, 11.5),
}

ExposureCategory = Literal["B", "C", "D"]


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ProjectInfo:
    """Project header fields (free-form, no calc impact)."""

    permit_number: str = ""
    process_number: str = ""
    roofing_contractor: str = ""
    date_prepared: str = ""
    job_address: str = ""


@dataclass
class BuildingInfo:
    """Geometry + site exposure inputs."""

    exposure_category: ExposureCategory = "B"  # D12
    risk_category: int = 2  # H12
    mean_roof_height_ft: float = 30.0  # D13 (h)
    parapet_height_ft: float = 0.0  # I13
    deck_type: str = "Min. 5/8\" plywood"  # D14


@dataclass
class WindInputs:
    """ASCE 7-22 Ch. 30 wind-pressure inputs (C&C, low-slope roof)."""

    basic_wind_speed_mph: float = 175.0  # D17 (V) - from ASCE 7 Hazard Tool
    directionality_factor_kd: float = 0.85  # D18 - Table 26.6-1 (C&C)
    topographic_factor_kzt: float = 1.0  # H17
    ground_elevation_factor_ke: float = 1.0  # H18
    internal_pressure_coef_gcpi: float = 0.18  # D20 - (+)enclosed bldg, T26.13-1
    # External pressure coefficients (Fig 30.3-2A) for the four zones used
    # on low-slope membrane roofs (h <= 60 ft, slope <= 7°). All negative.
    gcp_zone_1_prime: float = -0.9  # D22
    gcp_zone_1: float = -1.7  # E22
    gcp_zone_2: float = -2.3  # F22
    gcp_zone_3: float = -3.2  # G22


@dataclass
class ProductApproval:
    """Manufacturer / system identification + per-approval limits."""

    manufacturer: str = "GAF"  # D25
    system_number: str = "W-66"  # D26
    product_approval_no: str = "FL5293-R57"  # H25
    system_type: str = "C-2"  # H26
    product_description: str = "EverGuard TPO 60 10x100"  # D27
    full_sheet_width_in: float = 120.0  # D28
    fastener_description: str = "Drill-Tec #14 Double Barbed XHD 2-3/8"  # D29
    pa_fastener_spacing_in: float = 6.0  # D30 - FS in o.c.
    pa_row_spacing_in: float = 45.0  # H30 - RS in o.c.
    pa_max_design_pressure_psf: float = -52.5  # D31 - MDP (negative uplift)
    general_limitation: int = 7  # H31

    @property
    def half_sheet_width_in(self) -> float:
        """H28 = D28/2."""
        return self.full_sheet_width_in / 2.0


@dataclass
class ZoneSpacing:
    """Engineer-selected fastener + row spacing per roof zone."""

    fastener_spacing_in: float  # FS (in o.c.)
    row_spacing_in: float  # RS (in o.c.)


@dataclass
class ZoneResult:
    """Per-zone calc result."""

    zone_name: str
    design_pressure_psf: float  # P = qh * (GCp - GCpi)
    tributary_x_sf: float  # X = FS * RS / 144
    required_x_max_sf: float  # X_max = fv / |P|
    fastener_spacing_in: float  # input echo
    row_spacing_in: float  # input echo
    status: str  # "OK" | "FAIL - tighten spacing"

    @property
    def passes(self) -> bool:
        return self.tributary_x_sf <= self.required_x_max_sf

    @property
    def utilization(self) -> float:
        """Demand / capacity ratio (X_provided / X_required)."""
        if self.required_x_max_sf == 0:
            return float("inf")
        return self.tributary_x_sf / self.required_x_max_sf


@dataclass
class ValidationChecks:
    extrapolation_ratio: float  # max(|P_z|) / |MDP|
    extrapolation_ok: bool  # <= 3.0 (300%)
    min_fastener_spacing_in: float
    min_spacing_ok: bool  # FS >= 6 in.o.c.
    max_demand_capacity: float  # max utilization across zones
    overall_ok: bool  # max DC <= 1.0


@dataclass
class CalcResults:
    kh: float  # D19 - velocity pressure exposure coefficient
    qh_psf: float  # H19 - velocity pressure
    tributary_x_pa_sf: float  # F34 - X from PA spacing
    allowable_fastener_value_lbf: float  # F35 - fv
    zones: list[ZoneResult] = field(default_factory=list)
    validation: ValidationChecks | None = None


@dataclass
class CalcInputs:
    """Full input bundle for a calc run."""

    project: ProjectInfo = field(default_factory=ProjectInfo)
    building: BuildingInfo = field(default_factory=BuildingInfo)
    wind: WindInputs = field(default_factory=WindInputs)
    product: ProductApproval = field(default_factory=ProductApproval)
    # Engineer-selected spacing per zone. Defaults mirror the workbook's
    # representative example for verification.
    zone_spacing: dict[str, ZoneSpacing] = field(
        default_factory=lambda: {
            "Zone 1'": ZoneSpacing(fastener_spacing_in=5.0, row_spacing_in=55.0),
            "Zone 1": ZoneSpacing(fastener_spacing_in=5.0, row_spacing_in=27.5),
            "Zone 2": ZoneSpacing(fastener_spacing_in=5.0, row_spacing_in=20.0),
            "Zone 3": ZoneSpacing(fastener_spacing_in=5.0, row_spacing_in=15.0),
        }
    )


# ---------------------------------------------------------------------------
# Core calc functions (pure)
# ---------------------------------------------------------------------------
def compute_kh(exposure: ExposureCategory, mean_roof_height_ft: float) -> float:
    """ASCE 7-22 Eq. 26.10-1 for z <= zg.

    Source cell: D19
        =2.01 * (MAX(D13, 15) / IF(D12="B", 1200, IF(D12="C", 900, 700)))
              ^ (2 / IF(D12="B", 7, IF(D12="C", 9.5, 11.5)))
    """
    if exposure not in _EXPOSURE_PARAMS:
        raise ValueError(f"exposure must be 'B', 'C', or 'D' (got {exposure!r})")
    zg, alpha = _EXPOSURE_PARAMS[exposure]
    z = max(mean_roof_height_ft, 15.0)
    return 2.01 * (z / zg) ** (2.0 / alpha)


def compute_qh(kh: float, wind: WindInputs) -> float:
    """ASCE 7-22 Eq. 26.10-1 velocity pressure.

    Source cell: H19
        =0.00256 * D19 * H17 * D18 * H18 * D17^2
        =0.00256 * Kh * Kzt * Kd * Ke * V^2
    """
    return (
        0.00256
        * kh
        * wind.topographic_factor_kzt
        * wind.directionality_factor_kd
        * wind.ground_elevation_factor_ke
        * (wind.basic_wind_speed_mph**2)
    )


def compute_design_pressure(qh: float, gcp: float, gcpi: float) -> float:
    """ASCE 7-22 design pressure for C&C: P = qh * (GCp - GCpi).

    Source cells: C39..C42
        =$H$19 * (<GCp_zone> - $D$20)
    Returns a signed psf value (negative = uplift).
    """
    return qh * (gcp - gcpi)


def compute_tributary_area(spacing_in: float, row_spacing_in: float) -> float:
    """Tributary area per fastener (sq ft).

    Source cells: F34, F39..F42
        =ABS(FS) * ABS(RS) / 144
    """
    return abs(spacing_in) * abs(row_spacing_in) / 144.0


def compute_allowable_fastener_value(
    pa_max_design_pressure_psf: float, tributary_x_pa_sf: float
) -> float:
    """Allowable fastener value (lbf) from product-approval test.

    Source cell: F35
        =ABS(D31) * F34
        =|MDP| * X_PA
    """
    return abs(pa_max_design_pressure_psf) * tributary_x_pa_sf


def compute_required_x_max(
    allowable_fastener_value_lbf: float, design_pressure_psf: float
) -> float:
    """Maximum allowed tributary area per fastener for a given zone pressure.

    Source cells: G39..G42
        =$F$35 / ABS(<C_zone>)
        = fv / |P|
    """
    if design_pressure_psf == 0:
        return float("inf")
    return allowable_fastener_value_lbf / abs(design_pressure_psf)


def _zone_status(tributary_x_sf: float, required_x_max_sf: float) -> str:
    """Source cells: H39..H42
    =IF(F<=G, "OK", "FAIL - tighten spacing")
    """
    return "OK" if tributary_x_sf <= required_x_max_sf else "FAIL - tighten spacing"


def calculate(inputs: CalcInputs) -> CalcResults:
    """Run the full calc end-to-end against a CalcInputs bundle."""
    kh = compute_kh(inputs.building.exposure_category, inputs.building.mean_roof_height_ft)
    qh = compute_qh(kh, inputs.wind)

    # PA-derived fastener capacity
    x_pa = compute_tributary_area(
        inputs.product.pa_fastener_spacing_in, inputs.product.pa_row_spacing_in
    )
    fv = compute_allowable_fastener_value(
        inputs.product.pa_max_design_pressure_psf, x_pa
    )

    # Per-zone results
    zone_gcps = {
        "Zone 1'": inputs.wind.gcp_zone_1_prime,
        "Zone 1": inputs.wind.gcp_zone_1,
        "Zone 2": inputs.wind.gcp_zone_2,
        "Zone 3": inputs.wind.gcp_zone_3,
    }
    zone_results: list[ZoneResult] = []
    for zone_name, gcp in zone_gcps.items():
        p = compute_design_pressure(qh, gcp, inputs.wind.internal_pressure_coef_gcpi)
        sp = inputs.zone_spacing.get(zone_name)
        if sp is None:
            raise ValueError(f"Missing zone_spacing for {zone_name!r}")
        x_zone = compute_tributary_area(sp.fastener_spacing_in, sp.row_spacing_in)
        x_max = compute_required_x_max(fv, p)
        zone_results.append(
            ZoneResult(
                zone_name=zone_name,
                design_pressure_psf=p,
                tributary_x_sf=x_zone,
                required_x_max_sf=x_max,
                fastener_spacing_in=sp.fastener_spacing_in,
                row_spacing_in=sp.row_spacing_in,
                status=_zone_status(x_zone, x_max),
            )
        )

    # Validation gates
    max_abs_p = max(abs(z.design_pressure_psf) for z in zone_results)
    extrap_ratio = max_abs_p / abs(inputs.product.pa_max_design_pressure_psf)
    min_fs = min(sp.fastener_spacing_in for sp in inputs.zone_spacing.values())
    max_dc = max(z.utilization for z in zone_results)
    validation = ValidationChecks(
        extrapolation_ratio=extrap_ratio,
        extrapolation_ok=extrap_ratio <= 3.0,
        min_fastener_spacing_in=min_fs,
        min_spacing_ok=min_fs >= 6.0,
        max_demand_capacity=max_dc,
        overall_ok=max_dc <= 1.0,
    )

    return CalcResults(
        kh=kh,
        qh_psf=qh,
        tributary_x_pa_sf=x_pa,
        allowable_fastener_value_lbf=fv,
        zones=zone_results,
        validation=validation,
    )


# ---------------------------------------------------------------------------
# Convenience: render a plain-text calc memo (no Streamlit dependency)
# ---------------------------------------------------------------------------
def render_text_memo(inputs: CalcInputs, results: CalcResults) -> str:
    """Return a plain-text calc memo (used by the PDF/markdown export)."""
    lines: list[str] = []
    lines.append("MECHANICAL ATTACHMENT OF SINGLE PLY MEMBRANE ROOF SYSTEM")
    lines.append("Per FBC 2023 8th Edition - RAS 137, ASCE 7-22 Ch. 26 & 30")
    lines.append("")
    lines.append("PROJECT INFORMATION")
    lines.append(f"  Permit Number    : {inputs.project.permit_number}")
    lines.append(f"  Process Number   : {inputs.project.process_number}")
    lines.append(f"  Roofing Contractor: {inputs.project.roofing_contractor}")
    lines.append(f"  Date Prepared    : {inputs.project.date_prepared}")
    lines.append(f"  Job Address      : {inputs.project.job_address}")
    lines.append("")
    lines.append("BUILDING INFORMATION")
    lines.append(f"  Exposure Category : {inputs.building.exposure_category}")
    lines.append(f"  Risk Category     : {inputs.building.risk_category}")
    lines.append(f"  Mean Roof Height  : {inputs.building.mean_roof_height_ft:.1f} ft")
    lines.append(f"  Parapet Height    : {inputs.building.parapet_height_ft:.1f} ft")
    lines.append(f"  Deck Type         : {inputs.building.deck_type}")
    lines.append("")
    lines.append("WIND PRESSURE - ASCE 7-22 Ch 30 (C&C, low-slope)")
    lines.append(f"  Basic wind speed V     : {inputs.wind.basic_wind_speed_mph:.1f} mph")
    lines.append(f"  Kd                     : {inputs.wind.directionality_factor_kd:.2f}")
    lines.append(f"  Kzt                    : {inputs.wind.topographic_factor_kzt:.2f}")
    lines.append(f"  Ke                     : {inputs.wind.ground_elevation_factor_ke:.2f}")
    lines.append(f"  GCpi                   : {inputs.wind.internal_pressure_coef_gcpi:.2f}")
    lines.append(f"  Kh (computed)          : {results.kh:.4f}")
    lines.append(f"  qh (computed)          : {results.qh_psf:.2f} psf")
    lines.append("")
    lines.append("PRODUCT APPROVAL")
    lines.append(f"  Manufacturer         : {inputs.product.manufacturer}")
    lines.append(f"  Product Approval No  : {inputs.product.product_approval_no}")
    lines.append(f"  System / Type        : {inputs.product.system_number} / {inputs.product.system_type}")
    lines.append(f"  Description          : {inputs.product.product_description}")
    lines.append(f"  PA FS / RS / MDP     : {inputs.product.pa_fastener_spacing_in} in × "
                 f"{inputs.product.pa_row_spacing_in} in / "
                 f"{inputs.product.pa_max_design_pressure_psf} psf")
    lines.append(f"  Tributary X_PA       : {results.tributary_x_pa_sf:.4f} sf/fast")
    lines.append(f"  Allowable fv         : {results.allowable_fastener_value_lbf:.2f} lbf/fast")
    lines.append("")
    lines.append("CALCULATED FASTENER SPACING - RESULTS")
    lines.append(f"  {'Zone':<10}{'P (psf)':>12}{'FS in':>8}{'RS in':>8}"
                 f"{'X (sf)':>10}{'X_max':>10}{'Status':>30}")
    for z in results.zones:
        lines.append(
            f"  {z.zone_name:<10}{z.design_pressure_psf:>12.2f}"
            f"{z.fastener_spacing_in:>8.1f}{z.row_spacing_in:>8.1f}"
            f"{z.tributary_x_sf:>10.4f}{z.required_x_max_sf:>10.4f}"
            f"{z.status:>30}"
        )
    lines.append("")
    if results.validation:
        v = results.validation
        lines.append("VALIDATION CHECKS")
        lines.append(f"  Extrapolation ratio  : {v.extrapolation_ratio:.3f}  "
                     f"({'OK' if v.extrapolation_ok else 'FAIL'} - 300% limit)")
        lines.append(f"  Min fastener spacing : {v.min_fastener_spacing_in:.1f} in.o.c.  "
                     f"({'OK' if v.min_spacing_ok else 'FAIL'} - 6 in. min)")
        lines.append(f"  Max demand/capacity  : {v.max_demand_capacity:.3f}  "
                     f"({'OK' if v.overall_ok else 'FAIL'})")
    return "\n".join(lines)
