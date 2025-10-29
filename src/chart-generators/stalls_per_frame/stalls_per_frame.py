#!/usr/bin/env python3
"""
Stalls per Frame (Segment) Chart Generator

This script generates a grouped bar chart showing stall duration (in seconds)
per segment for different datasets (scenarios). Each dataset represents a
different scenario or configuration and is provided via a JSON configuration.

The script reads configuration from a JSON file that contains:
- datasets: Dictionary of scenario name -> array of objects { "segment": int, "seconds": number }
- chart_settings: Appearance settings (colors, sizes, labels, dpi, bar width, etc.)

Usage:
    python stalls_per_frame.py --config config.json > chart.png
    python stalls_per_frame.py --config config.json | tee chart.png

The JSON configuration file should contain:
- datasets: { "Scenario 1": [{"segment": 2, "seconds": 0.0}, ...], ... }
- chart_settings: { "figure_size": [12, 8], "colors": ["#..."], "bar_width": 0.25, "dpi": 300,
                   "title": "...", "x_label": "Segment", "y_label": "Stall Seconds",
                   "y_axis_limits": [0, 1] }
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import sys
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
    """Aggregate stall seconds per segment, summing where segments repeat."""
    stalls_per_segment: Dict[int, float] = {}
    for entry in dataset_entries:
        segment = int(entry.get('segment', 0))
        seconds = float(entry.get('seconds', 0.0))
        stalls_per_segment[segment] = stalls_per_segment.get(segment, 0.0) + seconds
    return stalls_per_segment


def create_stalls_chart(config: Dict[str, Any]) -> None:
    """Create and output the stalls per segment chart to stdout."""
    datasets: Dict[str, List[Dict[str, Any]]] = config['datasets']
    chart_settings: Dict[str, Any] = config['chart_settings']

    # Collect the union of all segments across scenarios and sort them
    all_segments_set = set()
    for entries in datasets.values():
        for e in entries:
            all_segments_set.add(int(e.get('segment', 0)))
    all_segments = sorted(all_segments_set)

    # Aggregate stalls per scenario and align values to the ordered segments
    aggregated: Dict[str, Dict[int, float]] = {
        scenario: aggregate_stalls(entries) for scenario, entries in datasets.items()
    }

    values_per_scenario: Dict[str, List[float]] = {
        scenario: [aggregated[scenario].get(seg, 0.0) for seg in all_segments]
        for scenario in datasets.keys()
    }

    # Plot settings
    figure_size = tuple(chart_settings.get('figure_size', [12, 8]))
    colors = chart_settings.get('colors', ['#1f77b4', '#ff7f0e', '#2ca02c'])
    bar_width = float(chart_settings.get('bar_width', 0.25))
    dpi = int(chart_settings.get('dpi', 300))

    plt.figure(figsize=figure_size)
    plt.style.use('default')

    indices = np.arange(len(all_segments), dtype=float)
    num_scenarios = max(1, len(datasets))
    group_offset = (num_scenarios - 1) * bar_width / 2.0

    # Draw grouped bars
    for i, (scenario_name, values) in enumerate(values_per_scenario.items()):
        positions = indices - group_offset + i * bar_width
        plt.bar(
            positions,
            values,
            width=bar_width,
            label=scenario_name,
            color=colors[i % len(colors)],
        )

    # Labels and title
    plt.xlabel(chart_settings.get('x_label', 'Segment'), fontsize=12, fontweight='bold')
    plt.ylabel(chart_settings.get('y_label', 'Stall Seconds'), fontsize=12, fontweight='bold')
    plt.title(chart_settings.get('title', 'Stall Duration per Segment'), fontsize=14, fontweight='bold', pad=20)

    # X-axis ticks at the center of each group
    plt.xticks(indices, [str(s) for s in all_segments])

    # Y-axis limits if provided
    if 'y_axis_limits' in chart_settings:
        y_min, y_max = chart_settings['y_axis_limits']
        plt.ylim(float(y_min), float(y_max))

    # Grid, legend, and layout
    plt.grid(True, axis='y', alpha=0.3, linestyle='--')
    plt.legend(loc='upper right', frameon=True, shadow=True)
    plt.tight_layout()

    # Save to stdout as PNG
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
        description="Generate a grouped bar chart of stall seconds per segment and output to stdout",
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

    args = parser.parse_args()

    try:
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        print("Generating stalls chart...", file=sys.stderr)
        create_stalls_chart(config)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


