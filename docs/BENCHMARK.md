# Windows Calculator pilot

This was an exploratory test of one task in one app, with two matched
pairs. With VisumWay v0.2.5, signed-in Codex completed the Calculator task
in a median of **23.35 s**, versus **34.34 s** with the screenshot-only
path. The difference for these runs was **11.00 s**, or **32.02%**.

| Pair | Screenshot observation | VisumWay control observation | Correct result |
| --- | ---: | ---: | --- |
| 1 | 34.23 s | 23.36 s | Both |
| 2 | 34.45 s | 23.33 s | Both |

Codex read an unseen starting value from Windows Calculator, added 7,
checked the intermediate display, multiplied by 4 and verified the
final display. Both routes used the same window, prompt and keyboard
actions. The two pairs used different starting values and opposite run
orders. The timer included signed-in Codex startup, reasoning,
observations and input. Calculator reset and seeding were outside the timer.

The screenshot path used the Codex computer-use screenshot tool. The
VisumWay path used `inspect_window` to read the Calculator accessibility
tree. Median observation time was **3.21 s** for the screenshot tool and
**81.4 ms** for VisumWay in this setup. Codex made one extra observation in
each screenshot run. Both screenshot runs produced the correct values.

One earlier pilot pair was excluded after a refresh error and a different
refresh cadence. The retained pairs demonstrate the workflow. Two pairs
are too few to estimate a general speedup or compare against other
accessibility tools. [Raw timings and observations](benchmarks/windows-calculator-v0.2.5.json)

## Local payload measurements

A separate disposable-window test measured the tool traffic before model
processing. Across nine runs, a named-control read returned 579 bytes
over MCP and took a median of 84.6 ms. An 820-pixel window capture
returned 49,025 bytes and took a median of 357.8 ms. These measurements
apply to that fixture and capture size.
[Control inspection test record](VERIFICATION.md#v025--read-windows-controls-directly)

## Next comparison

Run at least ten matched pairs with the same agent version, prompt, app,
and input actions. Alternate the first method, vary the seed, and retain
the results of each attempt, including timeouts and incorrect answers.
Report task completion rate and end-to-end duration alongside observation
time and payload size. To make a claim across desktop workflows, repeat
the comparison in apps with different accessibility coverage.
