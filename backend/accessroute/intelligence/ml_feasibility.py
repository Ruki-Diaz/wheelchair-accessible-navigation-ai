"""Machine Learning Feasibility and Research Evaluation.

Stage 10 Research Component:
Evaluates whether current open pedestrian networks contain sufficient, defensible
labelled ground-truth data for supervised machine learning (e.g., kerb ramp prediction).

SCIENTIFIC STANDARDS:
1. Audits label sparsity and class imbalance directly from real OSM data.
2. Avoids synthetic label inflation.
3. Documents: 'Insufficient labelled accessibility data for defensible supervised learning'
   when real ground truth is inadequate.
4. Any research predictions MUST remain marked RESEARCH_PREDICTION and are NEVER
   injected as authoritative routing evidence.
"""

from typing import Any, Dict, List, Optional
import networkx as nx

from accessroute.scoring.models import KerbType


class MLFeasibilityAuditor:
    """Evaluates the statistical feasibility of supervised machine learning on accessibility tags."""

    @staticmethod
    def audit_kerb_labels(graph: nx.MultiDiGraph) -> Dict[str, Any]:
        """Audit real-world label coverage for pedestrian crossing kerb ramps."""
        total_crossings = 0
        labeled_lowered = 0
        labeled_flush = 0
        labeled_raised = 0
        labeled_no_kerb = 0
        unknown_kerb = 0

        for u, v, k, d in graph.edges(keys=True, data=True):
            hw = str(d.get("highway", "")).lower()
            is_cross = bool(d.get("is_crossing")) or hw == "crossing"
            if is_cross:
                total_crossings += 1
                kerb = str(d.get("kerb", "unknown")).lower()
                if kerb == "lowered":
                    labeled_lowered += 1
                elif kerb == "flush":
                    labeled_flush += 1
                elif kerb == "raised":
                    labeled_raised += 1
                elif kerb == "no_kerb":
                    labeled_no_kerb += 1
                else:
                    unknown_kerb += 1

        total_labeled = labeled_lowered + labeled_flush + labeled_raised + labeled_no_kerb
        labeled_pct = (total_labeled / max(1, total_crossings)) * 100.0 if total_crossings > 0 else 0.0

        # Scientific feasibility assessment
        # A defensible supervised classifier requires adequate sample size and balanced classes
        # with geographic independence to avoid severe spatial autocorrelation / leakage.
        is_feasible = (total_labeled >= 500 and labeled_pct >= 40.0)

        if not is_feasible:
            conclusion = "Insufficient labelled accessibility data for defensible supervised learning."
            recommendation = (
                f"Only {total_labeled}/{total_crossings} ({labeled_pct:.1f}%) crossings have recorded ground-truth "
                f"kerb labels in this region. Training a model on this sparse, heavily biased sample risks severe "
                f"spatial leakage and spurious correlations. Prioritize community verification missions before supervised training."
            )
        else:
            conclusion = "Sufficient labelled data available for exploratory research benchmark."
            recommendation = "Proceed with spatial cross-validation, strictly isolating test folds by geographic sector."

        return {
            "total_crossings": total_crossings,
            "total_labeled_crossings": total_labeled,
            "labeled_percentage": round(labeled_pct, 1),
            "unknown_percentage": round(100.0 - labeled_pct, 1),
            "class_distribution": {
                "lowered": labeled_lowered,
                "flush": labeled_flush,
                "raised": labeled_raised,
                "no_kerb": labeled_no_kerb,
                "unknown": unknown_kerb,
            },
            "is_supervised_learning_defensible": is_feasible,
            "scientific_conclusion": conclusion,
            "recommendation": recommendation,
        }
