DEAR PIGGY - PYTHON COURSEWORK EDITION
====================================

Dear Piggy is a local self-care companion with daily habits, a mood diary,
breathing activities, an illustrated pig, and an energy-based clothing shop.
This edition is primarily Python: Python implements the game rules, validation,
SQLite persistence, HTTP routes, HTML rendering, and optional AI integration.
It is a substantive Python port of the earlier website, not a wrapper that runs
the earlier JavaScript application.

RUN THE PROGRAM

Requirements: Python 3.9 or newer, with its standard-library sqlite3 module,
and a modern browser such as Chrome, Edge, Firefox, or Safari.
No pip install, virtual environment, Flask, Node.js, npm, or build step is needed.
Check your Python version with python3 --version (Windows: py -3 --version).

1. Extract the complete submission, keeping its folder structure and assets.
2. Open a terminal in the folder containing this README.txt and main.py.
3. Run:

       python3 main.py

   On Windows, use:

       py -3 main.py

4. Open http://127.0.0.1:4180 in a modern browser. A guest browser profile is
   useful for an independent marking session. No invitation or login is needed.
5. Keep the terminal running. Stop the server with Ctrl+C when finished.

The server binds only to 127.0.0.1, so it is intended for use on this computer.
If port 4180 is occupied, use:

    python3 main.py --port 4181

Then open http://127.0.0.1:4181. The Windows equivalent starts with py -3.

Progress is saved by default in data/piggy.sqlite3. To keep marking data
separate, choose a new local folder:

    python3 main.py --data-dir marking-data

An absolute path to a temporary or custom folder is also accepted. Use the same
data directory and browser profile to revisit that session's progress.

FIVE-MINUTE MANUAL MARKING PATH

1. Open the welcome page, choose English if needed, and enter the app.
2. Complete a daily habit. Confirm energy rises by 10 and its completion button
   becomes disabled, preventing another award that day. The first six completions
   per day award energy; later completions can still increase total growth.
3. Add a custom habit, delete it, and restore it. Try the daily check-in and
   rest controls. Switch language to inspect the bilingual interface.
4. Save a mood diary entry with a short note; optionally attach a small photo.
   Refresh the page and confirm the entry remains. Try the breathing or worry
   activity. Worry text is transient and is not a saved diary entry.
5. Open the shop, preview a paid item, and confirm preview does not spend energy.
   Open My wardrobe: the free blanket and room are already owned and in use.
   Paid purchases require enough earned energy;
   a new profile is not expected to afford them during this short walkthrough.
   Open Growth and Settings, then refresh to check saved changes.

The optional AI chat is not required for this marking path. Without an API key,
the core app remains usable and chat configuration is explained in the app.

OPTIONAL OPENAI CHAT

The submitted files contain no API key. No key or online account is required
for habits, the diary, the shop, or the rest of the base app.

To enable AI chat, copy .env.example to .env.local beside main.py and set:

    OPENAI_API_KEY=your-own-key
    OPENAI_MODEL=gpt-6-luna

Alternatively, set these as environment variables before starting the server.
Environment variables take precedence over values in .env.local.
Restart the server after changing configuration. OPENAI_MODEL can be changed
to a model available to the configured API account. Model access depends on
that account; enabling chat may incur API charges.

Configuration is read on the Python server. The key is not sent to browser
code and must not be included in a submitted or shared archive. When enabled,
chat requests use Python's standard-library urllib over HTTPS to OpenAI, so
they require internet access. Chat content is sent to that external service.
The app does not store the API key, chat conversations, or worry text in its
SQLite game database. Recent chat history is held in the running server's memory
for the browser session: refreshing a page preserves it, while clearing chat
or restarting the server removes it. Worry text stays in the browser and is not
sent to the server. HTTP request logging does not record that content. This
edition has no cloud account synchronization.

TECHNOLOGY AND COMPATIBILITY DISCLOSURE

- Python dependencies: standard library only, including http.server, sqlite3,
  urllib, json, and unittest. There are no third-party Python packages.
- Graphics / GUI: the interface runs in a browser. Python generates HTML;
  local CSS and PNG/SVG illustrations display the pig and interface. Browser
  Canvas is used to prepare diary photos. This is not a terminal-only program
  or a desktop Tkinter/Pygame application.
- JavaScript: a small local enhancement script handles browser animation,
  audio, photo preparation, and visual conveniences. Game rules, purchases,
  saved state, and page rendering are implemented in Python.
- Audio / video: a bundled local .m4a music loop was extracted from a
  user-supplied video for the earlier project. The browser plays this local
  file when the music button is clicked; there is no Web Audio synthesis in
  this edition. No video playback, runtime video processing, FFmpeg, or external
  audio/video Python library is required.
- Web / networking: the browser communicates with the local Python HTTP
  server. The optional AI feature adds outbound HTTPS requests to OpenAI.
  The base application and bundled fonts/assets do not need internet access.
- Earlier website dependencies: this port does not include or require the
  earlier Three.js or Supabase runtime, Node build, or cloud backend.
- Ed compatibility: Ed's terminal-only execution environment cannot display
  this browser GUI, and a loopback server inside Ed is not the marker's local
  browser. Run the full application locally using the instructions above.
  The standard-library unit tests can be run in a compatible Python terminal.

FILES TO REVIEW

    main.py                Entry point, local HTTP server, routes and sessions
    game.py                Daily habits, rewards, diary, shop and game rules
    storage.py             SQLite persistence and transactional state changes
    views.py               Python-rendered HTML pages and forms
    ai_chat.py             Optional server-side OpenAI integration
    catalogue.json         Bilingual habit, mood, clothing and colour catalogue
    static/style.css       Interface styling
    static/avatar.css      Illustrated pig and clothing styling
    static/enhance.js      Browser animation, audio and photo conveniences
    static/assets/         Local illustrations, fonts and music
    tests/                 Python standard-library unittest test suite
    package_submission.py  Builds the distributable submission archive
    TEST_RESULTS.txt        Verification record with interpreter and outcomes
    .env.example           Optional configuration template; contains no secret
    README.txt             Run instructions and implementation disclosures

Suggested source reading order: game.py, storage.py, views.py, main.py, then
ai_chat.py. main.py is the executable Python entry point.

Keep every supplied .py file and the static/catalogue files together. The
data directory is generated at runtime; saved personal data is not needed to
start or mark the application.

TESTS

From this folder, run:

    python3 -m unittest discover -s tests -v

On Windows:

    py -3 -m unittest discover -s tests -v

The suite uses unittest and mocks for external AI requests. It does not need
an API key, contact OpenAI, or incur API charges. Browser appearance, animation,
sound, and photo selection should also be checked with the manual path above.
See TEST_RESULTS.txt for the recorded verification environment and outcomes.
The commands in this README are instructions for reproducing the checks.

REBUILDING THE SUBMISSION ARCHIVE

The marker can run the extracted files directly; packaging is not a launch step.
To rebuild the distributable archive from the source folder, run:

    python3 package_submission.py

On Windows, use py -3 package_submission.py. The output is
dist/Dear-Piggy-Python-Coursework.zip, with a top-level Dear-Piggy-Python folder.
The submission contains the source and local assets, not API keys, runtime
databases, browser profiles, or saved user records.

ED'S 2 MB LIMIT AND THE EXTERNAL ASSET COPY

The public coursework repository contains the complete code and local assets:
https://github.com/lorraineshou-dev/dearpiggy-python-coursework

For Ed, upload README.txt and every Python file. The Ed-specific README must
identify the exact Git commit being submitted and link to its full ZIP archive,
so the marker can download the larger illustrations, fonts, and music.
After publishing the final code, create this small submission with:

    python3 package_submission.py --ed-commit FULL_40_CHARACTER_COMMIT_ID

This produces dist/Dear-Piggy-Ed-Submission.zip (checked to be below 2 MB)
and an extracted folder of the same name. The folder contains all Python files,
catalogue.json, tests, and the Ed-specific README; static/ is hosted externally.
If Ed expects individual files, upload the folder's README.txt and all .py files
instead of relying only on an uploaded ZIP. Keep tests in their tests/ folder
when downloading the project to run it.

The confirmed course deadline is 1 November 2026 at 11:59 pm Australia/Sydney
(AEDT, UTC+11). Do not modify the hosted submission files after that deadline.
The pinned snapshot link in the Ed README is the version intended for marking.

PERSISTENCE AND LIMITATIONS

The local SQLite database stores game profiles and diary entries, including
saved diary photos. A random browser cookie identifies a profile; it is not
an account login or authentication system. A different browser, a new guest
session, or clearing cookies creates a different profile. There is no account
recovery, cross-device sync, or shared online multiplayer service.

Daily progress follows the computer's local calendar date. The app is designed
for a local coursework demonstration, not deployment as a public web service.
The diary holds up to 50 entries. Photo selection accepts JPEG, PNG, or WebP
files up to 10 MiB, resizes them in the browser, and submits a JPEG; the server
accepts only validated images up to 2 MiB. Older diary entries can be deleted.
Some enhancements, including audio and photo preparation, require JavaScript
and the relevant browser APIs. AI chat depends on an external API only when
the optional configuration is supplied.

ASSET SOURCES, LICENCES, AND AI ASSISTANCE

Bundled fonts are third-party assets, not Python dependencies:

- Swei Gothic CJK SC Regular / Medium (Swei Gothic):
  https://github.com/max32002/swei-gothic
  SIL Open Font License 1.1: static/assets/fonts/Swei-OFL.txt
- Nunito:
  https://github.com/google/fonts/tree/main/ofl/nunito
  SIL Open Font License 1.1: static/assets/fonts/Nunito-OFL.txt

Font source revisions and checksums are recorded in
static/assets/fonts/README.md. Fonts are bundled and loaded locally.

This submission was produced with OpenAI Codex assistance, including the
Python port, supporting code, and documentation. It reuses the project's
approved AI-generated illustrations and existing local artwork. The bundled
music comes from the user-supplied video described above. These reused assets
should not be represented as entirely hand-created for this Python submission.
The optional in-app AI chat is separate from the AI assistance used to develop
the project.
