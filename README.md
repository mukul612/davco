# Dimensional Layout Generator

A small internal web application for the Quality Engineering team. Upload
an engineering drawing PDF, pick **Supplier Layout** or **Customer
Layout**, and it produces:

- a ballooned copy of the drawing (red numbered circles on the print), and
- the correctly filled-in dimensional inspection Excel workbook,

using the exact same rules the team already validated in the
`dimensional-layout` Claude Code skill (grouping, title-block handling,
DAVCO/Customer part numbers, revision, released date, tolerances, etc.) --
this application is a web front end on top of that existing system, not a
rewrite of it.

This document assumes no web development background.

---

## First-Time Setup

You need three things installed on the computer that will run the server
(only that one computer -- your coworkers just use a browser, see "Team
Access" below):

1. **Python 3.10 or newer.** Get it from [python.org/downloads](https://www.python.org/downloads/)
   (not the Microsoft Store version -- it's known to cause a "python not
   found"-style problem). During install, tick **"Add python.exe to PATH"**.
2. **Claude Code**, already installed and signed in (run `claude` once
   from a terminal/PowerShell and follow the login prompt if you haven't).
   The web app uses this same login to analyze drawings -- there's nothing
   extra to configure for that part.
3. That's it -- everything else (the web framework, PDF/Excel libraries,
   etc.) gets installed automatically the first time you start the server.

You do **not** need to install anything on your coworkers' computers --
they only need a web browser.

## Start the Application

Open PowerShell, go to the `webapp` folder, and run the start script:

```powershell
cd "C:\Davco\Layout by AI\webapp"
.\start-server.ps1
```

The first run takes a minute or two (it creates a private Python
environment in `.venv\` and installs the required packages). After that,
starting is quick. When you see:

```
Starting server at http://127.0.0.1:8000 ...
Press CTRL+C to stop.
```

the app is running. Leave this PowerShell window open -- closing it stops
the server.

## Use the Application

1. On the same computer, open a browser to **http://localhost:8000**
2. Drag a drawing PDF onto the upload box (or click **Browse Files**)
3. Choose **Supplier Layout** or **Customer Layout**
4. Click **Generate Layout**
5. Wait -- the status area shows what's happening (analyzing, identifying
   characteristics, generating balloons, filling in the layout,
   validating). A single drawing typically takes **one to a few minutes**;
   this is normal, it's genuinely reading and reasoning about the drawing,
   not a stuck progress bar.
6. When it finishes, download the ballooned PDF, the completed Excel file,
   or both together as a ZIP. If anything about the drawing was uncertain,
   a **Review Required** notice appears with the specific items to
   double-check, plus a downloadable review log.

## Team Access

By default the server only answers on the host computer itself
(`127.0.0.1`, i.e. `localhost`) -- coworkers on other computers can't
reach it yet.

To make it reachable from other computers on your office network:

```powershell
.\start-server.ps1 -Public
```

This binds the server to all network interfaces on the host computer.
Coworkers can then browse to `http://<host computer's IP address>:8000`
(find the IP with `ipconfig` on the host machine -- look for "IPv4
Address"). A hostname like `http://your-computer-name:8000` often works
too, depending on your network's name resolution.

**You will also need a Windows Firewall rule** allowing inbound
connections on the port (8000 by default) before this works from other
computers -- this script does **not** modify firewall settings for you.
To add one yourself (run as Administrator):

```powershell
New-NetFirewallRule -DisplayName "Dimensional Layout Generator" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

**Important limitation:** this is a normal PowerShell process on one
computer, not a hosted cloud service. If the host computer is turned off,
asleep, or the PowerShell window running `start-server.ps1` is closed,
the application is unreachable for everyone until it's started again on
that machine.

If you want a password prompt before anyone (even on your network) can
use the app, set `APP_PASSWORD` in `.env` (see Configuration below) --
leave it blank to keep it open to anyone who can reach the address.

## Stopping the Server

Click into the PowerShell window running the server and press **CTRL+C**.
If you started it detached/in the background, stop it from Task Manager
(look for `python.exe` under the `webapp` working directory) or:

```powershell
Get-Process python | Where-Object { $_.Path -like "*webapp*.venv*" } | Stop-Process
```

## Updating Templates

The two master Excel templates live in:

```
webapp\templates_layout\Blank Supplier DIM.xlsx
webapp\templates_layout\Blank Customer DIM.xlsx
```

These are **read-only application assets** -- every job copies from them
and never writes back, so they're always safe. To roll out a revised
template, replace the file at one of the two paths above (keep the exact
filename) and restart the server. There's no need to touch anything else;
the header-field cell locations are documented in
`.claude\skills\dimensional-layout\scripts\fill_excel.py` if a future
template redesign moves a field.

## Logs

- **Application log:** `webapp\logs\app.log` -- one line per request/job
  stage/error, timestamped. This is the first place to look if something
  fails.
- **Per-job status:** `webapp\jobs\<job-id>\logs\status.json` -- a
  snapshot of that specific job's final state.
- Logs are not automatically cleaned up (job folders are -- see below);
  `app.log` will grow over time and can be safely deleted while the
  server is stopped if it gets large.

## How Long Files Are Kept

Each drawing you process gets its own folder under `webapp\jobs\`. These
are deleted automatically **24 hours** after creation (configurable, see
below) by a background cleanup pass that runs every 30 minutes. A job
that's still processing is never deleted early. Download anything you
need before it expires -- there's no "undo."

## Configuration

Copy `.env.example` to `.env` (the start script does this automatically
the first time) and edit values as needed, then restart the server:

| Variable | Default | Meaning |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | Address the server binds to (use `-Public` instead of editing this directly) |
| `APP_PORT` | `8000` | Port the server listens on |
| `JOB_RETENTION_HOURS` | `24` | How long a completed job's files are kept before automatic deletion |
| `CLEANUP_INTERVAL_MINUTES` | `30` | How often the cleanup pass runs |
| `MAX_UPLOAD_MB` | `50` | Largest PDF the app will accept |
| `ANTHROPIC_API_KEY` | *(blank)* | Only needed if you want the drawing-analysis step to use a dedicated API key instead of the `claude` CLI's own login. Leave blank normally. |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Model used for drawing interpretation |
| `CLAUDE_TIMEOUT_SECONDS` | `300` | Give up on a single drawing analysis after this long |
| `APP_PASSWORD` | *(blank)* | If set, everyone must enter this password once (stored in a browser cookie) before using the app. Leave blank to disable login entirely. |
| `DEBUG` | `false` | Verbose logging; leave off in normal use |

`.env` is excluded from version control (`.gitignore`) -- never commit it
if this project is ever put under source control, since it can hold
`APP_PASSWORD`/`ANTHROPIC_API_KEY`.

## Troubleshooting

**"No working Python interpreter found"** -- Python isn't installed, or
only the Microsoft Store stub is on PATH. Install Python from
python.org and make sure "Add to PATH" was checked, then open a *new*
PowerShell window and try again.

**Drawing analysis fails immediately / "claude CLI not found"** -- Claude
Code isn't installed, or isn't on PATH for the account running the
server. Open a terminal and run `claude` -- if that doesn't work, neither
will this app's analysis step. Install/sign in to Claude Code first.

**A job sits on "Identifying characteristics..." for a long time** -- this
is normal; reading and reasoning about a drawing's dimensions genuinely
takes one to a few minutes for a busy print. It only becomes a problem if
it eventually reports **Failed** with a timeout message -- if that happens
repeatedly, try raising `CLAUDE_TIMEOUT_SECONDS` in `.env`.

**"Review Required" keeps appearing** -- this is by design, not a bug. The
tool flags anything it wasn't fully certain about (a possibly-missed
dimension, an ambiguous grouping, a duplicate it couldn't rule out) so a
person double-checks it, rather than silently guessing. Read the specific
warnings; they name the item and why it's flagged.

**"SAFETY CHECK FAILED: the master Excel template changed on disk"** --
this should never happen (the app only ever copies from the templates,
never writes to them) and indicates something else modified the template
file during processing. Stop the server, verify the two files in
`templates_layout\` look correct, and investigate before restarting.

**Port 8000 already in use** -- either another copy of the server is
already running, or something else on the computer is using that port.
Set `APP_PORT` to a different number (e.g. `8001`) in `.env` and restart.

**Coworkers can't reach the app** -- confirm you started with
`.\start-server.ps1 -Public`, confirm the Windows Firewall rule (see "Team
Access"), confirm they're using the host computer's actual IP address
(not `localhost`, which only means "this computer" to them), and confirm
the host computer is on and the PowerShell window is still running.

**Tests fail after editing code** -- run `.\.venv\Scripts\python.exe -m
pytest tests\ -v` from the `webapp` folder to see exactly which check
failed and why.

---

## For Developers: What's Actually Happening

This section is for whoever maintains the code, not day-to-day users.

- **The ballooning/Excel-filling logic is not duplicated here.**
  `app/layout_engine/__init__.py` imports the three scripts directly from
  `.claude\skills\dimensional-layout\scripts\` (`extract_drawing.py`,
  `create_balloons.py`, `fill_excel.py`) as Python modules. Improve those
  scripts (or the skill's rules) in place, and this web app picks up the
  change automatically -- there's nothing to keep in sync.
- **The one genuinely new piece is `app/layout_engine/interpret.py`** --
  it restates the skill's grouping/title-block/destination rules for a
  single, tool-free, structured-JSON request to the `claude` CLI
  (subprocess, not the raw Anthropic API), so the web backend can drive
  the same reasoning the interactive skill relies on without a human
  running Claude Code by hand. It runs at `--effort high`: slower
  (roughly 1-4 minutes for a dense drawing) but meaningfully more
  complete than lower effort levels in testing -- a missed dimension
  matters more than the extra wait for this tool.
- **`app/services/pipeline.py`** also runs a small deterministic safety
  net (`_find_orphaned_dimensions`) after interpretation: it cross-checks
  every bare decimal-looking value from the extracted text against what
  actually made it into a balloon, and adds a warning for anything that
  didn't. LLM interpretation is not perfect -- this exists so a silently
  dropped dimension becomes a visible warning instead.
- **Jobs are fully isolated** under `jobs/<uuid4-hex>/{input,work,output,logs}/`
  and run on a `ThreadPoolExecutor` (see `app/services/job_manager.py`) --
  no shared global state, no shared temp filenames. If this ever needs to
  scale past one process, swap the executor and the in-memory `_STATE`
  dict for a real queue/shared store; `process_layout()` itself doesn't
  know or care how it's invoked.
- Run `pytest tests/ -v` for the automated test suite (security,
  validation, job isolation/cleanup, Excel template routing via the real
  templates, and the HTTP API -- all against deterministic fixtures, not
  live Claude calls, per the project's testing philosophy of not faking
  assertions about subjective AI interpretation).
