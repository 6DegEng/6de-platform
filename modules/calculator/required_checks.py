"""Seed data for calc_required_checks — the code-required checks per structure type.

Called by db.ensure_db() at startup. Idempotent via INSERT OR IGNORE on the
(structure_type, check_label) UNIQUE constraint.
"""
from __future__ import annotations

import sqlite3


REQUIRED_CHECKS: list[dict] = [
    # --- Glass Railing (with base shoe) ---
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "Top rail 50 plf line load",
        "code_ref": "IBC 1607.8.1.1 / ASCE 7-22 §4.5.1.1",
        "severity": "required",
        "notes": "Uniform load along top rail; separate from concentrated.",
    },
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "Top rail 200 lb concentrated, any direction",
        "code_ref": "IBC 1607.8.1.1",
        "severity": "required",
        "notes": "Applied at any point and in any direction on the top rail.",
    },
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "50 lbf infill load on 1 sq ft",
        "code_ref": "IBC 1607.8.1.2 / ASCE 7-22 §4.5.1.2",
        "severity": "required",
        "notes": "Normal to infill over 1 ft² area; governs glass bending.",
    },
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "Impact load on glass guard",
        "code_ref": "IBC 1607.8.1.3 / ASCE 7-22 §4.5.1.3",
        "severity": "required",
        "notes": "Often governs in FL exterior applications over wind.",
    },
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "Glass type (tempered/laminated) & interlayer specified",
        "code_ref": "IBC 2407.1.2 / ASTM E2353",
        "severity": "required",
        "notes": "Must state monolithic vs laminated, interlayer (PVB/SGP), heat treatment.",
    },
    {
        "structure_type": "Glass Railing (with base shoe)",
        "check_label": "Post-breakage redundancy if no continuous top rail",
        "code_ref": "IBC 2407.1.4.1 / ASTM E2358",
        "severity": "required",
        "notes": "Laminated with sufficient post-breakage capacity required.",
    },
    # --- Glass Railing (exterior, with base shoe) ---
    {
        "structure_type": "Glass Railing (exterior, with base shoe)",
        "check_label": "ASCE 7-22 component-and-cladding wind pressure",
        "code_ref": "ASCE 7-22 §29.3",
        "severity": "required",
        "notes": "C&C wind pressure on glass infill panel; exterior only.",
    },
    # --- Wall-Mounted Handrail ---
    {
        "structure_type": "Wall-Mounted Handrail",
        "check_label": "200 lb concentrated load in any direction",
        "code_ref": "IBC 1607.8.1.1",
        "severity": "required",
        "notes": "Applied at any point along top of handrail in any direction.",
    },
    {
        "structure_type": "Wall-Mounted Handrail",
        "check_label": "50 plf uniform load",
        "code_ref": "IBC 1607.8.1.1",
        "severity": "required",
        "notes": "Uniform line load along top of handrail.",
    },
    {
        "structure_type": "Wall-Mounted Handrail",
        "check_label": "Graspability Type I (round) or Type II (recessed)",
        "code_ref": "IBC 1014.3",
        "severity": "required",
        "notes": "Type I: 1.25-2 in circular. Type II: 4-6.25 in perimeter with recesses.",
    },
    {
        "structure_type": "Wall-Mounted Handrail",
        "check_label": "≥ 1½ in clear between handrail and wall",
        "code_ref": "IBC 1014.7",
        "severity": "required",
        "notes": "Bracket detail must show and verify 1.5 in minimum clearance.",
    },
    # --- Steel Stair ---
    {
        "structure_type": "Steel Stair",
        "check_label": "Stringer total deflection ≤ L/240 (or stricter per spec)",
        "code_ref": "IBC 1604.3 / FBC 1604.3",
        "severity": "required",
        "notes": "Total load deflection on stringer span.",
    },
    {
        "structure_type": "Steel Stair",
        "check_label": "Stringer live-load deflection ≤ L/360",
        "code_ref": "IBC Table 1604.3 footnote f",
        "severity": "required",
        "notes": "Live load only, checked separately from total deflection.",
    },
    {
        "structure_type": "Steel Stair",
        "check_label": "Connection moment transferred to slab/wall — local check",
        "code_ref": "ACI 318-19 Ch. 17 / AISC 360-22",
        "severity": "required",
        "notes": "Local punching/bending on existing slab at base plate.",
    },
    {
        "structure_type": "Steel Stair",
        "check_label": "Bolt/weld combined stress at all field connections",
        "code_ref": "AISC 360-22 Ch. J",
        "severity": "required",
        "notes": "Shear + tension interaction at bolted/welded field splices.",
    },
    # --- All — Post-installed anchor ---
    {
        "structure_type": "All — Post-installed anchor",
        "check_label": "ESR / ICC-ES report cited with edition + table",
        "code_ref": "ICC-ES AC193 / AC308",
        "severity": "required",
        "notes": "Manufacturer + product + ESR # + edition + table + cracked basis.",
    },
    {
        "structure_type": "All — Post-installed anchor",
        "check_label": "Cracked vs uncracked concrete basis stated",
        "code_ref": "ACI 318-19 §17.3",
        "severity": "required",
        "notes": "Allowables differ 30-50%; default to cracked for unknown slabs.",
    },
    {
        "structure_type": "All — Post-installed anchor",
        "check_label": "Existing concrete f'c stated",
        "code_ref": "ACI 318-19 §17",
        "severity": "required",
        "notes": "ESR tables require minimum f'c (typically ≥ 2500 psi).",
    },
    # --- All — Wood connection ---
    {
        "structure_type": "All — Wood connection",
        "check_label": "NDS 2018 adjustment factors (Cd, Cm, Ct, Cg, CΔ) shown",
        "code_ref": "NDS 2018 §11.3",
        "severity": "required",
        "notes": "Each factor must be stated explicitly with final adjusted value.",
    },
]


def seed_required_checks(conn: sqlite3.Connection) -> int:
    """Insert the required-checks seed data. Idempotent via INSERT OR IGNORE."""
    inserted = 0
    for check in REQUIRED_CHECKS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO calc_required_checks "
            "(structure_type, check_label, code_ref, severity, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                check["structure_type"],
                check["check_label"],
                check["code_ref"],
                check["severity"],
                check.get("notes"),
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    return inserted
