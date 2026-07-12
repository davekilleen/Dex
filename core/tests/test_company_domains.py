import json
from pathlib import Path

from core.utils.company_domains import company_name_from_domain, is_freemail, registrable_domain


def test_company_domain_golden_fixture():
    fixture = Path(__file__).parent / "fixtures" / "entity_pages" / "company_domains.json"
    for case in json.loads(fixture.read_text()):
        assert registrable_domain(case["input"]) == case["registrable_domain"]
        assert company_name_from_domain(case["input"]) == case["company_name"]
        assert is_freemail(case["input"]) is case["freemail"]
