# Biathlon CLI

A CLI to explore data from the IBU biathlon results API at https://biathlonresults.com.

No external dependencies - pure Python standard library.

## Installation

### From PyPI

```bash
pip install biathlon
```

### From source

```bash
git clone https://github.com/thbtmntgn/biathlon.git
cd biathlon
pip install .
```

### For development

```bash
git clone https://github.com/thbtmntgn/biathlon.git
cd biathlon
pip install -e .
```

## Usage

List available seasons:

```bash
biathlon seasons
```

List World Cup events from the current season:

```bash
biathlon events
```

List World Cup events for a specific season:

```bash
biathlon events --season 2425
```

List IBU Cup events for the current season:

```bash
biathlon events --level 2
```

List events with their races for the current season World Cup:

```bash
biathlon events --races
```

List sprint races for a specific season:

```bash
biathlon events --season 2425 --races --discipline sprint
```

Show results for the most recent World Cup race:

```bash
biathlon results
```

Show results for a specific race id:

```bash
biathlon results --race BT2526SWRLCP01SWSP
```

Show ski/range/shooting time breakdowns for a race:

```bash
biathlon results ski --race BT2526SWRLCP03SMMS
biathlon results range --race BT2526SWRLCP03SMMS
biathlon results shooting --race BT2526SWRLCP03SMMS
```

Show World Cup total standings (women, current season by default):

```bash
biathlon scores
```

Show men sprint standings for season 2425:

```bash
biathlon scores --season 2425 --men --sort sprint
```

Run without installing:

```bash
python -m biathlon.cli seasons
```

## Shell Completion

Enable tab completion for bash:

```bash
eval "$(biathlon --completion bash)"
```

Or add to your `~/.bashrc`:

```bash
source <(biathlon --completion bash)
```

For zsh, add to your `~/.zshrc`:

```zsh
source <(biathlon --completion zsh)
```

## Limitations

- **Relay races are not supported.** Commands like `results`, `shooting`, and `cumulate` filter out relay events. Only individual race formats (sprint, pursuit, individual, mass start) are included in statistics and rankings.

## License

MIT
