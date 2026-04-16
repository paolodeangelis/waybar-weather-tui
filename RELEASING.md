# Releasing

The project version is stored in `scripts/weather.py` as `__version__`.

To create a release:

```bash
./etc/release.sh 0.1.1
```

This will:

- update the version in the script
- commit the change with `release: v0.1.1`
- create the annotated git tag `v0.1.1`

Then push the branch and tags:

```bash
git push
git push --tags
```

Requirements:

- run the script from a clean git worktree
- use versions in `X.Y.Z` format
