#!/usr/bin/env python3
"""
Stalls por Frame Chart Generator

This script generates a grouped bar chart showing duração de parada (in seconds)
por frame for a single scenario. Within the selected scenario, it plots one
bar per strategy (e.g., round-robin, random-selection, memory-monitoring-6s,
memory-monitoring-30s) for each frame.

The script reads configuration from a JSON file that contains:
- datasets: { "scenario-1": { "round-robin": [{"segment": n, "seconds": x}, ...], ... }, ... }
- chart_settings: Appearance settings (colors, sizes, labels, dpi, bar width, etc.)

Usage:
    python stalls_per_frame.py --config config.json --output ./out_dir/

The JSON configuration file should contain:
- datasets: { "scenario-1": {"round-robin": [{"segment": 2, "seconds": 0.0}, ...], ...}, ... }
- chart_settings: { "figure_size": [12, 8], "colors": ["#..."], "bar_width": 0.25, "dpi": 300,
                   "title": "...", "x_label": "Número do Frame", "y_label": "Tempo de Parada (s)",
                   "y_axis_limits": [0, 1] }
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import sys
import os
import io
from typing import Dict, List, Any


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file '{config_path}' not found.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading configuration file '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)


def aggregate_stalls(dataset_entries: List[Dict[str, Any]]) -> Dict[int, float]:
    """Aggregate tempo de parada por frame, summing where frames repeat."""
    stalls_per_segment: Dict[int, float] = {}
    for entry in dataset_entries:
        segment = int(entry.get('segment', 0))
        seconds = float(entry.get('seconds', 0.0))
        stalls_per_segment[segment] = stalls_per_segment.get(segment, 0.0) + seconds
    return stalls_per_segment


def _normalize_strategy_name(name: str) -> str:
    n = name.strip().lower()
    mapping = {
        'round robin': 'Round Robin',
        'round-robin': 'Round Robin',
        'round_robin': 'Round Robin',
        'random selection': 'Seleção Aleatória',
        'random-selection': 'Seleção Aleatória',
        'random_selection': 'Seleção Aleatória',
        'memory monitoring': 'Monitoramento de Memória',
        'memory-monitoring': 'Monitoramento de Memória',
        'memory_monitoring': 'Monitoramento de Memória',
        'memory-monitoring-6s': 'Monitoramento de Memória (6s)',
        'memory-monitoring-30s': 'Monitoramento de Memória (30s)',
    }
    return mapping.get(n, name)


def _canonical_strategy_key(name: str) -> str:
    n = name.strip().lower()
    if n in ('round robin', 'round-robin', 'round_robin'):
        return 'round-robin'
    if n in ('random selection', 'random-selection', 'random_selection'):
        return 'random-selection'
    if n in ('memory monitoring 6s', 'memory-monitoring-6s', 'memory_monitoring_6s'):
        return 'memory-monitoring-6s'
    if n in ('memory monitoring 30s', 'memory-monitoring-30s', 'memory_monitoring_30s'):
        return 'memory-monitoring-30s'
    if n in ('memory monitoring', 'memory-monitoring', 'memory_monitoring'):
        return 'memory-monitoring'
    return n


def _resolve_output_path(output_path: str, scenario: str) -> str:
    if '{scenario}' in output_path:
        resolved = output_path.format(scenario=scenario)
    else:
        is_dir_hint = output_path.endswith(os.sep) or output_path.endswith('/') or not os.path.splitext(output_path)[1]
        if is_dir_hint or os.path.isdir(output_path):
            resolved = os.path.join(output_path, f"{scenario}.png")
        else:
            base, ext = os.path.splitext(output_path)
            if not ext:
                resolved = os.path.join(output_path, f"{scenario}.png")
            else:
                resolved = f"{base}_{scenario}{ext}"
    directory = os.path.dirname(resolved)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    return resolved


def create_stalls_charts(config: Dict[str, Any], output_path: str) -> None:
    """Create and save stalls charts for all scenarios."""
    all_datasets: Dict[str, Any] = config['datasets']
    chart_settings: Dict[str, Any] = config['chart_settings']

    # Plot settings
    figure_size = tuple(chart_settings.get('figure_size', [12, 8]))
    colors = chart_settings.get('colors', ['#1f77b4', '#ff7f0e', '#2ca02c'])
    bar_width = float(chart_settings.get('bar_width', 0.25))
    dpi = int(chart_settings.get('dpi', 300))

    for scenario, scenario_series in all_datasets.items():
        if not isinstance(scenario_series, dict):
            continue

        # Clamp to full segment range [1..22]
        all_segments = list(range(1, 23))

        aggregated: Dict[str, Dict[int, float]] = {
            strategy: aggregate_stalls(entries) for strategy, entries in scenario_series.items()
        }
        values_per_strategy: Dict[str, List[float]] = {
            strategy: [aggregated[strategy].get(seg, 0.0) for seg in all_segments]
            for strategy in scenario_series.keys()
        }

        plt.figure(figsize=figure_size)
        plt.style.use('default')

        indices = np.arange(len(all_segments), dtype=float)

        # Consistent color per strategy (fixed palette)
        strategy_order = ['round-robin', 'random-selection', 'memory-monitoring-6s', 'memory-monitoring-30s']
        strategy_color_map: Dict[str, str] = {
            'round-robin': '#d62728',            # red
            'random-selection': '#ff7f0e',       # orange
            'memory-monitoring-6s': '#2ca02c',   # green
            'memory-monitoring-30s': '#1f77b4',  # blue
        }

        labeled_strategies: Dict[str, bool] = {}
        draw_width = min(0.8, bar_width if bar_width else 0.6)

        # Draw at each segment: taller first, shorter last (in front)
        for seg_idx, seg in enumerate(all_segments):
            segment_pairs = []
            for strategy_name, values in values_per_strategy.items():
                v = float(values[seg_idx]) if seg_idx < len(values) else 0.0
                segment_pairs.append((v, strategy_name))
            segment_pairs.sort(key=lambda x: x[0], reverse=True)

            for value, strategy_name in segment_pairs:
                canonical = _canonical_strategy_key(strategy_name)
                color = strategy_color_map.get(canonical, colors[0])
                show_label = strategy_name not in labeled_strategies
                plt.bar(
                    indices[seg_idx],
                    value,
                    width=draw_width,
                    label=_normalize_strategy_name(strategy_name) if show_label else "__nolegend__",
                    color=color,
                    alpha=0.9,
                    edgecolor='black',
                    linewidth=0.4,
                )
                labeled_strategies[strategy_name] = True
        
        # Convert scenario name to Portuguese
        scenario_pt = scenario.replace('scenario-', 'Cenário ')
        
        plt.xlabel(chart_settings.get('x_label', 'Número do Frame'), fontsize=12, fontweight='bold')
        plt.ylabel(chart_settings.get('y_label', 'Tempo de Parada (s)'), fontsize=12, fontweight='bold')
        plt.title(chart_settings.get('title', 'Duração de Parada por Frame') + f" - {scenario_pt}", fontsize=14, fontweight='bold', pad=20)

        plt.xticks(indices, [str(s) for s in all_segments])

        # Dynamic upper limit based on data
        scenario_max = 0.0
        for vals in values_per_strategy.values():
            if vals:
                scenario_max = max(scenario_max, max(vals))
        y_min = 0.0
        if 'y_axis_limits' in chart_settings:
            try:
                y_min = float(chart_settings['y_axis_limits'][0])
            except Exception:
                y_min = 0.0
        y_upper = scenario_max * 1.1 if scenario_max else 1.0
        if y_upper <= y_min:
            y_upper = y_min + 1.0
        plt.ylim(y_min, y_upper)

        plt.grid(True, axis='y', alpha=0.3, linestyle='--')
        # Build legend in consistent strategy order for those present
        from matplotlib.patches import Patch
        handles = []
        labels = []
        present = set(values_per_strategy.keys())
        for key in strategy_order:
            # map canonical to original label if present
            for strat in present:
                if _canonical_strategy_key(strat) == key:
                    handles.append(Patch(facecolor=strategy_color_map.get(key, '#7f7f7f'), edgecolor='black', linewidth=0.4))
                    labels.append(_normalize_strategy_name(strat))
                    break
        if handles:
            plt.legend(handles, labels, loc='upper right', frameon=True, shadow=True)
        plt.tight_layout()

        out_file = _resolve_output_path(output_path, scenario)
        plt.savefig(out_file, format='png', dpi=dpi, bbox_inches='tight')
        print(f"Saved: {out_file}", file=sys.stderr)
        plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a grouped bar chart of tempo de parada por frame and output to stdout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python stalls_per_frame.py --config config.json > chart.png
  python stalls_per_frame.py --config config.json | tee chart.png
        """
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config.json',
        help='Path to JSON configuration file (default: config.json)'
    )
    parser.add_argument(
        '--output',
        type=str,
        required=True,
        help='Output path. Use a directory, a file path, or a pattern with {scenario}.'
    )

    args = parser.parse_args()

    try:
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        print("Generating stalls charts for all scenarios...", file=sys.stderr)
        create_stalls_charts(config, args.output)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


