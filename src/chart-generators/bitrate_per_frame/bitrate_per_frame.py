#!/usr/bin/env python3
"""
Bitrate per Frame Chart Generator

This script generates a line chart showing bitrate (in kbps) over time (per
frame) for a single scenario, plotting one line per strategy (e.g.,
round-robin, random-selection, memory-monitoring-6s, memory-monitoring-30s).

The script reads configuration from a JSON file that contains:
- datasets: { "scenario-1": { "round-robin": [..], "random-selection": [..], ... }, ... }
- chart_settings: Appearance settings (colors, sizes, labels, dpi, etc.)

Usage:
    python bitrate_per_frame.py --config config.json --scenario scenario-1 > chart.png
    python bitrate_per_frame.py --config config.json --scenario scenario-1 | tee chart.png
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
from typing import Dict, Any, List


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


def _normalize_strategy_name(name: str) -> str:
    n = name.strip().lower()
    mapping = {
        'round robin': 'Round Robin',
        'round-robin': 'Round Robin',
        'round_robin': 'Round Robin',
        'random selection': 'Random Selection',
        'random-selection': 'Random Selection',
        'random_selection': 'Random Selection',
        'memory monitoring': 'Memory Monitoring',
        'memory-monitoring': 'Memory Monitoring',
        'memory_monitoring': 'Memory Monitoring',
        'memory-monitoring-6s': 'Memory Monitoring (6s)',
        'memory-monitoring-30s': 'Memory Monitoring (30s)',
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
    """Resolve the output file path for a scenario.

    Rules:
    - If output_path contains '{scenario}', format it.
    - If output_path is a directory or ends with a path separator, write <dir>/<scenario>.png.
    - If output_path is a file path with extension, append _<scenario> before extension.
    - If output_path is a file path without extension, treat as directory.
    """
    if '{scenario}' in output_path:
        resolved = output_path.format(scenario=scenario)
    else:
        # Determine if it's a directory
        is_dir_hint = output_path.endswith(os.sep) or output_path.endswith('/') or not os.path.splitext(output_path)[1]
        if is_dir_hint or os.path.isdir(output_path):
            resolved = os.path.join(output_path, f"{scenario}.png")
        else:
            base, ext = os.path.splitext(output_path)
            if not ext:
                resolved = os.path.join(output_path, f"{scenario}.png")
            else:
                resolved = f"{base}_{scenario}{ext}"
    # Ensure directory exists
    directory = os.path.dirname(resolved)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    return resolved


def create_bitrate_charts(config: Dict[str, Any], output_path: str) -> None:
    """Create and save bitrate charts for all scenarios."""
    all_datasets: Dict[str, Any] = config['datasets']
    chart_settings: Dict[str, Any] = config.get('chart_settings', {})

    figure_size = tuple(chart_settings.get('figure_size', [12, 8]))
    colors = chart_settings.get('colors', ['#1f77b4', '#ff7f0e', '#2ca02c'])
    line_width = float(chart_settings.get('line_width', 2))
    marker_size = float(chart_settings.get('marker_size', 3))
    dpi = int(chart_settings.get('dpi', 300))

    base_title = chart_settings.get('title', 'Bitrate per Frame')

    # Consistent strategy colors across all scenarios (fixed palette)
    strategy_order = ['round-robin', 'random-selection', 'memory-monitoring-6s', 'memory-monitoring-30s']
    strategy_color_map: Dict[str, str] = {
        'round-robin': '#d62728',            # red
        'random-selection': '#ff7f0e',       # orange
        'memory-monitoring-6s': '#2ca02c',   # green
        'memory-monitoring-30s': '#1f77b4',  # blue
    }

    for scenario, scenario_series in all_datasets.items():
        if not isinstance(scenario_series, dict):
            continue
        plt.figure(figsize=figure_size)
        plt.style.use('default')

        # Order strategies consistently
        ordered = [k for k in strategy_order if k in { _canonical_strategy_key(s): None for s in scenario_series.keys() }]
        # Map original keys to canonical to preserve original labels
        canonical_to_original = {}
        for orig in scenario_series.keys():
            canonical_to_original[_canonical_strategy_key(orig)] = orig
        # Append any remaining strategies deterministically
        for k in sorted(canonical_to_original.keys()):
            if k not in ordered:
                ordered.append(k)

        scenario_max = 0.0
        scenario_min_positive = None
        for i, canonical in enumerate(ordered):
            orig_key = canonical_to_original.get(canonical, canonical)
            bitrate_values = scenario_series.get(orig_key, [])
            if not bitrate_values:
                continue
            frame_numbers = np.arange(1, len(bitrate_values) + 1)
            # Keep values in Kbps
            y_values = [float(v) for v in bitrate_values]
            if y_values:
                scenario_max = max(scenario_max, max(y_values))
                for _v in y_values:
                    if _v > 0 and (scenario_min_positive is None or _v < scenario_min_positive):
                        scenario_min_positive = _v
            # color by canonical strategy for consistency
            color = strategy_color_map.get(canonical, colors[i % len(colors)])
            # Replace non-positive values to a small epsilon for log-scale visibility
            eps = (scenario_min_positive * 0.1) if (scenario_min_positive and scenario_min_positive > 0) else 1.0
            safe_y = [v if v > 0 else eps for v in y_values]
            plt.plot(
                frame_numbers,
                safe_y,
                label=_normalize_strategy_name(orig_key),
                linewidth=line_width,
                marker='o',
                markersize=marker_size,
                color=color,
                linestyle=':',
                alpha=0.9,
                markeredgecolor='white',
                markeredgewidth=0.7,
            )

        plt.xlabel(chart_settings.get('x_label', 'Frame Number'), fontsize=12, fontweight='bold')
        # Y-axis: Kbps on logarithmic scale
        plt.ylabel('Bitrate (Kbps)', fontsize=12, fontweight='bold')
        plt.yscale('log')
        plt.title(f"{base_title} - {scenario}", fontsize=14, fontweight='bold', pad=20)

        if 'y_axis_limits' in chart_settings:
            y_min, y_max = chart_settings['y_axis_limits']
            # Ensure y_min > 0 for log scale
            try:
                y_min = max(1.0, float(y_min))
                y_max = float(y_max)
            except Exception:
                y_min, y_max = None, None
            upper = max(float(y_max) if y_max else 0.0, scenario_max * 1.05 if scenario_max else 1.0)
            lower = max(1.0, float(y_min) if y_min else (scenario_min_positive * 0.8 if scenario_min_positive else 1.0))
            if lower >= upper:
                upper = lower * 10.0
            plt.ylim(lower, upper)
        else:
            # Auto-scale based on data for log scale
            upper = scenario_max * 1.05 if scenario_max else 1.0
            lower = max(1.0, (scenario_min_positive * 0.8) if (scenario_min_positive and scenario_min_positive > 0) else 1.0)
            if upper <= lower:
                upper = lower * 10.0
            plt.ylim(lower, upper)

        plt.grid(True, alpha=0.3, linestyle='--')
        plt.legend(loc='upper right', frameon=True, shadow=True)
        plt.tight_layout()

        out_file = _resolve_output_path(output_path, scenario)
        plt.savefig(out_file, format='png', dpi=dpi, bbox_inches='tight')
        print(f"Saved: {out_file}", file=sys.stderr)
        plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a bitrate per frame chart and output to stdout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bitrate_per_frame.py --config config.json > chart.png
  python bitrate_per_frame.py --config config.json | tee chart.png
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
        print("Generating bitrate charts for all scenarios...", file=sys.stderr)
        create_bitrate_charts(config, args.output)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


