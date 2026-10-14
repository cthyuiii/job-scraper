# job-scraper

Give it your resume. It searches Indeed and LinkedIn, has a local LLM rank the jobs against your experience and preferences, and drafts a cover letter and LinkedIn note for the ones you pick. You review everything and submit it yourself. Nothing leaves your machine except the job searches.

Resumes must be PDF or .txt. For a Word resume, use File > Save As > PDF.

## Setup

**macOS / Linux**
```sh
brew install ollama python@3.12        # jobspy needs Python <= 3.12
brew services start ollama             # keeps Ollama running, also after reboot
ollama pull qwen3:8b                   # or any model; set it in prefs.toml
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp prefs.example.toml prefs.toml       # then edit it
```

**Windows (PowerShell)**
```powershell
winget install Ollama.Ollama           # runs in the tray, starts with Windows
winget install Python.Python.3.12
ollama pull qwen3:8b
py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy prefs.example.toml prefs.toml     # then edit it
```
On Windows, use `.venv\Scripts\python` wherever this README says `.venv/bin/python`.

**Docker** (no Python install needed; Ollama still runs on your machine so it can use the GPU)
```sh
docker build -t job-scraper .
docker run -it --rm -v "$PWD:/data" job-scraper resume.pdf     # PowerShell: "${PWD}:/data"
```
On Linux, add `--network host -e OLLAMA_URL=http://localhost:11434`. The container can't open your browser or send notifications, so open the links in `applications/` yourself.

## Use

**The page** (start it from this folder, then open http://localhost:8501):
```sh
.venv/bin/streamlit run app.py
```
Upload your resume in the sidebar, pick the country, state, work types (remote, hybrid, on-site) and job sites under **Search settings** (saved to `prefs.toml`), and press **Scan for new jobs**. Only remote can be filtered during the search; the model reads each job's work type while scoring, and jobs of a type you didn't pick are listed as Excluded. Every job is listed as **In** (at or above your minimum score), **Out**, **Excluded** (dropped by `exclude_title_keywords` or `min_salary`, with the reason) or **Not scored** yet. While a scan runs, the page shows which search it's on (site, job title, page) and then how many jobs are scored with the time left; **Stop scan** keeps what was found so far. Sort the table by score, date posted, date scored or country. **Search** looks through every job, including the full description; every word you type must appear somewhere. Under Search settings, **Title must include one of** (e.g. intern, internship) is added to every search, so the sites return mostly those roles, and any other title is listed as Excluded. Excluded jobs only show under **Show: Excluded**. **Clear all jobs**, above the table, empties `jobs.db` after a confirmation. The table grows with the list, and the selected job's details stay in view as you scroll. Drag **Minimum score** to move the cutoff; the chart shows where it falls. Click any job, or move through them with the arrow keys, to see why it scored that way, what's missing, and a link to the posting. The page runs only on your computer and sends Streamlit no usage data.

**The command line** (for drafting, tracking and scheduled runs):
```sh
.venv/bin/python main.py resume.pdf                # search, score, then review
.venv/bin/python main.py resume.pdf --review-only  # review saved matches
.venv/bin/python main.py resume.pdf --rescore      # after editing your resume or prefs.toml
.venv/bin/python main.py resume.pdf --full-search  # search back max_age_days again, e.g. after raising max_jobs
.venv/bin/python main.py --track                   # mark applied / interview / rejected / offer
```

For each match you see the score, why it fits, and what's missing. Press `d` to draft. The draft is saved to `applications/`, and the tool can open the job page plus a LinkedIn search for recruiters and managers at that company. Edit the draft, apply and send connection requests yourself, then mark it applied. After 7 days with no update, it reminds you to follow up.

List the companies you want most under `companies` in `prefs.toml`. Each one is searched directly, and its jobs are shown first in review with a ★.

The first search looks back `max_age_days` (default 90). After that, each run only looks back to the previous run, and `jobs.db` remembers every job so none is scored twice. Each scan collects up to `max_jobs` (default 1000), split evenly over every search (job titles x companies x sites). Sites rank recent postings first, so a bigger number reaches further back. After raising it, run once with `--full-search`.

Jobs whose title matches `exclude_title_keywords`, or whose listed salary is under `min_salary`, are skipped without scoring, and the output says why.

## Speed and model choice

The default model, `qwen3:8b`, scores a job in about 5 seconds on an M1 Pro, so a full 1000-job first scan takes about an hour and a half; later scans only score new postings. It got 13 of 15 jobs with known answers right. `gemma3:12b` got 14 but takes about 16 seconds per job. `gemma3:4b` is no faster than `qwen3:8b` and rated senior and off-field jobs as fits. Bigger models (27B and up) can take a minute or more per job, which turns a first scan into a day.

## Job sites

`prefs.toml` lists all 8 sites jobspy supports. When tested (Sep 2026, jobspy 1.1.82), only Indeed and LinkedIn returned jobs. ZipRecruiter and Bayt blocked the requests, Naukri asked for a CAPTCHA, and Glassdoor, Google and bdjobs are broken inside jobspy. The blocked ones may work from another network or through proxies.

## LinkedIn proxies

LinkedIn limits how many searches one internet connection can make. When it blocks you, LinkedIn searches find 0 jobs; waiting an hour or two usually clears it. If it keeps happening:

1. Buy **rotating residential** proxies from a provider such as Webshare, IPRoyal, Decodo, Bright Data or Oxylabs. They're billed per GB, and this tool uses little data. Cheaper "datacenter" proxies get blocked by LinkedIn almost at once. Avoid free proxy lists: they're unreliable and see your traffic.
2. The provider gives you a host, port, username and password. Add them to `prefs.toml`:
   ```toml
   proxies = ["username:password@host:port"]
   ```
   You can list several; jobspy rotates through them. Proxies apply to every site.

No LinkedIn account is used, so a block never affects your own LinkedIn profile.

## Run it every morning

The scheduled run searches and scores, then sends a notification when there's something to review. Put your resume in this folder as `resume.pdf` and run these commands from this folder.

**macOS** (runs at 8:00, or when your Mac wakes if it was asleep)
```sh
cat > ~/Library/LaunchAgents/local.job-scraper.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.job-scraper</string>
  <key>WorkingDirectory</key><string>$PWD</string>
  <key>ProgramArguments</key><array>
    <string>$PWD/.venv/bin/python</string><string>main.py</string><string>resume.pdf</string><string>--notify</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$PWD/scheduled.log</string>
  <key>StandardErrorPath</key><string>$PWD/scheduled.log</string>
</dict></plist>
EOF
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.job-scraper.plist
launchctl kickstart gui/$(id -u)/local.job-scraper   # optional: run once now to test
```
If no notification appears, allow notifications for Script Editor in System Settings > Notifications. To remove: `launchctl bootout gui/$(id -u)/local.job-scraper`.

**Linux**
```sh
(crontab -l; echo "0 8 * * * cd $PWD && DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus .venv/bin/python main.py resume.pdf --notify >> scheduled.log 2>&1") | crontab -
```

**Windows** (runs at 8:00, or when your PC wakes; no console window and no log file, errors come as a notification)
```powershell
$run = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\pythonw.exe" -Argument "main.py resume.pdf --notify" -WorkingDirectory "$PWD"
Register-ScheduledTask job-scraper -Action $run -Trigger (New-ScheduledTaskTrigger -Daily -At 8am) -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)
```
To remove: `Unregister-ScheduledTask job-scraper`.
