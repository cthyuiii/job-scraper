import sqlite3
from main import SCHEMA, at, dropped, followups_due, to_review

P = {"exclude_title_keywords": ["Intern"], "min_salary": 100_000}
assert dropped(P, "Software Engineering intern", None)
assert dropped(P, "Backend Engineer", 80_000)
assert not dropped(P, "Backend Engineer", None)       # no salary listed: keep
assert not dropped(P, "Backend Engineer", 120_000)
assert not dropped({**P, "min_salary": 0}, "Backend Engineer", 80_000)

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
db.execute(add, ("applied-8d", "D", "t", "applied", None, "-10 days", "-10 days", "-8 days"))  # follow-up due
db.execute(add, ("applied-2d", "E", "t", "applied", None, "-3 days", "-3 days", "-2 days"))
prefs = {"min_score": 60, "top_n": 10, "max_age_days": 90, "companies": ["Grab"]}
assert [r[0] for r in to_review(prefs, db)] == ["my-company", "match"]
assert followups_due(db) == 1
print("ok")
