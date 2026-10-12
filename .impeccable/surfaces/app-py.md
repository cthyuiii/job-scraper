---
version: 1
slug: "app-py"
primary_target: "app.py"
related_targets: []
---

Scope: the Streamlit page (`app.py`) that lists every job a scan found. Mode: Operate.
Audience and task: the owner, at their laptop, checking which jobs are within their score threshold and which are out, and why; starting a scan from the same page. Used after each scan and on daily check-ins; up to about 1000 jobs at a time.
Constraints: Streamlit components only (owner chose Streamlit over a custom page); localhost only, never hosted; no telemetry.

## Direction contract

THESIS: The threshold is the interface. One slider decides In or Out for every job at once, and the page shows that split everywhere: on the score histogram, in every row, in the detail panel. It refuses the category default of a plain results list with scores buried in text.
OWN-WORLD: Streamlit's native components, themed: green-tinted neutral grounds (light #F7F9F8 / dark #0E1411), deep green for In (#18794E / #3DB87A), slate for Out, amber for Excluded, blue for Not scored, used as state colours in pills, badges and bars. Follows the system light or dark setting. System sans, small radius.
STORY: The owner sees how many jobs are in and out, drags the threshold and watches the split move, picks a job, reads why it scored that way and what's missing, and opens the posting.
FIRST VIEWPORT: Sidebar left: resume upload, Scan button with live progress, a one-line summary of what is searched. Main: title; a control row (Minimum score slider, Show All/In/Out/Excluded, search); a counts line; a 140px score histogram coloured In/Out with the threshold drawn as a vertical rule; below, the job table (2/3 width: Fit pill, Score, Title, Company, Posted) beside the selected job's detail (1/3 width).
FORM: Pinned by the user (Streamlit, native components); no concept roll was run, so there is no seed key. Signature move: the threshold rule on the score distribution, driven by the slider.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
