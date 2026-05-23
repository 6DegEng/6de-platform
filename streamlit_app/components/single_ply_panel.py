"""Single-Ply Attachment calculator UI panel.

Extracted into its own component so the parent page (8_Calculator.py) stays
small. The component is rendered inside the Native Calculators tab of the
Engineering page.

Pure presentation layer — all math lives in
`modules.calculator.single_ply_attachment`.
"""
from __future__ import annotations

import streamlit as st

from modules.calculator.single_ply_attachment import (
    BuildingInfo,
    CalcInputs,
    ProductApproval,
    ProjectInfo,
    WindInputs,
    ZoneSpacing,
    calculate,
    render_text_memo,
)


def render_single_ply_attachment_panel() -> None:
    """Render the input form + results for the single-ply attachment calc."""

    st.subheader("Native Calculators")
    st.caption(
        "In-platform engineering calculators. Outputs are saved as printable "
        "calc memos. Add new calcs in `modules/calculator/` and register a "
        "sub-tab below."
    )

    native_tabs = st.tabs(["Single-Ply Attachment (RAS 137 / ASCE 7-22)"])

    with native_tabs[0]:
        st.markdown(
            "**Mechanical attachment of single-ply membrane roof systems** — "
            "low-slope (≤ 7°), h ≤ 60 ft. Per FBC 2023 8th Ed. RAS 137 "
            "rational analysis and ASCE 7-22 Ch. 26 / 30 (C&C wind pressures)."
        )

        with st.form("single_ply_form"):
            # ----- Project Information -----
            st.markdown("##### Project Information")
            pc1, pc2 = st.columns(2)
            permit_number = pc1.text_input("Permit Number", key="sp_permit")
            process_number = pc2.text_input("Process Number", key="sp_process")
            roofing_contractor = pc1.text_input(
                "Roofing Contractor", value="Margo Roofing", key="sp_contractor"
            )
            date_prepared = pc2.text_input("Date Prepared", key="sp_date")
            job_address = st.text_input(
                "Job Address", value="2000 NW 67 St", key="sp_address"
            )

            # ----- Building Information -----
            st.markdown("##### Building Information")
            bc1, bc2, bc3 = st.columns(3)
            exposure_category = bc1.selectbox(
                "Exposure Category", ["B", "C", "D"], index=0, key="sp_exposure"
            )
            risk_category = bc2.selectbox(
                "Risk Category", [1, 2, 3, 4], index=1, key="sp_risk"
            )
            mean_roof_height_ft = bc3.number_input(
                "Mean Roof Height h (ft)",
                min_value=0.0, max_value=60.0, value=30.0, step=1.0,
                key="sp_mrh",
                help="ASCE 7-22 procedure used here is valid for h ≤ 60 ft.",
            )
            bc4, bc5 = st.columns(2)
            parapet_height_ft = bc4.number_input(
                "Parapet Height (ft)",
                min_value=0.0, value=0.0, step=0.5, key="sp_parapet",
            )
            deck_type = bc5.text_input(
                "Deck Type", value='Min. 5/8" plywood', key="sp_deck"
            )

            # ----- Wind Pressure Inputs -----
            st.markdown("##### Wind Pressure (ASCE 7-22 Ch. 30 — C&C)")
            wc1, wc2, wc3 = st.columns(3)
            basic_wind_speed_mph = wc1.number_input(
                "Basic Wind Speed V (mph)",
                min_value=85.0, max_value=250.0, value=175.0, step=5.0,
                key="sp_v",
                help="From ASCE 7 Hazard Tool for the project location.",
            )
            directionality_factor_kd = wc2.number_input(
                "Kd (Directionality)", value=0.85, step=0.05, key="sp_kd",
                help="Table 26.6-1 (0.85 for C&C of buildings).",
            )
            topographic_factor_kzt = wc3.number_input(
                "Kzt (Topographic)", value=1.0, step=0.05, key="sp_kzt",
            )
            wc4, wc5 = st.columns(2)
            ground_elevation_factor_ke = wc4.number_input(
                "Ke (Ground Elevation)", value=1.0, step=0.05, key="sp_ke",
            )
            internal_pressure_coef_gcpi = wc5.number_input(
                "GCpi (Internal Press. Coef.)",
                value=0.18, step=0.01, key="sp_gcpi",
                help="+0.18 for enclosed building (Table 26.13-1).",
            )

            st.markdown("##### External Pressure Coefficients GCp (Fig 30.3-2A)")
            gc1, gc2, gc3, gc4 = st.columns(4)
            gcp_zone_1_prime = gc1.number_input(
                "Zone 1'", value=-0.9, step=0.1, key="sp_gcp_1p"
            )
            gcp_zone_1 = gc2.number_input(
                "Zone 1", value=-1.7, step=0.1, key="sp_gcp_1"
            )
            gcp_zone_2 = gc3.number_input(
                "Zone 2", value=-2.3, step=0.1, key="sp_gcp_2"
            )
            gcp_zone_3 = gc4.number_input(
                "Zone 3", value=-3.2, step=0.1, key="sp_gcp_3"
            )

            # ----- Product Approval -----
            st.markdown("##### Product Approval (System / Fastener)")
            pa1, pa2 = st.columns(2)
            manufacturer = pa1.text_input("Manufacturer", value="GAF", key="sp_mfr")
            product_approval_no = pa2.text_input(
                "Product Approval No.", value="FL5293-R57", key="sp_pa_no"
            )
            system_number = pa1.text_input("System Number", value="W-66", key="sp_sys")
            system_type = pa2.text_input("System Type", value="C-2", key="sp_sys_type")
            product_description = st.text_input(
                "Product Description",
                value="EverGuard TPO 60 10x100",
                key="sp_descr",
            )
            pa3, pa4 = st.columns(2)
            full_sheet_width_in = pa3.number_input(
                "Full Sheet Width (in)", value=120.0, step=6.0, key="sp_sheet_w"
            )
            fastener_description = pa4.text_input(
                "Fastener Description",
                value="Drill-Tec #14 Double Barbed XHD 2-3/8",
                key="sp_fast_descr",
            )
            pa5, pa6, pa7 = st.columns(3)
            pa_fastener_spacing_in = pa5.number_input(
                "PA Fastener Spacing FS (in o.c.)",
                min_value=1.0, value=6.0, step=0.5, key="sp_pa_fs",
            )
            pa_row_spacing_in = pa6.number_input(
                "PA Row Spacing RS (in o.c.)",
                min_value=1.0, value=45.0, step=1.0, key="sp_pa_rs",
            )
            pa_max_design_pressure_psf = pa7.number_input(
                "PA Max Design Pressure MDP (psf)",
                value=-52.5, step=1.0, key="sp_mdp",
                help="Negative = uplift. From the system's product approval.",
            )

            # ----- Engineer-selected per-zone spacing -----
            st.markdown("##### Engineer-Selected Fastener Spacing per Zone")
            sp_col1, sp_col2 = st.columns(2)
            sp_col1.markdown("**Zone 1'**")
            fs_1p = sp_col1.number_input(
                "FS (in o.c.)", value=5.0, min_value=1.0, step=0.5, key="sp_z1p_fs"
            )
            rs_1p = sp_col1.number_input(
                "RS (in o.c.)", value=55.0, min_value=1.0, step=1.0, key="sp_z1p_rs"
            )
            sp_col2.markdown("**Zone 1**")
            fs_1 = sp_col2.number_input(
                "FS (in o.c.)", value=5.0, min_value=1.0, step=0.5, key="sp_z1_fs"
            )
            rs_1 = sp_col2.number_input(
                "RS (in o.c.)", value=27.5, min_value=1.0, step=1.0, key="sp_z1_rs"
            )
            sp_col3, sp_col4 = st.columns(2)
            sp_col3.markdown("**Zone 2**")
            fs_2 = sp_col3.number_input(
                "FS (in o.c.)", value=5.0, min_value=1.0, step=0.5, key="sp_z2_fs"
            )
            rs_2 = sp_col3.number_input(
                "RS (in o.c.)", value=20.0, min_value=1.0, step=1.0, key="sp_z2_rs"
            )
            sp_col4.markdown("**Zone 3**")
            fs_3 = sp_col4.number_input(
                "FS (in o.c.)", value=5.0, min_value=1.0, step=0.5, key="sp_z3_fs"
            )
            rs_3 = sp_col4.number_input(
                "RS (in o.c.)", value=15.0, min_value=1.0, step=1.0, key="sp_z3_rs"
            )

            submitted = st.form_submit_button("Run Calc", type="primary")

        if submitted:
            inputs = CalcInputs(
                project=ProjectInfo(
                    permit_number=permit_number,
                    process_number=process_number,
                    roofing_contractor=roofing_contractor,
                    date_prepared=date_prepared,
                    job_address=job_address,
                ),
                building=BuildingInfo(
                    exposure_category=exposure_category,
                    risk_category=int(risk_category),
                    mean_roof_height_ft=float(mean_roof_height_ft),
                    parapet_height_ft=float(parapet_height_ft),
                    deck_type=deck_type,
                ),
                wind=WindInputs(
                    basic_wind_speed_mph=float(basic_wind_speed_mph),
                    directionality_factor_kd=float(directionality_factor_kd),
                    topographic_factor_kzt=float(topographic_factor_kzt),
                    ground_elevation_factor_ke=float(ground_elevation_factor_ke),
                    internal_pressure_coef_gcpi=float(internal_pressure_coef_gcpi),
                    gcp_zone_1_prime=float(gcp_zone_1_prime),
                    gcp_zone_1=float(gcp_zone_1),
                    gcp_zone_2=float(gcp_zone_2),
                    gcp_zone_3=float(gcp_zone_3),
                ),
                product=ProductApproval(
                    manufacturer=manufacturer,
                    system_number=system_number,
                    product_approval_no=product_approval_no,
                    system_type=system_type,
                    product_description=product_description,
                    full_sheet_width_in=float(full_sheet_width_in),
                    fastener_description=fastener_description,
                    pa_fastener_spacing_in=float(pa_fastener_spacing_in),
                    pa_row_spacing_in=float(pa_row_spacing_in),
                    pa_max_design_pressure_psf=float(pa_max_design_pressure_psf),
                ),
                zone_spacing={
                    "Zone 1'": ZoneSpacing(float(fs_1p), float(rs_1p)),
                    "Zone 1": ZoneSpacing(float(fs_1), float(rs_1)),
                    "Zone 2": ZoneSpacing(float(fs_2), float(rs_2)),
                    "Zone 3": ZoneSpacing(float(fs_3), float(rs_3)),
                },
            )
            try:
                results = calculate(inputs)
                st.session_state["sp_results"] = results
                st.session_state["sp_inputs"] = inputs
            except Exception as exc:
                st.error(f"Calc failed: {exc}")
                st.stop()

        # ----- Render results -----
        results = st.session_state.get("sp_results")
        inputs_snapshot = st.session_state.get("sp_inputs")
        if results is not None and inputs_snapshot is not None:
            st.markdown("---")
            st.markdown("#### Results")
            rcols = st.columns(4)
            rcols[0].metric("Kh", f"{results.kh:.4f}")
            rcols[1].metric("qh (psf)", f"{results.qh_psf:.2f}")
            rcols[2].metric(
                "X_PA (sf/fast)", f"{results.tributary_x_pa_sf:.4f}"
            )
            rcols[3].metric(
                "fv (lbf/fast)", f"{results.allowable_fastener_value_lbf:.2f}"
            )

            st.markdown("**Per-Zone Results**")
            zone_rows = [
                {
                    "Zone": z.zone_name,
                    "P (psf)": round(z.design_pressure_psf, 2),
                    "FS (in o.c.)": z.fastener_spacing_in,
                    "RS (in o.c.)": z.row_spacing_in,
                    "X (sf/fast)": round(z.tributary_x_sf, 4),
                    "X_max (sf/fast)": round(z.required_x_max_sf, 4),
                    "D/C": round(z.utilization, 3),
                    "Status": z.status,
                }
                for z in results.zones
            ]
            st.dataframe(zone_rows, use_container_width=True, hide_index=True)

            st.markdown("**Validation**")
            v = results.validation
            vcols = st.columns(3)
            vcols[0].metric(
                "Extrapolation ratio",
                f"{v.extrapolation_ratio:.3f}",
                delta="OK" if v.extrapolation_ok else "Exceeds 300%",
                delta_color="normal" if v.extrapolation_ok else "inverse",
            )
            vcols[1].metric(
                "Min FS (in o.c.)",
                f"{v.min_fastener_spacing_in:.1f}",
                delta="OK ≥ 6 in" if v.min_spacing_ok else "Below 6 in min",
                delta_color="normal" if v.min_spacing_ok else "inverse",
            )
            vcols[2].metric(
                "Max D/C",
                f"{v.max_demand_capacity:.3f}",
                delta="OK" if v.overall_ok else "FAIL",
                delta_color="normal" if v.overall_ok else "inverse",
            )

            if v.overall_ok and v.extrapolation_ok and v.min_spacing_ok:
                st.success(
                    "All zones pass and all validation gates satisfied."
                )
            elif v.overall_ok:
                st.warning(
                    "All zones pass strength check, but one or more "
                    "validation gates flag the calc for engineer review "
                    "(extrapolation or minimum spacing)."
                )
            else:
                st.error(
                    "Calc FAILS — one or more zones exceed allowable "
                    "tributary area. Tighten spacing."
                )

            # ----- Memo export -----
            memo_text = render_text_memo(inputs_snapshot, results)
            permit_slug = (
                inputs_snapshot.project.permit_number or "unsealed"
            ).replace(" ", "_")
            st.download_button(
                "Download Calc Memo (.txt)",
                data=memo_text,
                file_name=f"single_ply_attachment_{permit_slug}.txt",
                mime="text/plain",
                key="sp_download_memo",
            )
            with st.expander("Preview memo text"):
                st.code(memo_text, language=None)
