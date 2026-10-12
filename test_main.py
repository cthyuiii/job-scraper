import sqlite3
from main import SCHEMA, at, country_code, dropped, followups_due, off_type, to_review, where

P = {"exclude_title_keywords": ["Intern"], "include_title_keywords": [], "min_salary": 100_000}
assert dropped(P, "Software Engineering intern", None)
assert dropped(P, "Backend Engineer", 80_000)
assert not dropped(P, "Backend Engineer", None)       # no salary listed: keep
assert not dropped(P, "Backend Engineer", 120_000)
assert not dropped({**P, "min_salary": 0}, "Backend Engineer", 80_000)
assert dropped(P, "Senior Intern", None) == "title contains 'Intern'"   # reason is printed to the user

assert where({"location": "Scotland", "country": "uk"}) == "Scotland, United Kingdom"
assert where({"location": "", "country": "usa"}) == "United States"   # no state: whole country
assert country_code("United States") == "usa"
assert off_type({"work_types": ["remote"]}, "on-site") and not off_type({"work_types": ["remote"]}, "remote")
assert not off_type({"work_types": ["remote"]}, None)                   # work type unknown: keep

Q = {"exclude_title_keywords": [], "include_title_keywords": ["intern", "internship"], "min_salary": 0}
assert not dropped(Q, "Software Engineering Internship", None) and not dropped(Q, "AI Intern (Summer)", None)
assert dropped(Q, "Internal Tools Engineer", None) == "title has none of: intern, internship"   # whole words only
assert at(["sr."], "Sr. Data Engineer") and at(["c++"], "C++ Developer")

assert at(["grab"], "Grab Holdings") and not at(["Grab"], "Grabango") and not at(["Grab"], None)

db = sqlite3.connect(":memory:")
db.executescript(SCHEMA)
add = ("INSERT INTO jobs(url,company,title,status,score,posted,found_at,updated_at) "
       "VALUES(?,?,?,?,?,date('now',?),datetime('now',?),datetime('now',?))")
db.execute(add, ("match", "A", "t", "scored", 90, "-5 days", "-1 days", "-1 days"))
db.execute(add, ("my-company", "Grab Holdings", "t", "scored", 70, "-5 days", "-1 days", "-1 days"))  # lower score, still first
db.execute(add, ("posted-100d", "B", "t", "scored", 95, "-100 days", "-1 days", "-1 days"))  # found today, posted too long ago
db.execute(add, ("no-date-old", "F", "t", "scored", 99, None, "-100 days", "-100 days"))     # no posted date: age from found_at
db.execute(add, ("weak", "C", "t", "scored", 40, "-5 days", "-1 days", "-1 days"))           # below min_score
db.execute(add, ("on-site", "G", "t", "scored", 92, "-5 days", "-1 days", "-1 days"))
db.execute("UPDATE jobs SET work_type='on-site' WHERE url='on-site'")                     # work type not chosen
db.execute(add, ("applied-8d", "D", "t", "applied", None, "-10 days", "-10 days", "-8 days"))  # follow-up due
db.execute(add, ("applied-2d", "E", "t", "applied", None, "-3 days", "-3 days", "-2 days"))
prefs = {"min_score": 60, "top_n": 10, "max_age_days": 90, "companies": ["Grab"], "work_types": ["remote", "hybrid"],
         "exclude_title_keywords": [], "include_title_keywords": [], "min_salary": 0}
assert [r[0] for r in to_review(prefs, db)] == ["my-company", "match"]
assert followups_due(db) == 1
print("ok")
