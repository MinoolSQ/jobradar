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
    # struka
    "python", "data engineer", "data inzenjer", "podaci", "etl",
    "databricks", "spark", "airflow", "backend", "sql", "aws",
    "data platform", "kubernetes", "fastapi", "data analyst",
    "devops", "junior", "cloud", "linux",
    # premoscavanje dok se ne nadje posao u struci
    "it tehnicar", "sistem administrator", "administrator", "it podrska",
    "help desk", "tehnicka podrska", "it support", "serviser", "mrezni",
    "windows", "racunari",
]

# Infostud vraca 30 oglasa po strani, sortirano po relevantnosti.
INFOSTUD_PAGE = 30
INFOSTUD_MAX_PAGES = 6

# Oglas van IT kategorije prolazi ako mu naslov lici na IT posao (tehnicar u apoteci
# i slicno stoji pod "Ostalo" ili "Administracija").
IT_TITLE = re.compile(
    r"(^|\W)(it|ict|informati\w*|help ?desk|service ?desk|sysadmin|"
    r"sistem\w* administrator\w*|system administrator|administrator\w* sistem\w*|"
    r"mre[zž]n\w*|network|devops|linux|windows|ra[cč]unar\w*|computer|"
    r"tehni[cč]ka podr[sš]ka|it support|support engineer|noc)(\W|$)",
    re.I,
)

# Sekcije HelloWorld-a. Prazan string znaci sve IT kategorije.
HELLOWORLD_CATS = [""]

# Filter vreme_postavljanja na HelloWorld-u nudi "danas, 2, 3 i 7 dana", ali se sajt ne
# drzi toga (proba 04.10.2026: 2 vrati 30, 3 vrati 1, 7 vrati 23, 1 se ignorise), lista
# staje na 30 oglasa, a page=2 vrati istu stranu. Zato se cita lista bez filtera (nosi
# najnovije) i sve tri vrednosti, pa se spoje po ID-u, a tacan datum se posle proveri na
# stranici oglasa. Prazan string je lista bez filtera.
HELLOWORLD_WINDOWS = ["", "2", "3", "7"]

# Remote bordovi vracaju stotine oglasa, pa se filtriraju po ovim pojmovima.
REMOTE_KEYWORDS = [
    "python", "data engineer", "data engineering", "etl", "elt", "spark",
    "databricks", "airflow", "snowflake", "dbt", "backend", "back-end",
    "platform engineer", "analytics engineer", "data platform", "pipeline",
    "devops", "sysadmin", "site reliability", "linux", "support engineer", "junior",
]

# Koliko dugo se pamti kad je oglas prvi put vidjen.
SEEN_KEEP_DAYS = 45

# Dijagnostika o tome sta sajtovi vracaju; puni se samo uz --debug-out.
DEBUG = None

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

def infostud_search(query, page=1, extra=""):
    """Rezultati pretrage stoje kao JSON u __NEXT_DATA__ bloku stranice."""
    url = "https://poslovi.infostud.com/oglasi-za-posao-" + slugify(query)
    params = []
    if page > 1:
        params.append("page=%d" % page)
    if extra:
        params.append(extra)
    if params:
        url += "?" + "&".join(params)
    html_page = fetch(url)
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_page, re.S)
    if not match:
        raise RuntimeError("nema __NEXT_DATA__ na %s" % url)
    props = json.loads(match.group(1))["props"]["pageProps"]
    results = props.get("initialSearchResults")
    if DEBUG is not None and "infostud_meta" not in DEBUG:
        # Jednom po pokretanju: sta jos stoji uz rezultate, da se vidi kako sajt sortira
        # i da li ima parametre za stranu ili datum.
        meta = {k: v for k, v in (results or {}).items() if k != "jobs"}
        jobs_meta = {k: (len(v) if isinstance(v, list) else v)
                     for k, v in ((results or {}).get("jobs") or {}).items()}
        DEBUG["infostud_meta"] = {
            "url": url,
            "pageProps_kljucevi": sorted(props.keys()),
            "results_bez_jobs": json.dumps(meta, ensure_ascii=False)[:2500],
            "jobs_kljucevi": jobs_meta,
            "prvi_oglas_kljucevi": sorted((results or {}).get("jobs", {}).get("primary", [{}])[0].keys())
            if results else None,
        }
    if not results:
        return [], {}
    meta = {
        "total": results.get("totalPrimaryItems"),
        "page": results.get("page"),
        "sort": results.get("sort"),
        "params": {k: v for k, v in (results.get("params") or {}).items()
                   if v is not None and k != "__typename"},
    }
    return results["jobs"]["primary"], meta


# Kandidati za URL parametar kojim Infostud sortira ili filtrira po datumu. Sajt u
# odgovoru vraca parsirane parametre, pa proba vidi koji je prepoznat.
INFOSTUD_PROBES = [
    "sort=date", "sort=newest", "sort=new", "sort=datum", "sort=latest", "sort=DATE",
    "sortiranje=datum", "orderBy=date", "timeOfPosting=3", "time_of_posting=3",
    "vreme_postavljanja=3", "period=3", "dani=3", "days=3",
    "onlineAfterDate=2026-10-01", "online_after_date=2026-10-01", "from=2026-10-01",
]


def infostud_probe():
    for extra in INFOSTUD_PROBES:
        try:
            batch, meta = infostud_search("python", 1, extra)
            dates = [d for d in (parse_sr_date(j.get("onlineViewDate") or "") for j in batch) if d]
            DEBUG.setdefault("infostud_probe", []).append({
                "extra": extra, "oglasa": len(batch), "meta": meta,
                "redosled": [d.isoformat() for d in dates[:10]],
            })
        except Exception as exc:
            DEBUG.setdefault("infostud_probe", []).append({"extra": extra, "greska": str(exc)})


def infostud_query(query, cutoff):
    """
    Sve strane jedne pretrage. Sajt sortira po relevantnosti, ne po datumu, pa svez oglas
    moze da bude na bilo kojoj strani; cita se dok ima strana, do limita. Ako sajt
    ignorise parametar strane, druga strana vrati iste oglase i petlja stane.
    """
    found, seen, pages, stop, total = [], set(), 0, "limit", None
    # Sajt prepoznaje onlineAfterDate i vraca samo oglase od tog datuma, pa je obicno
    # dovoljna jedna strana. Datum se svejedno proverava i po oglasu.
    since = "onlineAfterDate=%s" % cutoff.isoformat()
    for page in range(1, INFOSTUD_MAX_PAGES + 1):
        batch, meta = infostud_search(query, page, since)
        total = meta.get("total") if total is None else total
        fresh_ids = [str(j.get("id")) for j in batch if str(j.get("id")) not in seen]
        if not fresh_ids:
            stop = "ista strana" if batch else "kraj"
            break
        pages += 1
        seen.update(fresh_ids)
        found.extend(batch)
        dates = [d for d in (parse_sr_date(j.get("onlineViewDate") or "") for j in batch) if d]
        if DEBUG is not None:
            DEBUG.setdefault("infostud_strane", []).append({
                "upit": query, "strana": page, "oglasa": len(batch), "novih_id": len(fresh_ids),
                "svezih": sum(1 for d in dates if d >= cutoff), "total": total,
            })
        if len(batch) < INFOSTUD_PAGE or (total is not None and len(seen) >= total):
            stop = "kraj"
            break
    return found, pages, stop


def looks_like_it(job):
    category = (job.get("primaryCategory") or {}).get("name", "")
    if category == "IT" or job.get("itTags"):
        return True
    return bool(IT_TITLE.search(job.get("title") or ""))


def collect_infostud(cutoff, stats):
    jobs, errors = {}, []
    if DEBUG is not None:
        infostud_probe()
    for query in INFOSTUD_QUERIES:
        try:
            found, pages, stop = infostud_query(query, cutoff)
        except Exception as exc:
            errors.append("infostud %s: %s" % (query, exc))
            continue
        stats[query] = {"vraceno": len(found), "strane": pages, "stop": stop}
        for job in found:
            it_tags = job.get("itTags") or []
            if not looks_like_it(job):
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


def collect_helloworld(cutoff, open_pages, char_limit, previous):
    """
    Lista oglasa ne nosi datum objave i staje na 30 oglasa bez paginacije, pa se citaju
    sve vrednosti filtera i spajaju, a tacan datum se procita iz JSON-LD bloka na
    stranici svakog oglasa. Oglasi koje je prethodno pokretanje vec otvorilo se ne
    otvaraju ponovo.
    """
    jobs, errors = {}, []
    if DEBUG is not None:
        helloworld_probe()
    lists = [(cat, window) for cat in HELLOWORLD_CATS for window in HELLOWORLD_WINDOWS]
    for cat, window in lists:
        params = {}
        if window:
            params["vreme_postavljanja"] = window
        if cat:
            params["cat"] = cat
        url = "https://www.helloworld.rs/oglasi-za-posao"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            page = fetch(url)
        except Exception as exc:
            errors.append("helloworld %s/%s: %s" % (cat or "sve", window or "bez filtera", exc))
            continue
        cards = list(HW_CARD.finditer(page))
        if DEBUG is not None:
            DEBUG.setdefault("helloworld", []).append({
                "url": url, "karaktera": len(page), "kartica": len(cards)})
        for index, card in enumerate(cards):
            if card.group("id") in jobs:
                continue
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
                "posted_window": "helloworld filter %s" % (window or "bez filtera"),
                "expires": clean(expires.group(1)) if expires else None,
                "salary": None,
                "url": "https://www.helloworld.rs" + href,
                "summary": text[:400],
                "matched": ["helloworld"],
            }

    if not jobs and not errors:
        errors.append("helloworld: nijedna kartica ni na jednoj listi, markup se verovatno promenio")
    if not open_pages:
        return list(jobs.values()), errors

    svezi = []
    for job in jobs.values():
        old = previous.get(job["id"])
        if old and old.get("details") and old.get("posted"):
            body, posted = old["details"], old["posted"]
        else:
            try:
                body, posted = page_data(job["url"], char_limit)
            except Exception as exc:
                job["details_error"] = str(exc)
                svezi.append(job)  # bez datuma je bolje pustiti oglas nego ga izgubiti
                continue
        job["details"] = body
        if posted:
            job["posted"] = posted
            job.pop("posted_window", None)
            if datetime.strptime(posted, "%Y-%m-%d").date() < cutoff:
                continue
        svezi.append(job)
    return svezi, errors


HW_PROBES = ["", "vreme_postavljanja=2", "vreme_postavljanja=2&strana=2",
             "vreme_postavljanja=2&p=2", "vreme_postavljanja=2&offset=30",
             "vreme_postavljanja=2&start=30"]


def helloworld_probe():
    """Sta znace vrednosti filtera, koji parametri postoje u linkovima, ima li paginacije."""
    for params in HW_PROBES:
        url = "https://www.helloworld.rs/oglasi-za-posao" + ("?" + params if params else "")
        try:
            page = fetch(url)
            ids = sorted(set(re.findall(r'data-job-id="(\d+)"', page)))
            info = {
                "params": params, "karaktera": len(page), "razlicitih_id": len(ids),
                "kartica": len(HW_CARD.findall(page)),
                "prvih_id": ids[:6], "poslednjih_id": ids[-4:],
                "param_imena": sorted(set(re.findall(r'[?&;]([a-zA-Z_]+)=', page)))[:60],
            }
            if not params:
                spots = [m.start() for m in re.finditer(r"vreme_postavljanja", page)][:12]
                info["filter_isecci"] = [
                    clean(re.sub(r"<[^>]+>", " ", page[s - 200:s + 600])) for s in spots]
                info["opcije"] = re.findall(
                    r'(?:name="vreme_postavljanja"[^>]*>|vreme_postavljanja=)(\d+)[^<]{0,200}?>([^<]{1,80})<',
                    page)[:20]
            DEBUG.setdefault("helloworld_probe", []).append(info)
        except Exception as exc:
            DEBUG.setdefault("helloworld_probe", []).append({"params": params, "greska": str(exc)})


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
LD_DATE = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def page_data(url, limit):
    """Sa stranice oglasa vraca goli tekst i datum objave, ako ga sajt daje."""
    page = fetch(url, tries=2)
    posted = LD_DATE.search(page)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = clean(re.sub(r"<[^>]+>", " ", body))
    for marker in BODY_MARKERS:
        spot = text.find(marker)
        if spot > 0:
            text = text[spot + len(marker):].strip()
            break
    return text[:limit], posted.group(1) if posted else None


def add_details(jobs, how_many, char_limit, previous):
    """Rutina koja ovo cita nema pristup internetu, pa uslovi moraju da udju u JSON."""
    done = 0
    for job in jobs:
        if job.get("details") is not None or not job.get("url"):
            continue  # HelloWorld je svoje stranice vec otvorio
        if job["source"] != "infostud":
            continue
        old = previous.get(job["id"])
        if old and old.get("details"):
            job["details"] = old["details"]
            continue
        if done >= how_many:
            break
        try:
            job["details"], _ = page_data(job["url"], char_limit)
        except Exception as exc:
            job["details_error"] = str(exc)
        done += 1
    return done


# ------------------------------------------------------- pamcenje vidjenog

def load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def previous_jobs(out_path):
    """Oglasi iz prethodnog rezultata, po ID-u, da se njihov tekst ne skida ponovo."""
    data = load_json(out_path) or {}
    return {j["id"]: j for j in data.get("jobs", []) if isinstance(j, dict) and "id" in j}


def mark_first_seen(jobs, seen_path, now):
    """
    Upisuje u svaki oglas kad ga je skripta prvi put videla, iz data/videno.json.
    Rutina po tome zna sta je novo od poslednjeg mejla, bez obzira na to koliko puta
    dnevno Action radi i koliko kasni.
    """
    seen = load_json(seen_path)
    if not isinstance(seen, dict):
        seen = {}
    stamp = now.isoformat(timespec="seconds")
    for job in jobs:
        first = seen.get(job["id"])
        if not first:
            first = seen[job["id"]] = stamp
        job["first_seen"] = first
    keep_from = (now - timedelta(days=SEEN_KEEP_DAYS)).isoformat(timespec="seconds")
    seen = {k: v for k, v in seen.items() if v >= keep_from}
    with Path(seen_path).open("w", encoding="utf-8") as handle:
        json.dump(seen, handle, indent=0, sort_keys=True)
    return sum(1 for j in jobs if j["first_seen"] == stamp)


# ------------------------------------------------------------------- glavni

def main():
    parser = argparse.ArgumentParser(description="Skuplja sveze IT oglase.")
    parser.add_argument("--days", type=int, default=1, help="koliko dana unazad")
    parser.add_argument("--out", default="oglasi.json", help="izlazni JSON fajl")
    parser.add_argument("--sources", default="infostud,helloworld,remoteok,wwr")
    parser.add_argument("--details", action=argparse.BooleanOptionalAction, default=True,
                        help="da li da skine i tekst svakog oglasa")
    parser.add_argument("--details-max", type=int, default=60,
                        help="najvise oglasa cija se stranica otvara u jednom pokretanju")
    parser.add_argument("--details-chars", type=int, default=3500,
                        help="koliko karaktera teksta oglasa se cuva")
    parser.add_argument("--seen", default=None,
                        help="fajl sa datumima prvog vidjenja, podrazumevano videno.json pored izlaza")
    parser.add_argument("--debug-out", default=None,
                        help="JSON fajl sa dijagnostikom o tome sta sajtovi vracaju")
    args = parser.parse_args()

    global DEBUG
    if args.debug_out:
        DEBUG = {}

    now = datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=args.days)
    wanted = {s.strip() for s in args.sources.split(",")}
    out_path = Path(args.out)
    seen_path = Path(args.seen) if args.seen else out_path.parent / "videno.json"
    previous = previous_jobs(out_path)

    jobs, errors, infostud_stats = [], [], {}
    plan = [
        ("infostud", lambda: collect_infostud(cutoff, infostud_stats)),
        ("helloworld", lambda: collect_helloworld(
            cutoff, args.details, args.details_chars, previous)),
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

    if out_path.parent != Path(""):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    new_count = mark_first_seen(unique, seen_path, now)
    # Novi oglasi idu prvi, da njihov tekst sigurno stane u limit otvaranja.
    unique.sort(key=lambda j: j["first_seen"], reverse=True)

    if args.details and unique:
        opened = add_details(unique, args.details_max, args.details_chars, previous)
        print("%-14s %3d otvorenih oglasa" % ("detalji", opened), file=sys.stderr)

    saturated = sorted(q for q, s in infostud_stats.items() if s["stop"] == "limit")
    if saturated:
        errors.append("infostud: pretrage %s su napunile svih %d strana, mozda ima jos"
                      % (", ".join(saturated), INFOSTUD_MAX_PAGES))

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": args.days,
        "cutoff": cutoff.isoformat(),
        "count": len(unique),
        "new_count": new_count,
        "errors": errors,
        "infostud_queries": infostud_stats,
        "jobs": unique,
    }
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    if DEBUG is not None:
        with Path(args.debug_out).open("w", encoding="utf-8") as handle:
            json.dump(DEBUG, handle, ensure_ascii=False, indent=1)

    print("ukupno %d jedinstvenih oglasa (%d prvi put vidjenih), upisano u %s"
          % (len(unique), new_count, args.out), file=sys.stderr)
    for problem in errors:
        print("greska: %s" % problem, file=sys.stderr)
    json.dump(payload, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
