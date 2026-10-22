# voice_control

Control an application with **spoken commands**. You write a small *controller* class
whose methods are decorated with the phrases that should trigger them; `voice_control`
listens (microphone or stdin), matches what was said against those phrases, pulls
arguments out of the sentence and calls the method. Executed commands can be saved to
a JSON history and replayed later.

```python
from voice_control import Controller, MatchType, command

class Timer(Controller):
    @command(r"set (?:a )?timer for (?P<minutes>\d+) minutes?", MatchType.DYNAMIC)
    def set_timer(self, minutes: int):
        """Start a countdown."""
        return f"Timer set for {minutes} min"
```

```console
$ voice-control do --app myapp:Timer "Set a timer for 5 minutes"
Timer set for 5 min
```

## Install

Requires Python 3.10+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # core + text input (no extra dependencies)
pip install -e '.[mic]'     # + microphone input (SpeechRecognition, PyAudio)
pip install -e '.[sphinx]'  # + offline CMU Sphinx engine
pip install -e '.[dev]'     # + pytest
```

PyAudio needs the PortAudio library (e.g. `apt install portaudio19-dev` on Debian/Ubuntu).

## Usage

```
voice-control run     listen for commands and execute them
voice-control do      execute commands given as arguments (as if spoken)
voice-control list    list the commands an app understands (--apps: list apps)
voice-control replay  re-run commands from a history file
```

Every subcommand has `--help`. Two example apps are built in: `home` (light, music,
volume) and `paint` (build a list of shapes); any `module:ClassName` works too.

Execute sentences directly and record them:

```console
$ voice-control do --app paint "Make rectangle of width 10 and height 20 with top left corner at 5, 5." \
    "draw a circle of radius 3 at the origin" "list shapes" --history drawing.json
Making rectangle 10x20 at (5, 5)
Making circle r=3 at (0, 0)
1. rectangle 10x20 at (5, 5)
2. circle r=3 at (0, 0)

$ voice-control replay --app paint drawing.json
> Make rectangle of width 10 and height 20 with top left corner at 5, 5.
Making rectangle 10x20 at (5, 5)
> draw a circle of radius 3 at the origin
Making circle r=3 at (0, 0)
> list shapes
1. rectangle 10x20 at (5, 5)
2. circle r=3 at (0, 0)

$ voice-control do --app paint "undo"; echo $?
Error: nothing to undo
1
```

Interactive session; the default `text` backend reads one sentence per line from stdin,
so you can try any controller without a microphone:

```console
$ printf 'turn on the light\nplay Bohemian Rhapsody\nset the volume to 30\nmake me a sandwich\nstatus\nstop listening\n' \
    | voice-control run --app home
You said: turn on the light
Turning on the light
You said: play Bohemian Rhapsody
Playing Bohemian Rhapsody
You said: set the volume to 30
Volume set to 30
You said: make me a sandwich
Command not recognized: 'make me a sandwich'
You said: status
Light is on; playing Bohemian Rhapsody; volume 30
You said: stop listening
Bye.
```

With a microphone:

```bash
voice-control run --app paint --backend mic                  # Google Web Speech API (online)
voice-control run --app paint --backend mic --engine sphinx  # offline
voice-control run --backend mic --language pl-PL --timeout 5 --phrase-time-limit 8 --once
```

During `run`, say **"help"** (or "what can I say") to list commands and **"stop
listening"** / "exit" / "quit" / "goodbye" to end. Ctrl-C also exits cleanly and the
history is still saved.

Exit codes: `0` success, `1` a command was not recognized / failed or the backend broke,
`2` usage or configuration error (unknown app, unreadable history), `130` interrupted.

## Configuration

CLI flags win; otherwise these environment variables supply defaults:

| Variable                 | Flag          | Default  |
|--------------------------|---------------|----------|
| `VOICE_CONTROL_APP`      | `--app`       | `home`   |
| `VOICE_CONTROL_BACKEND`  | `--backend`   | `text`   |
| `VOICE_CONTROL_ENGINE`   | `--engine`    | `google` |
| `VOICE_CONTROL_LANGUAGE` | `--language`  | `en-US`  |
| `VOICE_CONTROL_HISTORY`  | `--history`   | (none)   |

## Writing a controller

Decorate methods with `@command(pattern, match_type)` (`register_action` is kept as an
alias of the prototype's name). A method may carry several decorators for alternative
phrasings; the first matching command in definition order wins. Input is normalized
first (whitespace collapsed, trailing `.!?` dropped, case ignored).

| `MatchType`    | Pattern is          | Matches when                                  |
|----------------|---------------------|-----------------------------------------------|
| `STATIC`       | phrase (default)    | the whole sentence equals the phrase          |
| `STARTS_WITH`  | phrase              | the sentence starts with it (on a word boundary) |
| `ALL_KEYWORDS` | words               | every word occurs in the sentence, any order  |
| `SUBSTRING`    | regex               | the regex is found anywhere                   |
| `DYNAMIC`      | regex               | the regex matches the whole sentence          |

Named regex groups become keyword arguments. They are converted by the parameter's
`int`/`float` annotation, or by `converters={"name": func}` on the decorator, otherwise
passed as `str` (keeping the speaker's casing). Raise `CommandError("...")` from a handler
for a user-facing error; it is reported and the session continues.

## Design

```
src/voice_control/
  matching.py    pure: normalize() and match() for the five match types
  controller.py  @command, Controller (per-subclass command table), dispatch -> Result
  history.py     History / HistoryEntry: record, JSON save/load, replay by handler name
  backends.py    Recognizer protocol; TextRecognizer, ScriptedRecognizer,
                 SpeechRecognitionBackend (lazy import, google/sphinx), ALSA-noise muting
  session.py     listen -> dispatch -> report loop (stop words, help, history)
  apps.py        built-in HomeControl and PaintControl, load_app("module:Class")
  cli.py         argparse CLI; the recognizer factory is injectable for tests
```

Command matching and dispatch never touch audio: a backend only has to provide
`listen() -> str`, so the microphone can be swapped for stdin, a script or a fake.
History stores the handler name plus the *raw* captured strings, so replay re-runs the
same conversion and validation.

## Tests

```bash
pip install -e '.[dev]'
pytest
```

The suite covers matching, dispatch/conversion, the example apps, history round-trips
and replay, the session loop, the microphone backend (against a fake
`speech_recognition` module) and the CLI. It uses no microphone, network or home
directory.

## Known limitations

- **Not tested against real hardware or services.** The microphone path
  (PyAudio/PortAudio) and the Google/Sphinx engines are exercised only through fakes;
  only the "PyAudio missing" error path was checked with the real SpeechRecognition
  package.
- The Google engine sends audio to Google's free Web Speech API and needs internet.
- Numbers must be transcribed as digits ("10", not "ten"); recognizers usually do this,
  but there is no number-word parsing.
- `do` runs on a fresh controller each invocation; app state is not persisted between
  runs (use `replay` to rebuild it from a history file).
- The example apps only keep state in memory; they are demos of the framework, not
  integrations with a real smart-home or paint program.
