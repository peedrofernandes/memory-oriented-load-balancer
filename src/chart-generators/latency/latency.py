#!/usr/bin/env python3
"""
Latency Chart Generator

Reads a JSON mapping of scenario -> latency value and generates a bar chart.
X-axis: scenario names, Y-axis: numeric values (latency).

Supports optional chart_settings in the JSON for appearance control.

Usage:
    python latency.py --config config.json > chart.png
    python latency.py --config config.json | tee chart.png

JSON format examples:
1) Simple mapping only:
{
  "scenario-a": 123.4,
  "scenario-b": 98.7
}

2) With chart_settings:
{
  "data": { "scenario-a": 123.4, "scenario-b": 98.7 },
  "chart_settings": {
    "figure_size": [12, 8],
    "colors": ["#1f77b4"],
    "dpi": 300,
    "title": "Latency by Scenario",
    "x_label": "Scenario",
    "y_label": "Latency (ms)",
    "y_axis_limits": [0, 500]
  }
}
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import sys
import os
import io
from typing import Dict, Any, Tuple


def load_config(config_path: str) -> Dict[str, Any]:
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


def extract_data_and_settings(config: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, Any]]:
    if isinstance(config, dict) and 'data' in config:
        data = config['data']
        settings = config.get('chart_settings', {})
    else:
        data = config
        settings = {}
    return data, settings


def create_bar_chart(data: Dict[str, float], settings: Dict[str, Any], output_path: str) -> None:
    def get_scenario_group(name: str) -> str:
        # Expect keys like 'scenario-1-round-robin'; group is 'scenario-1'
        parts = name.split('-')
        for i in range(len(parts)):
            if parts[i].lower() == 'scenario' and i + 1 < len(parts):
                return f"scenario-{parts[i+1]}"
        # fallback: first token
        return parts[0]

    def display_group_label(group: str) -> str:
        # scenario-1 -> Scenario 1
        if group.startswith('scenario-'):
            return 'Scenario ' + group.split('-', 1)[1]
        return group.title()

    scenarios = list(data.keys())
    values = [float(data[k]) for k in scenarios]
    groups = [get_scenario_group(s) for s in scenarios]

    figure_size = tuple(settings.get('figure_size', [12, 8]))
    colors = settings.get('colors', None)
    dpi = int(settings.get('dpi', 300))

    plt.figure(figsize=figure_size)
    plt.style.use('default')

    indices = np.arange(len(scenarios))
    # Assign colors by scenario group
    fallback_palette = colors if colors else ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    group_color_map: Dict[str, str] = {}
    color_index = 0
    for g in groups:
        if g not in group_color_map:
            group_color_map[g] = fallback_palette[color_index % len(fallback_palette)]
            color_index += 1
    bar_colors = [group_color_map[g] for g in groups]
    plt.bar(indices, values, color=bar_colors, edgecolor='black', linewidth=0.4)

    plt.xlabel(settings.get('x_label', 'Scenario'), fontsize=12, fontweight='bold')
    plt.ylabel(settings.get('y_label', 'Latency (ms)'), fontsize=12, fontweight='bold')
    plt.title(settings.get('title', 'Latency by Scenario'), fontsize=14, fontweight='bold', pad=20)
    plt.xticks(indices, scenarios, rotation=45, ha='right')

    # Dynamic upper limit based on data
    v_max = max(values) if values else 0.0
    y_min = 0.0
    if 'y_axis_limits' in settings:
        try:
            y_min = float(settings['y_axis_limits'][0])
        except Exception:
            y_min = 0.0
    upper = v_max * 1.1 if v_max else 1.0
    if upper <= y_min:
        upper = y_min + 1.0
    plt.ylim(y_min, upper)

    plt.grid(True, axis='y', alpha=0.3, linestyle='--')
    seen = []
    handles = []
    for g in groups:
        if g not in seen:
            seen.append(g)
            handles.append(mpatches.Patch(color=group_color_map[g], label=display_group_label(g)))
    if handles:
        plt.legend(handles=handles, loc='upper right', frameon=True, shadow=True)
    plt.tight_layout()

    directory = os.path.dirname(output_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    plt.savefig(output_path, format='png', dpi=dpi, bbox_inches='tight')
    plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a bar chart of latency by scenario and output to stdout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python latency.py --config config.json > chart.png
  python latency.py --config config.json | tee chart.png
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
        help='Output file path for the latency chart PNG'
    )

    args = parser.parse_args()

    try:
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        data, settings = extract_data_and_settings(config)
        print("Generating latency chart...", file=sys.stderr)
        create_bar_chart(data, settings, args.output)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


