import json
import os
from datetime import datetime

from core.mcp import work_server
from core.utils.entity_pages import render_company_page


def test_build_company_index_and_rebuild_on_page_mtime(tmp_path, monkeypatch):
    companies = tmp_path / "companies"
    companies.mkdir()
    (companies / "README.md").write_text("ignored")
    acme = companies / "Acme.md"
    acme.write_text(render_company_page("Acme", ["acme.co.uk"], "https://acme.co.uk", "Prospect"))
    index_file = tmp_path / "System" / "Company_Index.json"
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "COMPANY_INDEX_FILE", index_file)
    monkeypatch.setattr(work_server, "get_companies_dir", lambda: companies)

    index = work_server.build_company_index_data()
    assert index["total"] == 1
    assert index["companies"] == [{
        "name": "Acme", "path": "companies/Acme.md", "domains": ["acme.co.uk"],
        "website": "https://acme.co.uk", "status": "Prospect",
    }]
    assert work_server.find_company_by_domain("mail.acme.co.uk")["name"] == "Acme"

    old_built_at = index["built_at"]
    future = datetime.fromisoformat(old_built_at).timestamp() + 2
    os.utime(acme, (future, future))
    assert work_server.find_company_by_domain("acme.co.uk")["name"] == "Acme"
    assert json.loads(index_file.read_text())["built_at"] != old_built_at
