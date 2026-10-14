"""Every job the scan found, its score, and whether it's in or out. Run from this folder: .venv/bin/streamlit run app.py"""
import re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import tomlkit
from jobspy.model import Country

from main import WORK_TYPES, at, connect, country_code, dropped, load_prefs, off_type

PREFS = Path("prefs.toml")
LOG = Path("scan.log")
FITS = {"In": "green", "Out": "gray", "Excluded": "orange", "Not scored": "blue"}  # fit -> theme colour
TAGS = FITS | {"Your company": "violet"}
SITES = {"indeed": "Indeed", "linkedin": "LinkedIn", "zip_recruiter": "ZipRecruiter", "glassdoor": "Glassdoor",
         "google": "Google Jobs", "bayt": "Bayt", "naukri": "Naukri", "bdjobs": "bdjobs"}
COUNTRIES = dict(sorted(((c.value[0].split(",")[0], c.value[0].split(",")[-1].title()) for c in Country
                         if c.name not in ("US_CANADA", "WORLDWIDE")), key=lambda c: c[1]))
US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "District of Columbia",
             "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
             "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
             "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
             "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
             "Washington", "West Virginia", "Wisconsin", "Wyoming"]
SORTS = {"Score": (["mine", "score"], [False, False]),  # your companies first, then highest score
         "Date posted": (["posted", "score"], [False, False]),
         "Date scored": (["scored_at", "score"], [False, False]),
         "Country": (["country", "score"], [True, False])}
SUGGEST_INCLUDE = ["intern", "internship", "placement", "graduate", "new grad", "entry level", "junior", "trainee"]
SUGGEST_EXCLUDE = ["senior", "sr.", "lead", "principal", "staff", "manager", "director", "head of"]
SEARCH_STEP = re.compile(r"^\[search (\d+)/(\d+)\] (\S+) '(.*)'")  # printed by main.fetch before each search
PAGE = re.compile(r"JobSpy:\w+ - search page: (\d+) / (\d+)")    # logged by jobspy for each results page
SCORE_STEP = re.compile(r"^\s*\[(\d+)/(\d+)\]")                    # printed by main.score for each job


def current_resume():
    found = [r for r in (Path("resume.pdf"), Path("resume.txt")) if r.exists()]
    return max(found, key=lambda r: r.stat().st_mtime) if found else None


st.set_page_config(page_title="Job matches", layout="wide", initial_sidebar_state="expanded")
st.html("""<style>
::selection { background: rgba(31, 132, 85, .28) }
/* the table grows with the job list, so keep the selected job's details in view while scrolling it */
[data-testid="stColumn"]:has(.st-key-job-detail) { align-self: stretch; }
[data-testid="stLayoutWrapper"]:has(> .st-key-job-detail) { position: sticky; top: 4rem; max-height: calc(100vh - 5rem); overflow-y: auto; }
.st-key-table-head { margin-bottom: .75rem; }  /* room for the table's hover toolbar, which otherwise covers Clear all jobs */
</style>""")
if not PREFS.exists():
    st.error("There's no prefs.toml yet. Copy prefs.example.toml to prefs.toml, set your job titles, then reload.")
    st.stop()
P = load_prefs(PREFS)


@st.cache_resource
def scan():  # outlives page reloads, so a running scan is never lost or started twice
    return {"proc": None, "seen_end": True}


def save(changes):  # edits prefs.toml in place, keeping its comments
    doc = tomlkit.parse(PREFS.read_text())
    for k, v in changes.items():
        doc[k] = v
    doc.pop("remote_only", None)  # replaced by work_types
    PREFS.write_text(tomlkit.dumps(doc))


def load():
    df = pd.read_sql("SELECT url, title, company, location, country, max_salary, posted, scored_at, status, score, why, gaps, "
                     "work_type FROM jobs WHERE COALESCE(posted, found_at) > date('now', ?)", connect(),
                     params=(f"-{P['max_age_days']} days",))
    df["posted"] = pd.to_datetime(df.posted, errors="coerce")
    df["scored_at"] = pd.to_datetime(df.scored_at, errors="coerce")
    df["work_type"] = df.work_type.fillna("")
    return df


def fit(score, title, salary, work_type, threshold):
    if dropped(P, title, salary) or off_type(P, work_type):  # today's rules, so changing them updates the list at once
        return "Excluded"
    if pd.isna(score):
        return "Not scored"  # includes jobs left out under older rules; the next scan scores them
    return "In" if score >= threshold else "Out"


def matches(df, query):
    """Rows with every word of the query somewhere: in the table's fields or the full job description."""
    text = df[["title", "company", "location", "country", "work", "why", "gaps"]].fillna("").astype(str).agg(" ".join, axis=1)
    keep, db = pd.Series(True, index=df.index), connect()
    for word in query.lower().split():
        # descriptions stay in the database: sending them to the page would slow every rerun
        in_description = {u for (u,) in db.execute("SELECT url FROM jobs WHERE instr(lower(description), ?) > 0", (word,))}
        keep &= text.str.contains(word, case=False, regex=False) | df.url.isin(in_description)
    return keep


def words(chosen):
    return list(dict.fromkeys(w.strip().lower() for w in chosen if w.strip()))


def duration(seconds):
    m = round(seconds / 60)
    return "under a minute" if m < 1 else f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def ago(utc_timestamp):
    seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(utc_timestamp).replace(tzinfo=timezone.utc)).total_seconds()
    return "just now" if seconds < 60 else f"{duration(seconds)} ago" if seconds < 86400 else f"{seconds // 86400:.0f} days ago"


def status(running):
    @st.fragment(run_every=2 if running else None)
    def show():
        s = scan()
        proc = s["proc"]
        if proc is None:
            last = connect().execute("SELECT max(last_run) FROM searches").fetchone()[0]
            st.caption(f"Last search finished {ago(last)}." if last else "No scans yet.")
            return
        lines = LOG.read_text().splitlines() if LOG.exists() else []
        if proc.poll() is None:
            searches = [m for m in map(SEARCH_STEP.search, lines) if m]
            scoring = next((m for m in map(SCORE_STEP.search, reversed(lines)) if m), None)
            phase = "Step 2 of 2: scoring jobs" if scoring else "Step 1 of 2: searching job sites" if searches else "Starting"
            box = st.status(phase, state="running", expanded=True)  # no with-block: leaving one marks it complete
            if scoring:
                i, n = map(int, scoring.groups())
                s["first"] = s["first"] or (time.time(), i)
                t0, i0 = s["first"]
                left = f", about {duration((time.time() - t0) / (i - i0) * (n - i))} left" if i > i0 else ""
                box.progress(i / n, text=f"Scored {i:,} of {n:,} jobs{left}.")
            elif searches:
                k, total, site, term = searches[-1].groups()
                page = None
                for line in reversed(lines):  # the latest page line since this search began
                    if SEARCH_STEP.search(line):
                        break
                    page = page or PAGE.search(line)
                p, q = map(int, page.groups()) if page else (0, 1)
                box.progress(min((int(k) - 1 + p / q) / int(total), 1.0),
                             text=f"Search {k} of {total}: {SITES.get(site, site)} for '{term}'" + (f", page {p} of {q}." if page else "."))
            else:
                box.progress(0.0, text="Checking Ollama and reading your resume.")
            box.caption(f"Running for {duration(time.time() - s['started'])}. You can keep using the page; "
                        "you'll also get a notification when it's done.")
            stop, partial = box.columns(2)
            if stop.button("Stop scan", icon=":material/stop_circle:", width="stretch"):
                proc.terminate()
                s["stopped"] = True
                st.rerun(scope="app")
            if scoring and partial.button("Show results so far", width="stretch"):
                st.rerun(scope="app")
        elif not s["seen_end"]:
            s["seen_end"], s["took"] = True, duration(time.time() - s["started"])
            st.rerun(scope="app")  # reload the whole page with the new scores
        elif s["stopped"]:
            st.info("Scan stopped. Jobs found so far are kept, and the next scan scores the rest.")
        elif proc.returncode:
            reason = next((l.strip() for l in reversed(lines) if l.strip() and "JobSpy" not in l), "no output")
            st.error(f"The scan stopped with an error: {reason}. The full log is in scan.log.")
        else:
            found = next((m.group(1) for m in map(re.compile(r"(\d+) new postings").search, lines) if m), "0")
            st.success(f"Scan finished in {s['took']}: {found} new jobs found and scored.")
    show()


@st.dialog("Clear all jobs?")
def clear(n, tracked):
    st.write(f"This deletes all {n:,} saved jobs and their scores"
             + (f", including {tracked} applications you're tracking" if tracked else "")
             + f". It can't be undone. Drafts in the applications folder are kept, and the next scan searches "
             f"the full {P['max_age_days']} days again.")
    keep, delete = st.columns(2)
    if keep.button("Keep them", type="primary", width="stretch"):
        st.rerun()
    if delete.button("Delete all jobs", icon=":material/delete:", width="stretch"):
        db = connect()
        db.execute("DELETE FROM jobs")
        db.execute("DELETE FROM searches")  # so the next scan looks back the whole window again
        db.commit()
        st.session_state.cleared = n
        st.rerun()


s = scan()
running = s["proc"] is not None and s["proc"].poll() is None

with st.sidebar:
    st.header("Resume")
    upload = st.file_uploader("Resume", type=["pdf", "txt"], label_visibility="collapsed",
                              help="Saved in this folder. It never leaves your computer.")
    if upload:
        Path("resume" + Path(upload.name).suffix.lower()).write_bytes(upload.getvalue())
    resume = current_resume()
    st.caption(f"Scoring against {resume}." if resume else "Add your resume to start scanning.")
    st.divider()

    st.header("Search settings")
    code = country_code(P["country"])
    country = st.selectbox("Country", list(COUNTRIES), index=list(COUNTRIES).index(code), format_func=COUNTRIES.get, key="country")
    here = P["location"] if country == code else ""  # a new country starts without a state
    if country == "usa":
        states = ["", *US_STATES, *([here] if here and here not in US_STATES else [])]
        location = st.selectbox("State", states, index=states.index(here), format_func=lambda x: x or "Anywhere in the US", key="loc-usa")
    else:
        location = st.text_input("State, region or city", here, placeholder="Anywhere in the country", key=f"loc-{country}").strip()
    work = st.pills("Work type", WORK_TYPES, selection_mode="multi", default=P["work_types"], format_func=str.capitalize, key="work")
    include = words(st.multiselect("Title must include one of", words(SUGGEST_INCLUDE + P["include_title_keywords"]),
                                   default=P["include_title_keywords"], accept_new_options=True, placeholder="Any title", key="include",
                                   help="Whole words in any case: 'intern' matches 'Intern' but not 'Internal', so add 'internship' too. "
                                        "They're also added to every search, so the sites return more of these roles."))
    exclude = words(st.multiselect("Leave out titles with", words(SUGGEST_EXCLUDE + P["exclude_title_keywords"]),
                                   default=P["exclude_title_keywords"], accept_new_options=True, placeholder="Nothing left out",
                                   key="exclude", help="Whole words in any case. Type your own and press Enter."))
    sites = st.pills("Job sites", list(SITES), selection_mode="multi", default=P["sites"], format_func=SITES.get, key="sites")
    st.caption("Only Indeed and LinkedIn returned jobs when last tested; the others are blocked or broken in jobspy.")
    changes = {"country": country, "location": location, "work_types": work, "sites": sites,
               "include_title_keywords": include, "exclude_title_keywords": exclude}
    if not work or not sites:
        st.warning("Pick at least one work type and one job site.")
    elif any(P[k] != v for k, v in changes.items()):
        save(changes)
        P.update(changes)
        st.toast("Saved. The next scan uses these settings.")
    terms = ", ".join(P["search_terms"]) or "job titles picked from your resume"
    st.caption(f"Searches for {terms}, up to {P['max_jobs']:,} jobs posted in the last {P['max_age_days']} days, "
               f"scored by {P['model']}. Job titles, limits and model are set in prefs.toml.")
if n := st.session_state.pop("cleared", None):
    st.toast(f"Deleted {n:,} jobs.")

head, action = st.columns([5, 2], vertical_alignment="center")
head.title("Job matches")
if action.button("Scanning…" if running else "Scan for new jobs", type="primary", icon=":material/travel_explore:",
                 width="stretch", disabled=running or not resume):
    s.update(proc=subprocess.Popen([sys.executable, str(Path(__file__).with_name("main.py")), str(resume), "--notify"],
                                   stdout=LOG.open("w"), stderr=subprocess.STDOUT),
             seen_end=False, stopped=False, started=time.time(), first=None)
    st.rerun()
if not resume:
    action.caption("Add your resume in the sidebar to scan.")
status(running)

df = load()
if df.empty:
    st.info("No jobs yet. Add your resume in the sidebar, then press Scan for new jobs. The first scan takes a while; "
            "you can follow its progress here and the table fills in when it finishes.")
    st.stop()

c1, c2, c3, c4 = st.columns([3, 3, 2, 3], vertical_alignment="bottom", gap="medium")
threshold = c1.slider("Minimum score", 0, 100, P["min_score"], help="Jobs scoring at least this are In. Starts at min_score from prefs.toml.")
show_only = c2.segmented_control("Show", ["In and out", "In", "Out", "Excluded"], default="In and out",
                                  help="Jobs left out by your title, salary or work-type rules only appear under Excluded.")
sort = c3.selectbox("Sort by", list(SORTS), help="Score puts your companies first. Newest dates come first; countries go A to Z.")
query = c4.text_input("Search", placeholder="Title, company, skill…", help="Searches every job, including the full description. "
                       "Every word must appear somewhere, so 'python intern' finds internships that mention Python.")

df["fit"] = [fit(sc, t, sal, wt, threshold) for sc, t, sal, wt in zip(df.score, df.title, df.max_salary, df.work_type)]
df["why"] = [dropped(P, t, sal) or off_type(P, wt) if f == "Excluded" else w
             for f, t, sal, wt, w in zip(df.fit, df.title, df.max_salary, df.work_type, df.why)]
df["work"] = df.work_type.str.capitalize()
counts = df.fit.value_counts()
st.caption(", ".join(f"{counts[f]:,} {f.lower()}" for f in FITS if f in counts))

scored = df[df.fit.isin(["In", "Out"])]
if not scored.empty:
    dark = st.context.theme.type == "dark"
    bars = alt.Chart(scored).mark_bar().encode(
        alt.X("score:Q", bin=alt.Bin(step=5, extent=[0, 100]), title="Score"),
        alt.Y("count():Q", title="Jobs"),
        alt.Color("fit:N", scale=alt.Scale(domain=["In", "Out"], range=["#3DB87A", "#4A5560"] if dark else ["#18794E", "#B4BCC5"]),
                  legend=None),
        tooltip=[alt.Tooltip("count():Q", title="Jobs"), alt.Tooltip("fit:N", title="Fit")])
    cutoff = alt.Chart(pd.DataFrame({"t": [threshold]})).mark_rule(strokeWidth=2, color="#E2E9E4" if dark else "#16201B").encode(x="t:Q")
    st.altair_chart(bars + cutoff, height=140)

view = df[df.fit != "Excluded"] if show_only in (None, "In and out") else df[df.fit == show_only]
if query.strip():
    view = view[matches(view, query)]
keys, ascending = SORTS[sort]
view = view.assign(mine=[at(P["companies"], c) for c in view.company]).sort_values(keys, ascending=ascending, na_position="last")
view = view.assign(Fit=[[f] + ["Your company"] * m for f, m in zip(view.fit, view.mine)]).reset_index(drop=True)

table, detail = st.columns([7, 3], gap="medium")
with table:
    shown, clear_col = st.container(key="table-head").columns([3, 1], vertical_alignment="center")
    shown.caption(f"Showing {len(view):,} of {len(df):,} jobs.")
    if clear_col.button("Clear all jobs…", icon=":material/delete:", width="stretch", disabled=running,
                        help="Stop the scan first." if running else "Delete every saved job and score, after a confirmation."):
        db = connect()
        clear(db.execute("SELECT count(*) FROM jobs").fetchone()[0],
              db.execute("SELECT count(*) FROM jobs WHERE status IN ('drafted','applied','interview','offer')").fetchone()[0])
    if view.empty:
        st.info("No jobs match. Lower the minimum score, switch Show to In and out, or clear the search.")
        rows = []
    else:
        # a column where every job says the same thing is noise; Scored shows while sorting by it
        cols = (["Fit", "score", "title", "company"] + [c for c in ("work", "country") if view[c].replace("", None).nunique() > 1]
                + ["posted"] + (["scored_at"] if sort == "Date scored" else []))
        if "jobs" not in st.session_state:
            st.session_state.jobs = {"selection": {"cells": [[0, "title"]]}}  # open the top job on arrival
        # as tall as its rows: the page scrolls, not the table. Clicking any cell opens that job.
        cells = st.dataframe(view, column_order=cols, hide_index=True, height=38 + 35 * len(view), on_select="rerun",
                             selection_mode="single-cell", placeholder="", key="jobs", column_config={
                                 "Fit": st.column_config.MultiselectColumn("Fit", options=list(TAGS), color=list(TAGS.values()),
                                                                           width=190 if P["companies"] else 96),
                                 "score": st.column_config.NumberColumn("Score", format="%d", width=52),
                                 "title": st.column_config.TextColumn("Title", width=240),
                                 "company": st.column_config.TextColumn("Company", width=140),
                                 "work": st.column_config.TextColumn("Work", width=72),
                                 "country": st.column_config.TextColumn("Country", width=100),
                                 "posted": st.column_config.DateColumn("Posted", format="D MMM", width=64),
                                 "scored_at": st.column_config.DateColumn("Scored", format="D MMM", width=64),
                             }).selection.cells
        rows = [r for r, _ in cells]

with detail, st.container(key="job-detail"):
    if not rows or rows[0] >= len(view):
        st.caption("Click a job to see why it's in or out.")
    else:
        j = view.iloc[rows[0]]
        st.subheader(j.title)
        st.write(", ".join(filter(None, [j.company, j.location])) + (f" ({j.work})" if j.work else ""))
        st.badge(j.fit if pd.isna(j.score) else f"{j.fit}, score {j.score:.0f}", color=FITS[j.fit])
        st.caption(" · ".join(f"{label} {d:%-d %b %Y}" for label, d in [("Posted", j.posted), ("Scored", j.scored_at)] if pd.notna(d)))
        st.markdown(f"**Why:** {j.why}" if j.why else "Not scored yet. It gets a score later in the scan.")
        if j.gaps:
            st.markdown("**Missing:**\n" + "\n".join(f"- {g}" for g in j.gaps.split("; ")))
        st.link_button("Open job posting", j.url)
        desc = connect().execute("SELECT description FROM jobs WHERE url=?", (j.url,)).fetchone()[0]
        if desc:
            with st.expander("Job description"):
                st.markdown(desc)
