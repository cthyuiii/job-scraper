# job-scraper

Give it your resume. It searches Indeed and LinkedIn, has a local LLM rank the jobs against your experience and preferences, and drafts a cover letter and LinkedIn note for the ones you pick. You review everything and submit it yourself. Nothing leaves your machine except the job searches.

Resumes must be PDF or .txt. For a Word resume, use File > Save As > PDF.

## Setup

**macOS / Linux**
```sh
brew install ollama python@3.12        # jobspy needs Python <= 3.12
brew services start ollama             # keeps Ollama running, also after reboot
ollama pull gemma3:12b                 # or any model; set it in prefs.toml
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp prefs.example.toml prefs.toml       # then edit it
```

**Windows (PowerShell)**
```powershell
winget install Ollama.Ollama           # runs in the tray, starts with Windows
winget install Python.Python.3.12
ollama pull gemma3:12b
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

```sh
.venv/bin/python main.py resume.pdf                # search, score, then review
.venv/bin/python main.py resume.pdf --review-only  # review saved matches
.venv/bin/python main.py resume.pdf --rescore      # after editing your resume or prefs.toml
.venv/bin/python main.py --track                   # mark applied / interview / rejected / offer
```

For each match you see the score, why it fits, and what's missing. Press `d` to draft. The draft is saved to `applications/`, and the tool can open the job page plus a LinkedIn search for recruiters and managers at that company. Edit the draft, apply and send connection requests yourself, then mark it applied. After 7 days with no update, it reminds you to follow up.

List the companies you want most under `companies` in `prefs.toml`. Each one is searched directly, and its jobs are shown first in review with a ★.

The first search looks back `max_age_days` (default 90). After that, each run only looks back to the previous run, and `jobs.db` remembers every job so none is scored twice. Scoring takes about 15s per job on an M1 Pro with `gemma3:12b`, so the first run can take an hour with several companies and job titles. Later runs take minutes.

If LinkedIn keeps finding 0 jobs, it's blocking you. Add proxies in `prefs.toml`.

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
