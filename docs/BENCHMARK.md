# Windows Calculator benchmark

With VisumWay v0.2.5, signed-in Codex completed the Calculator task in a
median of **23.35 s**, versus **34.34 s** with the screenshot-only path.
That is **11.00 s less time**, or **32.02%**, in this benchmark.

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

This measures one app and one task. The result does not establish a speedup
over other accessibility tools or across arbitrary desktop workflows.
See the [raw timings and observations](benchmarks/windows-calculator-v0.2.5.json).
