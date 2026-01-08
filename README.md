# Biathlon CLI

A CLI to explore data from the IBU biathlon results API at https://biathlonresults.com.

No external dependencies - pure Python standard library.

## Installation

### From GitHub

```bash
pip install git+https://github.com/thbtmntgn/biathlon.git
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

List World Cup events for specific seasons:

```bash
biathlon events --seasons 2425,2324
```

List IBU Cup and IBU Cup Junior events for the current season:

```bash
biathlon events --levels 2,3
```

List races (all event types) for the current season World Cup:

```bash
biathlon races
```

List sprint and mass-start races across specific seasons:

```bash
biathlon races --seasons 2425,2324 --types sprint,mass
```

List races for specific events:

```bash
biathlon races --events BT2526SWRLCP01,BT2526SWRLCP02
```

Show results for the most recent World Cup race:

```bash
biathlon results
```

Show results for a specific race id:

```bash
biathlon results --race BT2526SWRLCP01SWSP
```

Show course/range/shooting time breakdowns for a race:

```bash
biathlon results course --race BT2526SWRLCP03SMMS
biathlon results range --race BT2526SWRLCP03SMMS
biathlon results shooting --race BT2526SWRLCP03SMMS
```

Show World Cup total standings (women, current season by default):

```bash
biathlon scores
```

Show men sprint standings for season 2425:

```bash
biathlon scores --season 2425 --gender men --type sprint
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
