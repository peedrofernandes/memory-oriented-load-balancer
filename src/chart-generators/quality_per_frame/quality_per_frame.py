#!/usr/bin/env python3
"""
Quality per Frame Chart Generator

This script generates a line chart showing video quality changes over time
for different datasets. Each dataset represents a different scenario or
configuration.

The script reads configuration from a JSON file that contains:
- Quality mappings (string to numeric values)
- Dataset definitions (scenarios with quality data)
- Chart settings (colors, sizes, labels, etc.)

Usage:
    python quality_per_frame.py --config config.json > chart.png
    python quality_per_frame.py --config config.json | tee chart.png

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


def create_quality_chart(config: Dict) -> None:
    """Create and output the quality per frame chart to stdout."""
    # Extract configuration
    datasets = config['datasets']
    quality_mapping = config['quality_mapping']
    quality_labels = config['quality_labels']
    quality_values = config['quality_values']
    chart_settings = config['chart_settings']
    
    # Set up the plot
    plt.figure(figsize=tuple(chart_settings['figure_size']))
    plt.style.use('default')
    
    # Colors for different lines
    colors = chart_settings['colors']
    
    # Plot each dataset
    for i, (scenario_name, quality_data) in enumerate(datasets.items()):
        frame_numbers = list(range(1, len(quality_data) + 1))
        numeric_quality = convert_quality_to_numeric(quality_data, quality_mapping)
        
        plt.plot(frame_numbers, numeric_quality, 
                label=scenario_name, 
                linewidth=chart_settings['line_width'], 
                marker='o', 
                markersize=chart_settings['marker_size'],
                color=colors[i % len(colors)])
    
    # Customize the chart
    plt.xlabel(chart_settings['x_label'], fontsize=12, fontweight='bold')
    plt.ylabel(chart_settings['y_label'], fontsize=12, fontweight='bold')
    plt.title(chart_settings['title'], fontsize=14, fontweight='bold', pad=20)
    
    # Set Y-axis labels and ticks
    plt.yticks(quality_values, quality_labels)
    plt.ylim(tuple(chart_settings['y_axis_limits']))
    
    # Add grid for better readability
    plt.grid(True, alpha=0.3, linestyle='--')
    
    # Add legend
    plt.legend(loc='upper right', frameon=True, shadow=True)
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Save the chart to stdout
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=chart_settings['dpi'], bbox_inches='tight')
    buffer.seek(0)
    
    # Write PNG data to stdout in binary mode
    try:
        # Ensure we're writing binary data
        png_data = buffer.getvalue()
        sys.stdout.buffer.write(png_data)
        sys.stdout.buffer.flush()
    except AttributeError:
        # Fallback for systems without buffer attribute
        sys.stdout.write(buffer.getvalue())
    
    buffer.close()
    plt.close()  # Clean up the figure


def main():
    """Main function to generate chart and output to stdout."""
    parser = argparse.ArgumentParser(
        description="Generate a quality per frame chart and output to stdout",
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
    
    args = parser.parse_args()
    
    try:
        # Print status to stderr so it doesn't interfere with binary output
        print(f"Loading configuration from '{args.config}'...", file=sys.stderr)
        config = load_config(args.config)
        print("Generating quality chart...", file=sys.stderr)
        create_quality_chart(config)
        print("Chart generated successfully!", file=sys.stderr)
    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())