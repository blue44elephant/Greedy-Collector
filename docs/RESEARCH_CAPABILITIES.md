# Research capability audit

Authority: current source catalog, screening engine, schemas, service persistence and router, inspected before frontend implementation. Baseline: 226 tests. No live sources queried.

The current API exposes GET `/api/greedy-collector/kyc/sources`, POST `/api/greedy-collector/kyc/screen`, PATCH `/api/greedy-collector/kyc/matches/{match_id}`. Runs and matches persist in SQLite; no run-list/detail endpoint exists. Case entity types contain no research-match type.

| ID | Source | Category | Mode | Key | Actual inputs | Output / URL behavior | Failure behavior |
|---|---|---|---|---|---|---|---|
| opensanctions | OpenSanctions | sanctions | api | Required | name | Entities from name search; entity-ID URL | Unavailable on caught request/parse error; missing key unavailable |
| openscreening | OpenScreening | screening | manual | None | name | Manual link only: https://openscreening.com/search?q={query} | Not queried by GC; analyst checks external site |
| ofac | OFAC Sanctions List Search | sanctions | manual | None | None (fixed portal) | Manual link only: https://sanctionssearch.ofac.treas.gov/ | Not queried by GC; analyst checks external site |
| un_sanctions | UN Security Council Consolidated List | sanctions | manual | None | name | Manual link only: https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list?search={query} | Not queried by GC; analyst checks external site |
| uk_ofsi | UK Sanctions List / OFSI | sanctions | manual | None | name | Manual link only: https://search-uk-sanctions-list.service.gov.uk/?q={query} | Not queried by GC; analyst checks external site |
| eu_sanctions | EU Sanctions Map | sanctions | manual | None | name | Manual link only: https://www.sanctionsmap.eu/#/main?search={query} | Not queried by GC; analyst checks external site |
| us_csl | U.S. Consolidated Screening List | screening | manual | None | name | Manual link only: https://www.trade.gov/consolidated-screening-list?search={query} | Not queried by GC; analyst checks external site |
| fiu_india | FIU-India UNSC Sanctions Updates | sanctions | manual | None | None (fixed portal) | Manual link only: https://fiuindia.gov.in/files/UNSC/UNSC.html | Not queried by GC; analyst checks external site |
| interpol | INTERPOL Public Notices | notices | api | None | name | Public notices; returned self URL | Unavailable on caught request/parse error |
| opencorporates | OpenCorporates | corporate | manual | None | name | Manual link only: https://opencorporates.com/companies?q={query} | Not queried by GC; analyst checks external site |
| companies_house | Companies House UK | corporate | manual | None | name | Manual link only: https://find-and-update.company-information.service.gov.uk/search?q={query} | Not queried by GC; analyst checks external site |
| sec_edgar | SEC EDGAR | corporate | api | None | name | Ticker registry names with similarity >=0.7, up to 20; CIK browse URL | Unavailable on caught request/parse error |
| open_ownership | Open Ownership Register | ownership | manual | None | name | Manual link only: https://register.openownership.org/search?q={query} | Not queried by GC; analyst checks external site |
| occrp_aleph | OCCRP Aleph | investigations | manual | None | name | Manual link only: https://aleph.occrp.org/search?q={query} | Not queried by GC; analyst checks external site |
| india_mca | India MCA Master Data | corporate | manual | None | None (fixed portal) | Manual link only: https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html | Not queried by GC; analyst checks external site |
| gst_india | GST Taxpayer Search | corporate | manual | None | None (fixed portal) | Manual link only: https://services.gst.gov.in/services/searchtp | Not queried by GC; analyst checks external site |
| icann | ICANN Lookup | domain | manual | None | domain, or name fallback | Manual link only: https://lookup.icann.org/en/lookup?name={query} | Not queried by GC; analyst checks external site |
| arin_rdap | ARIN RDAP / WHOIS | network | manual | None | domain, or name fallback | Manual link only: https://search.arin.net/rdap/?query={query} | Not queried by GC; analyst checks external site |
| crtsh | crt.sh | domain | api | None | domain | Deduplicated certificate names, up to 50; certificate-ID URL | Unavailable on caught request/parse error |
| urlscan | urlscan.io | domain | api | Optional; public requests without key | domain | Up to 20 existing public scan records; returned result URL | Unavailable on caught request/parse error |
| virustotal | VirusTotal | domain | api | Required | domain | One domain reputation metadata record; domain GUI URL | Unavailable on caught request/parse error; missing key unavailable |
| google | Google Search Operators | web | manual | None | name | Manual link only: https://www.google.com/search?q=%22{query}%22 | Not queried by GC; analyst checks external site |
| google_alerts | Google Alerts | monitoring | manual | None | None (fixed portal) | Manual link only: https://www.google.com/alerts#1:0 | Not queried by GC; analyst checks external site |
| gdelt | GDELT | news | api | None | name | Up to 20 article records; returned article URL | Unavailable on caught request/parse error |
| local_sources | Local News / Court / Regulator Searches | local | manual | None | name | Manual link only: https://www.google.com/search?q=%22{query}%22+court+OR+regulator+OR+enforcement | Not queried by GC; analyst checks external site |

Automated adapters use name/domain only. Aliases, country, date_of_birth and identifier are stored with the query but ignored by all current matching adapters. They are omitted from this UI. Domain sources are not scheduled without a domain; they are not provider failures. include_manual_sources controls link generation.

Match score is `round(SequenceMatcher(None, subject.casefold(), query.casefold()).ratio(), 3)`, a 0–1 text similarity. VirusTotal compares the queried domain to itself and therefore returns 1; this is not domain safety, identity probability, or wallet risk. SEC uses >=0.7 for filtering. Other adapters retain returned records without this filter.

Initial limitations: capability API reports credential variable names but no configured boolean; unexpected gather exceptions disappear from source accounting; raw provider evidence and persisted errors can carry credentials; blank names and URL-shaped domains pass schema validation. Focused failing regressions precede these narrow corrections.

No automatic attribution, wallet association, label creation, new sources, historical-run browser, or research-match case entity is introduced. Copy/open source records and add a case note manually.
