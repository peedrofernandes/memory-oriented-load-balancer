#!/usr/bin/env python3
"""
Bitrate per Frame Chart Generator

This script generates a line chart showing bitrate (in kbps) over time (per
frame) for different datasets. Each dataset represents a different scenario or
configuration.

The script reads configuration from a JSON file that contains:
- datasets: Dictionary of scenario name -> array of numeric bitrate values
- chart_settings: Appearance settings (colors, sizes, labels, dpi, etc.)

Usage:
    python bitrate_per_frame.py --config config.json > chart.png
    python bitrate_per_frame.py --config config.json | tee chart.png
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import sys
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


def create_bitrate_chart(config: Dict[str, Any]) -> None:
    """Create and output the bitrate per frame chart to stdout."""
    datasets: Dict[str, List[float]] = config['datasets']
    chart_settings: Dict[str, Any] = config.get('chart_settings', {})

    figure_size = tuple(chart_settings.get('figure_size', [12, 8]))
    colors = chart_settings.get('colors', ['#1f77b4', '#ff7f0e', '#2ca02c'])
    line_width = float(chart_settings.get('line_width', 2))
    marker_size = float(chart_settings.get('marker_size', 3))
    dpi = int(chart_settings.get('dpi', 300))

    plt.figure(figsize=figure_size)
    plt.style.use('default')

    # Plot each dataset
    for i, (scenario_name, bitrate_values) in enumerate(datasets.items()):
        frame_numbers = np.arange(1, len(bitrate_values) + 1)
        y_values = [float(v) for v in bitrate_values]
        plt.plot(
            frame_numbers,
            y_values,
            label=scenario_name,
            linewidth=line_width,
            marker='o',
            markersize=marker_size,
            color=colors[i % len(colors)],
        )

    plt.xlabel(chart_settings.get('x_label', 'Frame Number'), fontsize=12, fontweight='bold')
    plt.ylabel(chart_settings.get('y_label', 'Bitrate (kbps)'), fontsize=12, fontweight='bold')
    plt.title(chart_settings.get('title', 'Bitrate per Frame'), fontsize=14, fontweight='bold', pad=20)

    if 'y_axis_limits' in chart_settings:
        y_min, y_max = chart_settings['y_axis_limits']
        plt.ylim(float(y_min), float(y_max))

    plt.grid(True, alpha=0.3, linestyle='--')
    plt.legend(loc='upper right', frameon=True, shadow=True)
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

    args = parser.parse_args()

    try:
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        print("Generating bitrate chart...", file=sys.stderr)
        create_bitrate_chart(config)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())


