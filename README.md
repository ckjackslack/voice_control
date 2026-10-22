# voice_control

> **DRAFT** — initial assessment only. This README is unfinished on purpose; see
> "TODO / to be finished" below.

## What this seems to be

A small framework for **controlling an application by spoken commands**. The idea in
`src/voice.py`:

- capture speech from the microphone with `SpeechRecognition` and transcribe it
  (Google Web Speech API),
- match the transcribed text against command patterns registered with a
  `@register_action(pattern, match_type)` decorator on methods of a "control" class,
- run the matching handler (e.g. `TestControl.turn_on_light`, or a dynamic
  `PaintAppControl.make_rectangle(width, height, position)` whose arguments are pulled
  from the sentence by a regex with named groups),
- keep a history of executed commands, save it to JSON and replay it later.

## Current state

What works:

- Static matching modes `SUBSTRING`, `STARTS_WITH`, `ALL_KEYWORDS` in `is_match`.
- The basic microphone → Google recognizer → print loop (on a machine with a mic,
  PyAudio and internet).

What is broken / missing:

- `sr.Microphone()` is created at **class definition / import time**, so merely importing
  the module crashes on machines without a microphone or PyAudio.
- A single module-global `_action_registry` is shared by *all* control classes, so
  `PaintAppControl` also "has" the `TestControl` commands and vice versa.
- `DYNAMIC` and `STATIC` match types are declared but not handled by `is_match`; handlers
  are always called without arguments, so `make_rectangle` can never work. The working
  version only exists as commented-out code.
- History is never recorded (`add_to_history` is never called), and
  `load_and_replay_history` looks handlers up by action *name* in a registry keyed by
  *pattern*, so replay would raise `KeyError`.
- `main()` does nothing (everything is commented out); there is no CLI.
- `import sounddevice` is an unused import used only as a side-effect hack to silence
  ALSA warnings.
- Error strings ("API unavailable") are returned as if they were recognized speech and then
  dispatched as commands.
- No package metadata, no tests. Nothing sensitive (secrets/paths) in the code.

## TODO / to be finished

- [ ] Redesign as a package with a pluggable speech backend
- [ ] Per-class command registries, working dynamic commands with typed arguments
- [ ] History save / replay
- [ ] CLI, usage docs, tests
