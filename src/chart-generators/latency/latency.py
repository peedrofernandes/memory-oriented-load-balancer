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


def create_bar_chart(data: Dict[str, float], settings: Dict[str, Any]) -> None:
    def get_category_from_name(name: str) -> str:
        if '-' in name:
            return name.split('-')[-2] + '-' + name.split('-')[-1] if name.endswith(('round-robin','random-selection','memory-monitoring')) else name.split('-')[-1]
        return name

    def normalize_category(cat: str) -> str:
        c = cat.strip().lower()
        if c in ("round robin", "round-robin", "round_robin"): return "round-robin"
        if c in ("random selection", "random-selection", "random_selection"): return "random-selection"
        if c in ("memory monitoring", "memory-monitoring", "memory_monitoring"): return "memory-monitoring"
        return c

    def display_label(cat: str) -> str:
        labels = {
            "round-robin": "Round Robin",
            "random-selection": "Random Selection",
            "memory-monitoring": "Memory Monitoring",
        }
        return labels.get(cat, cat.title())

    scenarios = list(data.keys())
    values = [float(data[k]) for k in scenarios]
    raw_categories = [get_category_from_name(s) for s in scenarios]
    categories = [normalize_category(c) for c in raw_categories]

    figure_size = tuple(settings.get('figure_size', [12, 8]))
    colors = settings.get('colors', ['#1f77b4'])
    dpi = int(settings.get('dpi', 300))

    plt.figure(figsize=figure_size)
    plt.style.use('default')

    indices = np.arange(len(scenarios))
    default_category_colors: Dict[str, str] = {
        "round-robin": "#1f77b4",
        "random-selection": "#ff7f0e",
        "memory-monitoring": "#2ca02c",
    }
    category_colors: Dict[str, str] = settings.get('category_colors', default_category_colors)
    fallback_color = colors[0 % len(colors)] if colors else "#7f7f7f"
    bar_colors = [category_colors.get(cat, fallback_color) for cat in categories]
    plt.bar(indices, values, color=bar_colors)

    plt.xlabel(settings.get('x_label', 'Scenario'), fontsize=12, fontweight='bold')
    plt.ylabel(settings.get('y_label', 'Latency (ms)'), fontsize=12, fontweight='bold')
    plt.title(settings.get('title', 'Latency by Scenario'), fontsize=14, fontweight='bold', pad=20)
    plt.xticks(indices, scenarios, rotation=45, ha='right')

    if 'y_axis_limits' in settings:
        y_min, y_max = settings['y_axis_limits']
        plt.ylim(float(y_min), float(y_max))

    plt.grid(True, axis='y', alpha=0.3, linestyle='--')
    seen = []
    handles = []
    for cat in categories:
        if cat not in seen:
            seen.append(cat)
            handles.append(mpatches.Patch(color=category_colors.get(cat, fallback_color), label=display_label(cat)))
    if handles:
        plt.legend(handles=handles, loc='upper right', frameon=True, shadow=True)
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=dpi, bbox_inches='tight')
    buffer.seek(0)

    try:
        png_data = buffer.getvalue()
        sys.stdout.buffer.write(png_data)
        sys.stdout.buffer.flush()
    except AttributeError:
        sys.stdout.write(buffer.getvalue())

    buffer.close()
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

    args = parser.parse_args()

    try:
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        data, settings = extract_data_and_settings(config)
        print("Generating latency chart...", file=sys.stderr)
        create_bar_chart(data, settings)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


