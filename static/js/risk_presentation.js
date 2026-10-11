export function riskPresentation(risk = {}) {
  const versioned = risk.model_version === "deterministic-v3";
  return {
    overall: risk.overall_score ?? risk.score ?? null,
    tier: risk.overall_tier ?? risk.level ?? "Unassessed",
    behavioralExposure: versioned ? risk.behavioral_exposure_score : null,
    model: risk.model_version ?? risk.scoring_model ?? "Historical model unavailable",
    overrides: Array.isArray(risk.overrides) ? risk.overrides.map(item => item.reason).filter(Boolean) : [],
    statuses: Array.isArray(risk.authoritative_status) ? risk.authoritative_status.map(item => `${item.source || "Authoritative source"}: ${item.listing_state || "unknown"} (${item.match_type || "unknown"})${item.stale ? "; registry stale" : ""}`) : [],
    limitations: Array.isArray(risk.limitations) ? risk.limitations : [],
    coverage: risk.data_coverage?.status || "UNKNOWN",
    versioned,
  };
}
