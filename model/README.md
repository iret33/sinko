# The host model

`host-model.json` is the small AI model the box uses to learn new addresses of blocked apps (`sinko learn`, off until it
is switched on). It reads a host name and says how sure it is that the name belongs to one of the apps in `lists/`, and
to which. How it works, how well it does and what it gets wrong: [`docs/maintainers/host-model.md`](../docs/maintainers/host-model.md).

| | |
|---|---|
| Made by | `python3 tools/suggest-hosts.py --save-model model/host-model.json` |
| Trained on | the block lists in `lists/` at the commit that adds the file (the guard list left out), and Cisco Umbrella's list of the million most looked-up names of 13 October 2026, as examples of ordinary names |
| Size | 481 KB (136 KB compressed): 22,065 pieces of names for the first stage, 4,331 for the second, 19 apps |
| Backtest | trained on the lists before #25, it found 15 of the 24 hosts #25 then added by hand (`--backtest 1ffee15`) |

The file holds pieces of the apps' own names (`D:tiktokcdn`, `G:^twi`), from the lists and from the apps' names that
Cisco's list holds, and numbers. No ordinary name of Cisco's list is in it: those only move the numbers. Cisco Umbrella's
popularity list is credited in [`NOTICE`](../NOTICE).

**Refreshing it.** Run the command above (or download `host-model.json` from a run of the *Host suggestions* workflow),
check `--backtest` and a review list made the same day, and change this table. A new app in `lists/` needs a new model:
`tests/test_learn.py` fails while the model does not know every app of the catalogue. Unlike the lists, which boxes fetch
every night, the model reaches a box only with a release.
