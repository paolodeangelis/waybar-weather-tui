# Development

This is a small personal Waybar / Hyprland utility, not a packaged Python application.

## Repo layout

- [scripts/weather.py](/home/paolo/Work/Projects/waybar-weather-tui/scripts/weather.py:1) is the main script
- [examples/waybar/config.jsonc](/home/paolo/Work/Projects/waybar-weather-tui/examples/waybar/config.jsonc:1) is the example Waybar config
- [examples/hypr/weather.conf](/home/paolo/Work/Projects/waybar-weather-tui/examples/hypr/weather.conf:1) is the example Hyprland config
- [etc/release.sh](/home/paolo/Work/Projects/waybar-weather-tui/etc/release.sh:1) updates the script version and creates the matching git tag

## Local usage

Waybar JSON mode:

```bash
python3 scripts/weather.py
```

TUI mode:

```bash
python3 scripts/weather.py --tui --colored --width 95 --days 6 --hours 24
```

Refresh cached data:

```bash
python3 scripts/weather.py --refresh
```

Show version:

```bash
python3 scripts/weather.py --version
```

## Notes

- the script is self-contained and keeps its version in `scripts/weather.py`
- it is designed to be copied and used directly, without Python packaging
- cache files are stored under `~/.cache/waybar-weather/`
- the TUI popup behavior is controlled by your terminal command plus Hyprland window rules

## Releasing

Use the helper script:

```bash
./etc/release.sh 0.1.1
```

That script:

- updates `__version__` in `scripts/weather.py`
- creates a release commit
- creates the matching annotated git tag

Then push manually:

```bash
git push
git push --tags
```

## Pre-commit

If you want to run the repo checks locally before pushing, install and enable `pre-commit`:

```bash
pre-commit install
pre-commit run --all-files
```

The repo includes a minimal [.pre-commit-config.yaml](/home/paolo/Work/Projects/waybar-weather-tui/.pre-commit-config.yaml:1) with a few basic checks.
