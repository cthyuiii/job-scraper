"""Find jobs that match your resume with a local LLM, draft applications, then you review and submit."""
import argparse, base64, json, os, re, shutil, sqlite3, subprocess, sys, tomllib, urllib.parse, urllib.request, webbrowser
from pathlib import Path

from jobspy import scrape_jobs
from pypdf import PdfReader

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DB = Path("jobs.db")
DRAFTS = Path("applications")
DEFAULTS = Path(__file__).with_name("prefs.example.toml")  # fills in settings missing from older prefs.toml files
FOLLOWUP_DAYS = 7   # nudge when an application has had no update this long
TRACK = {"a": "applied", "i": "interview", "r": "rejected", "o": "offer"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  url TEXT PRIMARY KEY, site TEXT, title TEXT, company TEXT, location TEXT, description TEXT, max_salary REAL,
  posted TEXT,  -- date the site says it was posted, if it says
  status TEXT DEFAULT 'new',  -- new | filtered | scored | skipped | drafted | applied | interview | rejected | offer
  score INTEGER, why TEXT, gaps TEXT,
  found_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(company, title));  -- same job cross-posted on several sites is stored once
CREATE TABLE IF NOT EXISTS searches(query TEXT PRIMARY KEY, last_run TEXT);"""
STR = {"type": "string"}
# Windows' built-in toast API, reached through Windows PowerShell; the message arrives as an env var
WIN_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>job-scraper</text><text>$([Security.SecurityElement]::Escape($env:JOB_SCRAPER_MSG))</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props)}


def llm(P, prompt, schema):
    body = {"model": P["model"], "messages": [{"role": "user", "content": prompt}], "stream": False,
            "format": schema, "options": {"temperature": 0, "num_ctx": 8192}}  # default ctx silently truncates
    req = urllib.request.Request(f"{OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(json.load(r)["message"]["content"])


def check_ollama(model):
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags") as r:
            names = [m["name"] for m in json.load(r)["models"]]
    except OSError:
        sys.exit(f"Can't reach Ollama at {OLLAMA}. Start it with: ollama serve")
    if (model if ":" in model else model + ":latest") not in names:
        sys.exit(f"Model not installed. Run: ollama pull {model}")


def read_resume(path):
    p = Path(path)
    if p.suffix.lower() not in (".pdf", ".txt", ".md"):
        sys.exit(f"{p.name}: save your resume as a PDF (Word: File > Save As > PDF) or .txt")
    text = "\n".join(pg.extract_text() or "" for pg in PdfReader(p).pages) if p.suffix.lower() == ".pdf" else p.read_text()
    if not text.strip():
        sys.exit(f"No text in {p}. Scanned PDF? Export a text PDF or save it as .txt")
    return text


def suggest_roles(P, resume):
    r = llm(P, f"{resume}\n\nList the 3 job titles this person is best qualified for, as job-board search terms.",
            obj(titles={"type": "array", "items": STR}))
    return r["titles"][:3]


def at(companies, name):
    return any(re.search(rf"\b{re.escape(c)}\b", name or "", re.I) for c in companies)


def fetch(P, queries, db):
    new, max_h = 0, P["max_age_days"] * 24
    for term, company in queries:
        for site in P["sites"]:  # one site per call: jobspy drops every site's results if one raises
            key = f"{site}|{term}|{P['location']}"
            # Results are sorted by relevance, not date, so a fixed window returns the same jobs every day.
            # Search the full window once, then only back to this query's last run.
            last = db.execute("SELECT (julianday('now')-julianday(last_run))*24 FROM searches WHERE query=?", (key,)).fetchone()
            hours = min(int(last[0]) + 24, max_h) if last else max_h
            try:
                df = scrape_jobs(site_name=site, search_term=term, google_search_term=f"{term} jobs near {P['location']}",
                                 location=P["location"], is_remote=P["remote_only"], results_wanted=P["results_per_search"],
                                 hours_old=hours, country_indeed=P["country"], linkedin_fetch_description=True,
                                 enforce_annual_salary=True, proxies=P["proxies"] or None)
            except Exception as e:
                print(f"  {site} '{term}': failed ({e})")
                continue
            for j in df.astype(object).where(df.notna(), None).to_dict("records"):
                if company and not at([company], j["company"]):
                    continue  # company search turned up a different employer
                if P["remote_only"] and site == "indeed" and not j["is_remote"]:
                    continue  # jobspy drops Indeed's remote filter whenever a date filter is set
                cur = db.execute("INSERT OR IGNORE INTO jobs(url,site,title,company,location,description,max_salary,posted) "
                                 "VALUES(?,?,?,?,?,?,?,?)", (j["job_url"], site, j["title"], j["company"], j["location"],
                                 j["description"] or "", j["max_amount"], j["date_posted"] and str(j["date_posted"])[:10]))
                new += cur.rowcount
            db.execute("INSERT OR REPLACE INTO searches VALUES(?, CURRENT_TIMESTAMP)", (key,))
            db.commit()
            print(f"  {site} '{term}': {len(df)} found in the last {hours // 24} days")
    return new


def dropped(P, title, salary):
    t = title.lower()
    return any(k.lower() in t for k in P["exclude_title_keywords"]) or bool(P["min_salary"] and salary and salary < P["min_salary"])


def set_status(db, url, status):
    db.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE url=?", (status, url))
    db.commit()


def score(P, resume, db):
    rows = db.execute("SELECT url,title,company,location,description,max_salary FROM jobs WHERE status='new'").fetchall()
    for i, (url, title, company, loc, desc, sal) in enumerate(rows, 1):
        if dropped(P, title, sal):
            set_status(db, url, "filtered")
            continue
        # resume goes first so Ollama reuses the cached prompt prefix across jobs
        r = llm(P, f"RESUME:\n{resume}\n\nWHAT I WANT:\n{P['about_me']}\n\nJOB: {title} at {company} ({loc})\n{desc[:6000]}\n\n"
                   "Compare this job's day-to-day responsibilities with what this person has actually done, and their wants. "
                   "Score 0-100. Be strict: 80+ only for strong fits. why = one sentence. gaps = missing requirements. "
                   "Address the candidate as 'you'.",
                obj(score={"type": "integer"}, why=STR, gaps={"type": "array", "items": STR}))
        db.execute("UPDATE jobs SET status='scored',score=?,why=?,gaps=?,updated_at=CURRENT_TIMESTAMP WHERE url=?",
                   (r["score"], r["why"], "; ".join(r["gaps"]), url))
        db.commit()
        print(f"  [{i}/{len(rows)}] {r['score']:>3}  {title} — {company}")


def to_review(P, db):
    rows = db.execute("SELECT url,title,company,location,description,score,why,gaps FROM jobs WHERE status='scored' "
                      "AND score>=? AND COALESCE(posted, found_at) > date('now', ?) ORDER BY score DESC",
                      (P["min_score"], f"-{P['max_age_days']} days")).fetchall()
    return sorted(rows, key=lambda r: not at(P["companies"], r[2]))[:P["top_n"]]  # your companies first, then by score


def followups_due(db):
    return db.execute("SELECT count(*) FROM jobs WHERE status='applied' AND updated_at < datetime('now', ?)",
                      (f"-{FOLLOWUP_DAYS} days",)).fetchone()[0]


def review(P, resume, db):
    rows = to_review(P, db)
    if not rows:
        print("Nothing new to review.")
        return
    DRAFTS.mkdir(exist_ok=True)
    for url, title, company, loc, desc, sc, why, gaps in rows:
        star = "★ " if at(P["companies"], company) else ""
        print(f"\n[{sc}] {star}{title} — {company} ({loc})\n{url}\nwhy:  {why}\ngaps: {gaps or '-'}")
        a = input("[d]raft application / [s]kip / [q]uit? ").strip().lower()
        if a == "q":
            return
        if a != "d":
            set_status(db, url, "skipped")
            continue
        r = llm(P, f"RESUME:\n{resume}\n\nJOB: {title} at {company}\n{desc[:6000]}\n\n"
                   "Never claim a skill or experience that is not in the resume. No placeholders like [Name]. "
                   "Write (1) cover_letter: under 200 words, specific to this job. "
                   "(2) linkedin_note: under 200 characters, starting with 'Hi,', to someone at this company, mentioning the role and one relevant strength.",
                obj(cover_letter=STR, linkedin_note=STR))
        people = "https://www.linkedin.com/search/results/people/?keywords=" + urllib.parse.quote(
            f'"{company}" (recruiter OR "talent acquisition" OR manager OR director)')
        f = DRAFTS / (re.sub(r"\W+", "-", f"{company}-{title}").strip("-").lower()[:80] + ".md")
        f.write_text(f"# {title} — {company}\n\n{url}\n\n## Cover letter\n\n{r['cover_letter']}\n\n"
                     f"## LinkedIn note ({len(r['linkedin_note'])} chars)\n\n{r['linkedin_note']}\n\nFind people: {people}\n")
        print(f"\n{f.read_text()}\nSaved to {f}. Edit it before sending.")
        if input("Open the job page and LinkedIn people search so you can apply? [y/n] ").strip().lower() == "y":
            webbrowser.open(url)
            webbrowser.open(people)
        applied = input("Applied? [y]es / [enter] later (mark it with --track) ").strip().lower() == "y"
        set_status(db, url, "applied" if applied else "drafted")


def track(db):
    rows = db.execute("SELECT url,title,company,status,CAST(julianday('now')-julianday(updated_at) AS INT) FROM jobs "
                      "WHERE status IN ('drafted','applied','interview') ORDER BY updated_at").fetchall()
    if not rows:
        print("Nothing to track yet. Draft an application first.")
    for url, title, company, status, days in rows:
        due = "  <- follow up" if status == "applied" and days >= FOLLOWUP_DAYS else ""
        print(f"\n{title} — {company}\n{url}\n{status} {days} days ago{due}")
        a = input("[a]pplied or followed up / [i]nterview / [r]ejected / [o]ffer / [enter] no change / [q]uit? ").strip().lower()
        if a == "q":
            return
        if a in TRACK:
            set_status(db, url, TRACK[a])


def notify(msg):
    print(msg)
    if sys.platform == "darwin":  # message goes in as argv so quotes in job titles can't break the script
        subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display notification (item 1 of argv) with title "job-scraper"', "-e", "end run", msg])
    elif sys.platform == "win32":  # encoded so the script survives Windows command-line quoting
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", base64.b64encode(WIN_TOAST.encode("utf-16-le")).decode()],
                       env={**os.environ, "JOB_SCRAPER_MSG": msg}, creationflags=subprocess.CREATE_NO_WINDOW)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "job-scraper", msg])


def run(a, db):
    if not Path(a.prefs).exists():
        sys.exit(f"Copy prefs.example.toml to {a.prefs} and edit it first.")
    P = tomllib.loads(DEFAULTS.read_text()) | tomllib.loads(Path(a.prefs).read_text())
    check_ollama(P["model"])
    resume = read_resume(a.resume)
    if not a.review_only:
        if a.rescore:
            db.execute("UPDATE jobs SET status='new' WHERE status IN ('scored','filtered') "
                       "AND COALESCE(posted, found_at) > date('now', ?)", (f"-{P['max_age_days']} days",))
        terms = P["search_terms"] or suggest_roles(P, resume)
        # your companies go first, so they're searched before any rate limit kicks in
        queries = [(f"{c} {t}", c) for c in P["companies"] for t in terms] + [(t, None) for t in terms]
        print("Searching:", ", ".join(terms), "| companies:", ", ".join(P["companies"]) or "any")
        print(f"{fetch(P, queries, db)} new postings. Scoring...")
        score(P, resume, db)
    due = followups_due(db)
    if a.notify:
        jobs = to_review(P, db)
        msg = [f"{len(jobs)} jobs to review, top: [{jobs[0][5]}] {jobs[0][1]} at {jobs[0][2]}"] if jobs else []
        msg += [f"{due} applications need a follow-up"] if due else []
        if msg:
            notify(". ".join(msg))
        return
    if due:
        print(f"{due} applications have had no update for {FOLLOWUP_DAYS}+ days. Run with --track to follow up.")
    review(P, resume, db)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("resume", nargs="?", help="your resume, .pdf or .txt")
    ap.add_argument("--prefs", default="prefs.toml")
    ap.add_argument("--review-only", action="store_true", help="skip searching, review saved matches")
    ap.add_argument("--rescore", action="store_true", help="re-score recent jobs after editing your resume or prefs")
    ap.add_argument("--notify", action="store_true", help="search and score, then send a desktop notification (for scheduled runs)")
    ap.add_argument("--track", action="store_true", help="mark applications applied / interview / rejected / offer (no resume needed)")
    a = ap.parse_args()
    if sys.stdout:  # None under pythonw (Windows scheduled runs)
        sys.stdout.reconfigure(line_buffering=True)  # scheduled runs write to a log; show progress as it happens
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    if a.track:
        return track(db)
    if not a.resume:
        ap.error("give your resume file, e.g. main.py resume.pdf")
    try:
        run(a, db)
    except (Exception, SystemExit) as e:
        if a.notify:  # a scheduled run nobody is watching must not fail silently
            notify(f"Run failed: {e}")
        raise


if __name__ == "__main__":
    main()
