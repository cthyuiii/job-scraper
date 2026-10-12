# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Streamlit page served on localhost, on top of the existing Python app (`main.py`: jobspy for job search, Ollama for the local LLM, SQLite `jobs.db` for state). How other people will install and launch it (double-click launcher, Docker, or both) is undecided; the owner wants it working on their own machine first.

## Users

The owner first: one person running their own job hunt on their own laptop, comfortable with a terminal but wanting a page to see results instead of reading terminal output. Other job seekers, including non-technical ones, are a later audience ("tool for everyone"), deliberately not designed for yet.

## Product Purpose

Find jobs that match your resume and preferences, have a local LLM score every one, and make it obvious which jobs are within your score threshold and which are out, and why. For the jobs you pick, it drafts a cover letter and a short LinkedIn note. You review, apply and send everything yourself, then track each application through applied, interview, rejected or offer, with follow-up reminders. Success: a daily list of worthwhile jobs you can act on in minutes, without missing good ones.

## Positioning

Private and local: the resume and all scoring stay on the user's machine, the LLM runs through Ollama, and only the job searches go out to the job sites. No API costs. A human decides and submits everything: no auto-apply, no LinkedIn account automation, no messages sent on the user's behalf.

## Operating Context

- A scan searches Indeed and LinkedIn for the user's job titles and preferred companies, then scores each new job. Scans can run on demand or daily on a schedule with a desktop notification.
- Scoring time is set by the local model's speed and the number of jobs. The owner wants roughly 1000 jobs per run and a small, fast model so a run doesn't take hours.
- Applying happens on the job sites in the user's own browser; outreach happens on LinkedIn by hand, from drafted notes.

## Capabilities and Constraints

- Job sources: only Indeed and LinkedIn work (tested Sep 2026, jobspy 1.1.82). ZipRecruiter, Bayt and Naukri are blocked; Glassdoor, Google and bdjobs are broken in jobspy. LinkedIn rate-limits heavy use; proxies are optional.
- Settings live in `prefs.toml`: search terms, preferred companies (searched first and listed first), location, remote only, sites, maximum posting age (default 90 days), excluded title words, minimum salary, plain-English wants, model, minimum score.
- Each job has a 0-100 score, a one-line reason, and missing requirements. Jobs whose title matches an excluded word, or whose listed salary is under the minimum, are left out before scoring, with the reason recorded.
- Job statuses: new, filtered, scored, skipped, drafted, applied, interview, rejected, offer.
- Resumes: PDF or plain text only.
- Undecided: the product name ("job-scraper" is the working repo name), and how the app is distributed to others.

## Evidence on Hand

None. No users besides the owner, no testimonials, no benchmarks. Future work must not invent any.

## Product Principles

1. Private by default: nothing about the user leaves their machine except the job searches.
2. The human submits: the tool finds, ranks and drafts, the person decides and sends.
3. Show the reasoning: every score comes with why and what's missing, and every excluded job says why it was excluded.
4. Fast enough to run every day: speed beats the last bit of scoring accuracy.
5. Owner first: make it work well for one person before packaging it for everyone.
