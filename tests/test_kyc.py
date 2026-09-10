import asyncio

from greedy_collector.kyc import KycScreeningEngine, SOURCE_CATALOG
from greedy_collector.schemas import KycQuery


def test_all_requested_source_families_are_catalogued():
    ids = {source.id for source in SOURCE_CATALOG}
    assert {
        "opensanctions",
        "ofac",
        "un_sanctions",
        "uk_ofsi",
        "eu_sanctions",
        "interpol",
        "opencorporates",
        "companies_house",
        "sec_edgar",
        "occrp_aleph",
        "india_mca",
        "gst_india",
        "icann",
        "arin_rdap",
        "crtsh",
        "urlscan",
        "virustotal",
        "gdelt",
    }.issubset(ids)


def test_opencorporates_and_companies_house_are_manual_only():
    """Verify that OpenCorporates and Companies House remain manual-review sources with no credential metadata."""
    opencorporates = next((s for s in SOURCE_CATALOG if s.id == "opencorporates"), None)
    companies_house = next((s for s in SOURCE_CATALOG if s.id == "companies_house"), None)
    
    assert opencorporates is not None, "OpenCorporates not in SOURCE_CATALOG"
    assert companies_house is not None, "Companies House not in SOURCE_CATALOG"
    
    # Both must be in "manual" mode (analyst leaves Epic Archer to search)
    assert opencorporates.mode == "manual", "OpenCorporates should be manual-only"
    assert companies_house.mode == "manual", "Companies House should be manual-only"
    
    # Both are corporate-category sources
    assert opencorporates.category == "corporate", "OpenCorporates should be corporate category"
    assert companies_house.category == "corporate", "Companies House should be corporate category"
    
    # CRITICAL: No credential metadata (no active API support)
    assert opencorporates.credential_env is None, "OpenCorporates should not have credential_env (manual-only)"
    assert companies_house.credential_env is None, "Companies House should not have credential_env (manual-only)"
    
    # Both have official registry URLs
    assert "opencorporates.com" in opencorporates.search_url
    assert "find-and-update.company-information.service.gov.uk" in companies_house.search_url
    
    # Verify they are included in manual sources returned to analyst
    engine = KycScreeningEngine()
    result = engine._manual_source(opencorporates, KycQuery(name="Example Corp"))
    assert result["id"] == "opencorporates"
    assert "opencorporates.com" in result["url"]
    assert "Example+Corp" in result["url"]
    
    result = engine._manual_source(companies_house, KycQuery(name="Example Corp"))
    assert result["id"] == "companies_house"
    assert "find-and-update.company-information.service.gov.uk" in result["url"]


def test_screening_preserves_manual_review_and_disclaimer(monkeypatch):
    engine = KycScreeningEngine()

    async def no_matches(query):
        return {"source": "fixture", "checked": True, "matches": []}

    monkeypatch.setattr(engine, "_opensanctions", no_matches)
    monkeypatch.setattr(engine, "_interpol", no_matches)
    monkeypatch.setattr(engine, "_sec_edgar", no_matches)
    monkeypatch.setattr(engine, "_gdelt", no_matches)
    result = asyncio.run(engine.screen(KycQuery(name="Example Person")))
    assert result["manual_sources"]
    assert "does not establish identity" in result["disclaimer"]
