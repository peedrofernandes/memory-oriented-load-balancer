#!/usr/bin/env python3
"""
Quality por Frame Chart Generator

This script generates a line chart showing qualidade de vídeo por frame
for a single scenario, plotting one line per strategy (e.g., round-robin,
random-selection, memory-monitoring-6s, memory-monitoring-30s).

The script reads configuration from a JSON file that contains:
- Quality mappings (string to numeric values)
- Dataset definitions (scenarios with quality data)
- Chart settings (colors, sizes, labels, etc.)

Usage:
    python quality_per_frame.py --config config.json --scenario scenario-1 > chart.png
    python quality_per_frame.py --config config.json --scenario scenario-1 | tee chart.png

The JSON configuration file should contain:
- quality_mapping: Dictionary mapping quality strings to numeric values
- quality_labels: List of quality labels for Y-axis
- quality_values: List of numeric values corresponding to labels
- datasets: Dictionary of scenario names to quality data arrays
- chart_settings: Dictionary with chart appearance settings
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import os
import sys
import io
from typing import List, Dict

def load_config(config_path: str) -> Dict:
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


def convert_quality_to_numeric(quality_data: List[str], quality_mapping: Dict[str, int]) -> List[int]:
    """Convert quality strings to numeric values for plotting."""
    return [quality_mapping.get(q, 0) for q in quality_data]


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


def create_quality_charts(config: Dict, output_path: str) -> None:
    """Create and save quality charts for all scenarios."""
    all_datasets = config['datasets']
    quality_mapping = config['quality_mapping']
    quality_labels = config['quality_labels']
    quality_values = config['quality_values']
    chart_settings = config['chart_settings']
    
    # Set up the plot
    plt.figure(figsize=tuple(chart_settings['figure_size']))
    plt.style.use('default')
    
    colors = chart_settings['colors']

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

        plt.figure(figsize=tuple(chart_settings['figure_size']))
        plt.style.use('default')

        # Order strategies consistently
        canonical_to_original: Dict[str, str] = {}
        for orig in scenario_series.keys():
            canonical_to_original[_canonical_strategy_key(orig)] = orig
        ordered = [k for k in strategy_order if k in canonical_to_original]
        for k in sorted(canonical_to_original.keys()):
            if k not in ordered:
                ordered.append(k)

        for i, canonical in enumerate(ordered):
            strategy_name = canonical_to_original.get(canonical, canonical)
            quality_data = scenario_series.get(strategy_name, [])
            if not quality_data:
                continue
            frame_numbers = list(range(1, len(quality_data) + 1))
            numeric_quality = convert_quality_to_numeric(quality_data, quality_mapping)

            color = strategy_color_map.get(canonical, colors[i % len(colors)])
            plt.plot(frame_numbers, numeric_quality,
                     label=_normalize_strategy_name(strategy_name),
                     linewidth=chart_settings['line_width'] * 1.5,
                     marker='o',
                     markersize=chart_settings['marker_size'],
                     color=color,
                     linestyle='--',
                     alpha=0.9,
                     markeredgecolor='white',
                     markeredgewidth=0.7)

        # Convert scenario name to Portuguese
        scenario_pt = scenario.replace('scenario-', 'Cenário ')
        
        plt.xlabel(chart_settings.get('x_label', 'Número do Frame'), fontsize=12, fontweight='bold')
        plt.ylabel(chart_settings.get('y_label', 'Qualidade'), fontsize=12, fontweight='bold')
        plt.title(f"{chart_settings.get('title', 'Qualidade por Frame')} - {scenario_pt}", fontsize=14, fontweight='bold', pad=20)

        plt.yticks(quality_values, quality_labels)
        plt.ylim(tuple(chart_settings['y_axis_limits']))

        plt.grid(True, alpha=0.3, linestyle='--')
        plt.legend(loc='upper right', frameon=True, shadow=True)
        plt.tight_layout()

        out_file = _resolve_output_path(output_path, scenario)
        plt.savefig(out_file, format='png', dpi=chart_settings['dpi'], bbox_inches='tight')
        print(f"Saved: {out_file}", file=sys.stderr)
        plt.close()


def main():
    """Main function to generate chart and output to stdout."""
    parser = argparse.ArgumentParser(
        description="Generate a quality por frame chart and output to stdout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python quality_per_frame.py --config config.json > chart.png
  python quality_per_frame.py --config config.json | tee chart.png
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
        # Print status to stderr so it doesn't interfere with binary output
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        print("Generating quality charts for all scenarios...", file=sys.stderr)
        create_quality_charts(config, args.output)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())