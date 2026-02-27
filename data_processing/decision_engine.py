from __future__ import annotations

import pandas as pd


def apply_decision_logic(
    metrics_df: pd.DataFrame,
    target_roas: float,
    min_installs: int = 200,
    upper_buffer: float = 1.15,
    lower_buffer: float = 0.9,
) -> pd.DataFrame:
    out = metrics_df.copy()
    upper = target_roas * upper_buffer
    lower = target_roas * lower_buffer

    def _decide_with_reason(row: pd.Series) -> tuple[str, str]:
        installs = int(row.get("installs", 0))
        d7_roas = float(row.get("d7_roas", 0.0))

        if installs < min_installs:
            return (
                "Hold (Low Sample)",
                f"installs {installs} < min_installs {min_installs}",
            )

        if d7_roas > upper:
            return (
                "Scale Up",
                f"d7_roas {d7_roas:.3f} > upper_bound {upper:.3f}",
            )
        if d7_roas < lower:
            return (
                "Scale Down",
                f"d7_roas {d7_roas:.3f} < lower_bound {lower:.3f}",
            )
        return (
            "Maintain",
            f"lower_bound {lower:.3f} <= d7_roas {d7_roas:.3f} <= upper_bound {upper:.3f}",
        )

    decision_reason = out.apply(_decide_with_reason, axis=1)
    out[["decision", "decision_reason"]] = pd.DataFrame(decision_reason.tolist(), index=out.index)

    if target_roas > 0:
        out["roas_gap_vs_target_pct"] = (out.get("d7_roas", 0) - target_roas) / target_roas * 100
    else:
        out["roas_gap_vs_target_pct"] = 0.0
    out["install_gap_to_min"] = out.get("installs", 0) - min_installs

    def _efficiency_note(row: pd.Series) -> str:
        if int(row.get("installs", 0)) < min_installs:
            return "Sample risk"
        if float(row.get("d7_roas", 0.0)) >= upper:
            return "Strong efficiency"
        if float(row.get("d7_roas", 0.0)) < lower:
            return "Efficiency risk"
        return "Near target"

    out["efficiency_note"] = out.apply(_efficiency_note, axis=1)
    return out
