# app/interact: driving our own programs

A small framework for clicking and typing in programs of our own, so the self-test, the demo
table and PokerScribe's own windows can be driven and checked automatically. It is kept apart
from the poker engine: it doesn't decide moves, and the engine doesn't know it exists.

## What it can and can't drive (rule 4)

It can drive three things, all inside the Python process that runs it:

- **The simulator's game** (`SimBackend`): a "click" is a call to `tools/simulate.py`'s `act()`
  on a `Hand` object in memory.
- **The demo table** (`DemoTableBackend`): it draws the picture itself from the simulator's
  game (`app/tests/demo_table.py`), and a "click" is checked against where that picture's
  buttons were drawn, then made in the game with `act()`. It takes no picture from anywhere
  else: there is no way to hand it a screenshot.
- **Our own Qt windows** (`QtBackend`): the targets are named QWidget objects of this program.
  QtTest delivers events to those objects; the computer's pointer doesn't move and the events
  never leave the process.

It can't drive anything else: no other program's window, no browser, no poker client, not
even play-money 247 (rule 4 in `docs/research/README.md`; Kevin, 27 Nov: "Do not implement
live poker client integration or mechanisms designed to evade platform bot detection."). There
is no pointer movement of any kind and no backend for the system pointer or keyboard.

How that is enforced in code, not by convention:

- `app/tests/test_interact.py::test_nothing_in_the_repository_can_drive_another_program` scans
  every source file in the repository (Python, shell, JavaScript, Swift, Rust; not only
  `app/interact`) and fails on anything that can move the system pointer, press system keys or
  act in another program's window: the input libraries (pyautogui, pynput, pywinauto, Quartz,
  AppKit, Xlib, evdev and others), the macOS, Windows and X11 calls by name (`CGEventPost`,
  `CGEventCreate...`, `CGWarpMouseCursorPosition`, `SendInput`, `mouse_event`, `SetCursorPos`,
  `XTestFake...`), the command-line tools (`xdotool`, `cliclick`, `osascript`), AppleScript's
  System Events, accessibility actions (`AXUIElement...`), `QCursor.setPos` and
  `QWindow.fromWinId`. Browsers too, since 247 is a browser game: browser automation in Python,
  JavaScript or TypeScript (playwright, selenium, pyppeteer, puppeteer, webdriver and the like),
  the Chrome DevTools input calls (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`,
  `Input.insertText`) and Qt's web engine (`QtWebEngine...`, `QWebEngine...`). It also fails on
  any Rust input or browser crate (enigo, rdev, autopilot, headless_chrome, chromiumoxide,
  fantoccini, thirtyfour and others) in a `Cargo.toml`, and on any of those packages in a
  requirements file (and on PySide6-Addons, the Qt build that ships the web engine).
  `test_the_scan_would_catch_each_way_in` checks the scan catches each of those, and doesn't
  catch what the app does itself (its own cursor shape, the screen-capture permission check,
  its own requirements).
- `test_interact_drives_nothing_outside_our_own_programs` fails if `app/interact` or its
  backends import ctypes or subprocess at all.
- `QtBackend` takes only a QWidget, and refuses (at the start and on every look at its targets)
  a window holding anything but our own widgets: a window container or a foreign window made
  from another program's window id (`test_a_window_holding_another_window_is_refused`), a web
  view, a QML scene that could host one, or an ActiveX control, a subclass of one included
  (`test_a_web_view_or_qml_scene_in_our_window_is_refused`). A key with no target goes to the
  widget with the focus only if it is in the window driven, else to the window itself
  (`test_a_key_without_a_target_stays_in_our_window`).
- The import test keeps the framework and the poker engine apart, both ways: the advice, the
  solver and the reader can't use it.

## How it fits together

- `app/interact/intents.py`: a `Target` (a named box: "call", "amount", a widget's object
  name, with its label and whether it's shown and enabled), the steps (`Click`, `TypeText`,
  `PressKey`), an `Expect` (a state to see afterwards, checked on the backend's `snapshot()`),
  and a `Plan` (steps, an optional state required before the first, the caller's notes).
- `app/interact/backend.py`: what a backend implements: `targets()`, `click()`, `type_text()`,
  `press_key()`, `snapshot()`, and `invoke()`, where its calls run (a thread of its own by
  default, the GUI thread for Qt).
- `app/interact/runner.py`: the `Runner`. Plans run one at a time, in order, on the runner's own
  thread; `submit()` returns at once with a Future, `run()` waits. Before acting, each step finds
  its target and checks it is shown and enabled; afterwards it waits for the step's expected
  state (and can try again, `retries`). `Settings`: clicking and keys switched on or off
  separately (a plan needing what is off is skipped whole, so an amount is never typed without
  its click), dry run (every target found and checked, nothing done), timeouts, a JSON lines
  log of every step and plan. `stop()` is the emergency stop: waiting plans are dropped, the plan
  under way ends before its next step or at once if it is waiting for a state, new plans are
  refused until `reset()`. `Runner.stop_all()` stops every runner. A backend call that doesn't
  return in time stops the runner too, since it may still act late.
- `app/interact/moves.py`: `plan_for_move(kind, amount, targets)` turns a poker move (fold,
  check, call, bet or raise to an amount) into a plan: the button, with the amount typed first
  when there is an amount box. It refuses (PlanError) what it can't do as asked, and never turns
  one move into another: a fold with no Fold button is refused, not made a check.
- `app/interact/qt.py`: `QtBackend(window)`: the window's named widgets (buttons, line edits,
  combo and spin boxes) are the targets. A plan on it must be submitted, not waited for, on the
  GUI thread (`run()` there raises), and the window keeps running meanwhile.
- `tools/interact_backends.py`: `SimBackend`, the hero's buttons in the simulator's game (as the
  self-test's table shows them) and an amount box; `DemoTableBackend`, the demo table's picture,
  where the targets are the buttons the reader finds and each click is checked against where the
  button was really drawn.
- `tools/selftest.py --interact`: your moves go through the runner on `SimBackend` instead of
  being made directly. `applied_move()` first works out the move the simulator really makes (a
  raise under the minimum is the minimum, one you can't make is a call), so the plan asks for
  exactly that; amounts are typed with `repr`, so they are read back as the same number.

## Checks

- `app/tests/test_interact.py`: order and the runner's own thread, submit not waiting, dry run,
  switches, missing, hidden and switched-off targets, expected states waited for and retried,
  required states, the emergency stop (under way, waiting, refused until reset, every runner),
  a hanging backend, backend errors, the log, no CPU while idle; moves as plans and the moves
  refused; every kind of move through the runner on `SimBackend` leaves the game exactly as
  making it directly; what the package may import, both ways.
- `app/tests/test_interact_qt.py`: clicks, typing and keys reach our own widgets; switched-off,
  hidden and missing ones are left alone; a QTimer keeps firing while a plan waits (the GUI
  thread is never blocked); waiting on the GUI thread is refused; dry run.
- `app/tests/test_interact_demo.py`: on the demo table at 0.75, 1 and 1.5 times its size, and
  on the column and phone layouts, every button the reader finds has its middle on the button
  drawn there; the call is made and the buttons are gone when the table is read again; a raise
  by the amount on its button; a click off its button is caught and nothing is played; and the
  self-test plays the same game, every count equal, with `--interact` and without.
- `tools/interact_timing.py`: the timings below.

## Timings

`python tools/interact_timing.py`, 27 Nov, on the 4-core cloud machine with a self-test running
beside it (load about 4), Qt offscreen:

| What | Plans | p50 ms | p95 ms | max ms |
| --- | --- | --- | --- | --- |
| submit() returns (the caller is held up) | 2000 | 0.020 | 0.027 | 0.061 |
| a click on a backend that does nothing (the runner's own time) | 2000 | 0.136 | 0.190 | 8.019 |
| simulator: type the amount, click raise, check the turn is over | 2000 | 0.376 | 0.650 | 9.067 |
| Qt window: click a button, check it was clicked | 200 | 0.570 | 6.081 | 11.654 |
| stop() to the end of a plan that is waiting | 40 | 0.070 | 0.144 | 0.150 |

An idle runner uses no CPU (0.00% of one core over 2 s: its thread waits on its queue). The
runner's own cost is a fraction of a millisecond, so a move takes as long as the backend: on
the demo table that is the reading of the picture afterwards (a second or two), which is why
its tests give the runner a long `call_timeout`. The time a plan takes doesn't depend on how
long the advice took to decide it: the advice runs before the plan is submitted, and the
runner neither waits for nor slows it.
