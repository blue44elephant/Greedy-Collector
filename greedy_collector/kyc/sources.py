from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDescriptor:
    id: str
    name: str
    category: str
    mode: str
    search_url: str
    credential_env: str | None = None
    note: str = ""


SOURCE_CATALOG = [
    SourceDescriptor("opensanctions", "OpenSanctions", "sanctions", "api", "https://www.opensanctions.org/search/?q={query}", "OPENSANCTIONS_API_KEY"),
    SourceDescriptor("openscreening", "OpenScreening", "screening", "manual", "https://openscreening.com/search?q={query}"),
    SourceDescriptor("ofac", "OFAC Sanctions List Search", "sanctions", "manual", "https://sanctionssearch.ofac.treas.gov/", note="Use the official search portal and review identifiers."),
    SourceDescriptor("un_sanctions", "UN Security Council Consolidated List", "sanctions", "manual", "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list?search={query}"),
    SourceDescriptor("uk_ofsi", "UK Sanctions List / OFSI", "sanctions", "manual", "https://search-uk-sanctions-list.service.gov.uk/?q={query}"),
    SourceDescriptor("eu_sanctions", "EU Sanctions Map", "sanctions", "manual", "https://www.sanctionsmap.eu/#/main?search={query}"),
    SourceDescriptor("us_csl", "U.S. Consolidated Screening List", "screening", "manual", "https://www.trade.gov/consolidated-screening-list?search={query}"),
    SourceDescriptor("fiu_india", "FIU-India UNSC Sanctions Updates", "sanctions", "manual", "https://fiuindia.gov.in/files/UNSC/UNSC.html"),
    SourceDescriptor("interpol", "INTERPOL Public Notices", "notices", "api", "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices#{query}"),
    SourceDescriptor("opencorporates", "OpenCorporates", "corporate", "manual", "https://opencorporates.com/companies?q={query}"),
    SourceDescriptor("companies_house", "Companies House UK", "corporate", "manual", "https://find-and-update.company-information.service.gov.uk/search?q={query}"),
    SourceDescriptor("sec_edgar", "SEC EDGAR", "corporate", "api", "https://www.sec.gov/edgar/search/#/q={query}"),
    SourceDescriptor("open_ownership", "Open Ownership Register", "ownership", "manual", "https://register.openownership.org/search?q={query}"),
    SourceDescriptor("occrp_aleph", "OCCRP Aleph", "investigations", "manual", "https://aleph.occrp.org/search?q={query}"),
    SourceDescriptor("india_mca", "India MCA Master Data", "corporate", "manual", "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html"),
    SourceDescriptor("gst_india", "GST Taxpayer Search", "corporate", "manual", "https://services.gst.gov.in/services/searchtp"),
    SourceDescriptor("icann", "ICANN Lookup", "domain", "manual", "https://lookup.icann.org/en/lookup?name={query}"),
    SourceDescriptor("arin_rdap", "ARIN RDAP / WHOIS", "network", "manual", "https://search.arin.net/rdap/?query={query}"),
    SourceDescriptor("crtsh", "crt.sh", "domain", "api", "https://crt.sh/?q={query}"),
    SourceDescriptor("urlscan", "urlscan.io", "domain", "api", "https://urlscan.io/search/#*domain:{query}", "URLSCAN_API_KEY"),
    SourceDescriptor("virustotal", "VirusTotal", "domain", "api", "https://www.virustotal.com/gui/search/{query}", "VIRUSTOTAL_API_KEY"),
    SourceDescriptor("google", "Google Search Operators", "web", "manual", "https://www.google.com/search?q=%22{query}%22"),
    SourceDescriptor("google_alerts", "Google Alerts", "monitoring", "manual", "https://www.google.com/alerts#1:0"),
    SourceDescriptor("gdelt", "GDELT", "news", "api", "https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=artlist"),
    SourceDescriptor("local_sources", "Local News / Court / Regulator Searches", "local", "manual", "https://www.google.com/search?q=%22{query}%22+court+OR+regulator+OR+enforcement"),
]
