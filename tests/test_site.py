"""Guards for the static site's hard rules (no JS runtime needed)."""

import re
from pathlib import Path

from worlds import export

SITE = Path(__file__).resolve().parents[1] / "site"
JS = sorted((SITE / "js").glob("*.mjs"))
HTML = sorted(SITE.glob("*.html"))
RIOT_NOTICE = (
    'LoL Worlds Predictor was created under Riot Games\' "Legal Jibber Jabber" policy '
    "using assets owned by Riot Games. Riot Games does not endorse or sponsor this project."
)


def test_pages_exist_and_load_only_local_files():
    names = {p.name for p in HTML}
    assert names == {
        "index.html",
        "teams.html",
        "team.html",
        "matches.html",
        "match.html",
        "model.html",
    }
    for page in HTML:
        text = page.read_text()
        for ref in re.findall(r'(?:src|href)="([^"]+)"', text):
            assert not re.match(r"(?:https?:)?//", ref), f"{page.name} loads {ref}"
            assert (SITE / ref).exists(), f"{page.name} refers to missing {ref}"


def test_no_innerhtml_eval_or_external_scripts_in_js():
    for f in JS:
        text = f.read_text()
        if f.name.endswith(".test.mjs"):
            continue
        assert not re.search(
            r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function",
            text,
        ), f.name
        assert not re.search(r"import\s*\(?\s*[\"']https?:", text), f.name
        assert "cdn" not in text.lower(), f.name


def test_riot_notice_verbatim_and_oracles_elixir_credit():
    shell = (SITE / "js/shell.mjs").read_text()
    # the notice is written in a JS string with escapes; compare after unescaping
    m = re.search(r"const RIOT_NOTICE =\s*'(.*?)';", shell, re.DOTALL)
    assert m and m.group(1).replace("\\'", "'") == RIOT_NOTICE
    assert "Oracle's Elixir" in shell and "oracleselixir.com" in shell


def test_site_title_and_no_trademarks_or_logos():
    for page in HTML:
        assert "<img" not in page.read_text()
    assert not list((SITE).rglob("*.png")) and not list(SITE.rglob("*.svg"))
    assert "LoL Worlds Predictor" in (SITE / "js/shell.mjs").read_text()


def test_js_provenance_labels_match_the_exporter():
    prov = (SITE / "js/prov.mjs").read_text()
    block = re.search(r"export const PROV = \{(.*?)\};", prov, re.DOTALL).group(1)
    keys = re.findall(r"^\s*(\w+):", block, re.MULTILINE)
    assert set(keys) == set(export.PROVENANCE)
    css = (SITE / "css/style.css").read_text()
    for k in export.PROVENANCE:
        assert f".prov-{k} " in css or f".prov-{k}{{" in css, f"no style for {k}"


def test_data_files_the_pages_fetch_are_exported():
    data = SITE / "data"
    for f in (
        "meta.json",
        "model.json",
        "matches.json",
        "overview_2026.json",
        "teams/index.json",
    ):
        assert (data / f).exists(), f
    fetched = set()
    for f in JS:
        fetched |= set(re.findall(r'load\("([^"$]+\.json)"\)', f.read_text()))
    assert fetched <= {p.relative_to(data).as_posix() for p in data.rglob("*.json")}
