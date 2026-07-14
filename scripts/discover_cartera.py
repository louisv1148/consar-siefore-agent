"""Discover the CONSAR SISET 'cartera por instrumento' report id + its line-item
checkboxes (renta variable internacional / estructurados / FIBRAS).

Read-only exploration: navigates the SISET portal with the same headless-Chrome
setup the download pipeline uses, dumps the report catalog and, for a candidate
report, the available series checkboxes with their labels + values. Nothing is
written to the CRM or committed; output is printed for a human to read.

Usage:
    python3 scripts/discover_cartera.py            # dump the catalog tree
    python3 scripts/discover_cartera.py <cd>       # dump one report's checkboxes
"""
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


def init_driver():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1400,2000")
    return webdriver.Chrome(options=o)


def dump_catalog(d):
    """Walk the SISET landing tree; print every report link/label we can see."""
    d.get("https://www.consar.gob.mx/gobmx/aplicativo/siset/CuadroInicial.aspx")
    time.sleep(3)
    print("TITLE:", d.title)
    # SISET renders a tree of links; harvest anchors + list items.
    for tag in ("a", "span", "li"):
        for el in d.find_elements(By.TAG_NAME, tag):
            txt = (el.text or "").strip()
            if not txt:
                continue
            low = txt.lower()
            if any(k in low for k in ("cartera", "composici", "instrument",
                                      "inversi", "renta", "estructur", "fibra",
                                      "activo", "valores")):
                href = el.get_attribute("href") or ""
                onclick = el.get_attribute("onclick") or ""
                print(f"  <{tag}> {txt[:70]!r}  href={href[:70]}  oc={onclick[:70]}")


def dump_report(d, cd):
    """For a given report cd, print the series checkboxes: value + nearby label."""
    url = f"https://www.consar.gob.mx/gobmx/aplicativo/siset/Series.aspx?cd={cd}&cdAlt=False"
    d.get(url)
    time.sleep(3)
    print(f"REPORT cd={cd}  TITLE={d.title!r}")
    boxes = d.find_elements(By.XPATH, "//input[@type='checkbox']")
    print(f"  {len(boxes)} checkboxes")
    for b in boxes:
        val = b.get_attribute("value")
        # label: try associated <label for=id>, else parent row text
        bid = b.get_attribute("id")
        label = ""
        if bid:
            labs = d.find_elements(By.XPATH, f"//label[@for='{bid}']")
            if labs:
                label = labs[0].text.strip()
        if not label:
            try:
                label = b.find_element(By.XPATH, "./following::td[1]").text.strip()
            except Exception:
                try:
                    label = b.find_element(By.XPATH, "..").text.strip()
                except Exception:
                    label = "(no label)"
        print(f"    value={val!r:>10}  {label[:70]}")


def main():
    d = init_driver()
    try:
        if len(sys.argv) > 1:
            dump_report(d, sys.argv[1])
        else:
            dump_catalog(d)
    finally:
        d.quit()


if __name__ == "__main__":
    main()
