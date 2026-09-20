#!/usr/bin/env python3
"""
jobradar: skuplja sveze IT oglase sa Infostuda, HelloWorld-a i remote bordova.

Samo standardna biblioteka, bez pip instalacije, da moze da se pokrene u bilo kom
sandboxu. Ispis je JSON na stdout, a kratak pregled ide na stderr.

    python fetch_jobs.py --days 1 --out oglasi.json
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
TIMEOUT = 45

# Kljucne reci za pretragu Infostuda. Svaka je jedna pretraga.
INFOSTUD_QUERIES = [
    "python", "data engineer", "data inzenjer", "podaci", "etl",
    "databricks", "spark", "airflow", "backend", "sql", "aws",
    "data platform", "kubernetes", "fastapi", "data analyst",
]

# Sekcije HelloWorld-a. Prazan string znaci sve IT kategorije.
HELLOWORLD_CATS = [""]

# Remote bordovi vracaju stotine oglasa, pa se filtriraju po ovim pojmovima.
REMOTE_KEYWORDS = [
    "python", "data engineer", "data engineering", "etl", "elt", "spark",
    "databricks", "airflow", "snowflake", "dbt", "backend", "back-end",
    "platform engineer", "analytics engineer", "data platform", "pipeline",
]

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]


def fetch(url, tries=3):
    """Skida stranicu kao tekst, sa par pokusaja na mreznu gresku."""
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "sr,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:
            last = exc
    raise RuntimeError("ne mogu da skinem %s: %s" % (url, last))


def clean(text):
    """Cisti HTML entitete i visak razmaka."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def slugify(term):
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")


def parse_sr_date(value):
    """Datum oblika 14.09.2026 pretvara u date, ili vraca None."""
    try:
        return datetime.strptime(value.strip().rstrip("."), "%d.%m.%Y").date()
    except Exception:
        return None


# ---------------------------------------------------------------- Infostud

def infostud_search(query):
    """Rezultati pretrage stoje kao JSON u __NEXT_DATA__ bloku stranice."""
    url = "https://poslovi.infostud.com/oglasi-za-posao-" + slugify(query)
    page = fetch(url)
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if not match:
        raise RuntimeError("nema __NEXT_DATA__ na %s" % url)
    results = json.loads(match.group(1))["props"]["pageProps"].get("initialSearchResults")
    if not results:
        return []
    return results["jobs"]["primary"]


def collect_infostud(cutoff):
    jobs, errors = {}, []
    for query in INFOSTUD_QUERIES:
        try:
            found = infostud_search(query)
        except Exception as exc:
            errors.append("infostud %s: %s" % (query, exc))
            continue
        for job in found:
            category = (job.get("primaryCategory") or {}).get("name", "")
            it_tags = job.get("itTags") or []
            if category != "IT" and not it_tags:
                continue  # pretraga po kljucnoj reci vuce i proizvodnju i prodaju
            posted = parse_sr_date(job.get("onlineViewDate") or "")
            if posted and posted < cutoff:
                continue
            job_id = str(job.get("id"))
            record = jobs.setdefault(job_id, {
                "source": "infostud",
                "id": job_id,
                "title": clean(job.get("title")),
                "company": clean(job.get("companyName")),
                "location": clean(job.get("location")),
                "remote": bool(job.get("workFromHome")),
                "hybrid": bool(job.get("hybridWork")),
                "tags": it_tags,
                "posted": posted.isoformat() if posted else None,
                "expires": job.get("expirationDate"),
                "salary": job.get("salary"),
                "url": job.get("url"),
                "summary": clean((job.get("jobSummary") or {}).get("summary")),
                "matched": [],
            })
            record["matched"].append(query)
    return list(jobs.values()), errors


# -------------------------------------------------------------- HelloWorld

HW_CARD = re.compile(
    r'<a data-job-id="(?P<id>\d+)" href="(?P<href>/posao/[^"?]+)[^"]*"[^>]*'
    r'class="__ga4_job_title[^"]*">\s*(?P<title>.*?)\s*</a>',
    re.S,
)


def collect_helloworld(days):
    """HelloWorld ima filter po datumu postavljanja, pa je svezina resena na serveru."""
    window = "today" if days <= 1 else str(min(days, 7))
    jobs, errors = {}, []
    for cat in HELLOWORLD_CATS:
        params = {"vreme_postavljanja": window}
        if cat:
            params["cat"] = cat
        url = "https://www.helloworld.rs/oglasi-za-posao?" + urllib.parse.urlencode(params)
        try:
            page = fetch(url)
        except Exception as exc:
            errors.append("helloworld %s: %s" % (cat or "sve", exc))
            continue
        cards = list(HW_CARD.finditer(page))
        for index, card in enumerate(cards):
            # Kartica se zavrsava tamo gde pocinje sledeca, da tagovi ne pobegnu u susedni oglas.
            end = cards[index + 1].start() if index + 1 < len(cards) else card.end() + 6000
            body = page[card.end():end]
            text = clean(re.sub(r"<[^>]+>", " ", body))
            company = re.search(r'__ga4_job_company[^>]*>\s*([^<]+?)\s*</a>', body)
            location = re.search(r'la-map-marker.*?<p[^>]*>\s*(.*?)\s*</p>', body, re.S)
            expires = re.search(r'la-clock.*?<p[^>]*>\s*(.*?)\s*</p>', body, re.S)
            tags = re.findall(r'<a href="/oglasi-za-posao/([a-z0-9\-]+)"[^>]*?__ga4_job_tech_tag', body)
            href = card.group("href")
            place = clean(location.group(1)) if location else ""
            jobs[card.group("id")] = {
                "source": "helloworld",
                "id": card.group("id"),
                "title": clean(card.group("title")),
                # Ako firma nema profil na sajtu, ime se izvlaci iz putanje oglasa.
                "company": clean(company.group(1)) if company else url_company(href),
                "location": place,
                "remote": "remote" in place.lower() or "od kuće" in place.lower(),
                "hybrid": "hibrid" in place.lower(),
                "tags": [t.replace("-", " ") for t in tags],
                "posted": None,
                "posted_window": "danas" if window == "today" else "poslednjih %s dana" % window,
                "expires": clean(expires.group(1)) if expires else None,
                "salary": None,
                "url": "https://www.helloworld.rs" + href,
                "summary": text[:400],
                "matched": ["helloworld"],
            }
    return list(jobs.values()), errors


def url_company(href):
    """/posao/Naziv-posla/Ime-firme/12345 -> Ime firme"""
    parts = [p for p in href.split("/") if p]
    if len(parts) >= 3:
        return clean(urllib.parse.unquote(parts[2]).replace("-", " "))
    return ""


# ------------------------------------------------------------ remote bordovi

def is_relevant(text):
    low = text.lower()
    return any(word in low for word in REMOTE_KEYWORDS)


def collect_remoteok(cutoff):
    try:
        data = json.loads(fetch("https://remoteok.com/api"))
    except Exception as exc:
        return [], ["remoteok: %s" % exc]
    jobs = []
    for item in data:
        if not isinstance(item, dict) or "position" not in item:
            continue  # prvi element liste je pravno obavestenje, ne oglas
        try:
            posted = datetime.fromtimestamp(int(item.get("epoch", 0)), timezone.utc).date()
        except Exception:
            continue
        if posted < cutoff:
            continue
        tags = [str(t) for t in (item.get("tags") or [])]
        blob = " ".join([item.get("position", ""),
                         (item.get("description") or "")[:600],
                         " ".join(tags)])
        if not is_relevant(blob):
            continue
        salary = None
        if item.get("salary_min"):
            salary = "%s-%s USD" % (item.get("salary_min"), item.get("salary_max"))
        jobs.append({
            "source": "remoteok",
            "id": "remoteok-" + str(item.get("id")),
            "title": clean(item.get("position")),
            "company": clean(item.get("company")),
            "location": clean(item.get("location")) or "remote",
            "remote": True,
            "hybrid": False,
            "tags": tags[:12],
            "posted": posted.isoformat(),
            "expires": None,
            "salary": salary,
            "url": item.get("url") or item.get("apply_url"),
            "summary": clean(re.sub(r"<[^>]+>", " ", item.get("description") or ""))[:400],
            "matched": ["remoteok"],
        })
    return jobs, []


def collect_wwr(cutoff):
    jobs, errors = [], []
    for feed in WWR_FEEDS:
        try:
            xml = fetch(feed)
        except Exception as exc:
            errors.append("wwr %s: %s" % (feed.rsplit("/", 1)[-1], exc))
            continue
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):

            def field(name, blob=item):
                found = re.search(r"<%s>(.*?)</%s>" % (name, name), blob, re.S)
                if not found:
                    return ""
                return clean(re.sub(r"<!\[CDATA\[|\]\]>", "", found.group(1)))

            title = field("title")
            if not is_relevant(title + " " + field("description")[:600]):
                continue
            posted, raw_date = None, field("pubDate")
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    posted = datetime.strptime(raw_date, fmt).date()
                    break
                except Exception:
                    continue
            if posted and posted < cutoff:
                continue
            company, _, role = title.partition(":")
            link = field("link")
            jobs.append({
                "source": "weworkremotely",
                "id": "wwr-" + (link.rstrip("/").rsplit("/", 1)[-1] or title[:40]),
                "title": clean(role or title),
                "company": clean(company),
                "location": field("region") or "remote",
                "remote": True,
                "hybrid": False,
                "tags": [],
                "posted": posted.isoformat() if posted else None,
                "expires": None,
                "salary": None,
                "url": link,
                "summary": clean(re.sub(r"<[^>]+>", " ", field("description")))[:400],
                "matched": ["weworkremotely"],
            })
    return jobs, errors


# ------------------------------------------------- tekst pojedinacnog oglasa

# Sve pre ovih reci je navigacija sajta, ne oglas.
BODY_MARKERS = ("Tekst oglasa", "Oglasi za posao")


def page_text(url, limit):
    """Skida stranicu oglasa i vraca goli tekst, bez menija i podnozja."""
    page = fetch(url, tries=2)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = clean(re.sub(r"<[^>]+>", " ", body))
    for marker in BODY_MARKERS:
        spot = text.find(marker)
        if spot > 0:
            text = text[spot + len(marker):].strip()
            break
    return text[:limit]


def add_details(jobs, how_many, char_limit):
    """Rutina koja ovo cita nema pristup internetu, pa uslovi moraju da udju u JSON."""
    done = 0
    for job in jobs:
        if done >= how_many:
            break
        if job["source"] not in ("infostud", "helloworld") or not job.get("url"):
            continue
        try:
            job["details"] = page_text(job["url"], char_limit)
        except Exception as exc:
            job["details_error"] = str(exc)
        done += 1
    return done


# ------------------------------------------------------------------- glavni

def main():
    parser = argparse.ArgumentParser(description="Skuplja sveze IT oglase.")
    parser.add_argument("--days", type=int, default=1, help="koliko dana unazad")
    parser.add_argument("--out", default="oglasi.json", help="izlazni JSON fajl")
    parser.add_argument("--sources", default="infostud,helloworld,remoteok,wwr")
    parser.add_argument("--details", action=argparse.BooleanOptionalAction, default=True,
                        help="da li da skine i tekst svakog oglasa")
    parser.add_argument("--details-max", type=int, default=40,
                        help="najvise oglasa cija se stranica otvara")
    parser.add_argument("--details-chars", type=int, default=3500,
                        help="koliko karaktera teksta oglasa se cuva")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=args.days)
    wanted = {s.strip() for s in args.sources.split(",")}

    jobs, errors = [], []
    plan = [
        ("infostud", lambda: collect_infostud(cutoff)),
        ("helloworld", lambda: collect_helloworld(args.days)),
        ("remoteok", lambda: collect_remoteok(cutoff)),
        ("wwr", lambda: collect_wwr(cutoff)),
    ]
    for name, run in plan:
        if name not in wanted:
            continue
        try:
            found, source_errors = run()
        except Exception as exc:
            errors.append("%s: %s" % (name, exc))
            continue
        errors.extend(source_errors)
        jobs.extend(found)
        print("%-14s %3d oglasa" % (name, len(found)), file=sys.stderr)

    # Infostud i HelloWorld dele bazu i ID-jeve, pa isti oglas moze da dodje dvaput.
    unique, seen = [], set()
    for job in sorted(jobs, key=lambda j: (j["source"] != "infostud", j["title"])):
        if job["id"] in seen:
            continue
        seen.add(job["id"])
        unique.append(job)

    if args.details and unique:
        opened = add_details(unique, args.details_max, args.details_chars)
        print("%-14s %3d otvorenih oglasa" % ("detalji", opened), file=sys.stderr)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": args.days,
        "cutoff": cutoff.isoformat(),
        "count": len(unique),
        "errors": errors,
        "jobs": unique,
    }
    out_path = Path(args.out)
    if out_path.parent != Path(""):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)

    print("ukupno %d jedinstvenih oglasa, upisano u %s" % (len(unique), args.out),
          file=sys.stderr)
    for problem in errors:
        print("greska: %s" % problem, file=sys.stderr)
    json.dump(payload, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
