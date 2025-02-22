#!/usr/bin/env python3
"""
Generate hover test CSV files for drone shows with customizable parameters and visual feedback
"""

import csv
from pathlib import Path
import math
from datetime import datetime

# ====================== CONFIGURABLE PARAMETERS ======================
# File configuration
OUTPUT_PATHS = [
    Path("shapes/hover_test.csv"),
    Path("shapes_sitl/hover_test.csv")
]

# Flight parameters
TARGET_ALTITUDE = 8.0  # Meters (negative for NED coordinates)
ASCENT_SPEED = 0.5      # m/s
HOVER_DURATION = 10     # seconds
SAMPLE_TIME = 0.05      # seconds (0.05 = 20Hz)

# Visual parameters
YAW = 0.0               # Degrees
MODE = 70               # Flight mode
BASE_LED_BRIGHTNESS = 255  # 0-255

# Phase colors (RGB)
ASCENT_COLOR = (0, 0, 255)      # Blue
HOVER_COLORS = [
    (0, 255, 0),    # Green
    (255, 255, 0)   # Yellow
] 
LANDING_COLOR = (255, 0, 0)     # Red

# Hover light show parameters
COLOR_CHANGE_INTERVAL = 2.0  # Seconds between color changes
PULSE_FREQUENCY = 0.5        # Hz for brightness pulsation

# =====================================================================

TARGET_ALTITUDE = -1 * TARGET_ALTITUDE  # negative for NED coordinates)


def calculate_phase_durations():
    """Calculate phase durations and time thresholds"""
    ascent_time = abs(TARGET_ALTITUDE / ASCENT_SPEED)
    landing_time = ascent_time  # Same speed for descent
    return {
        'ascent': ascent_time,
        'hover': HOVER_DURATION,
        'landing': landing_time,
        'total': ascent_time + HOVER_DURATION + landing_time
    }

def get_hover_light_show(t_hover):
    """Generate dynamic light patterns during hover phase"""
    # Color transition between HOVER_COLORS
    color_index = int(t_hover / COLOR_CHANGE_INTERVAL) % len(HOVER_COLORS)
    base_color = HOVER_COLORS[color_index]
    
    # Add brightness pulsation
    pulsation = int((math.sin(t_hover * 2 * math.pi * PULSE_FREQUENCY) + 1) * 0.3 * BASE_LED_BRIGHTNESS)
    
    return (
        min(base_color[0] + pulsation, 255),
        min(base_color[1] + pulsation, 255),
        min(base_color[2] + pulsation, 255)
    )

def generate_trajectory():
    """Generate complete flight trajectory with light patterns"""
    phase_durations = calculate_phase_durations()
    current_time = 0.0
    idx = 0
    
    # Ascent phase
    while current_time < phase_durations['ascent']:
        progress = current_time / phase_durations['ascent']
        altitude = TARGET_ALTITUDE * progress
        yield {
            't': current_time,
            'pz': altitude,
            'led': ASCENT_COLOR
        }
        current_time += SAMPLE_TIME
        idx += 1

    # Hover phase
    hover_start = current_time
    while current_time < hover_start + phase_durations['hover']:
        t_hover = current_time - hover_start
        yield {
            't': current_time,
            'pz': TARGET_ALTITUDE,
            'led': get_hover_light_show(t_hover)
        }
        current_time += SAMPLE_TIME
        idx += 1

    # Landing phase
    landing_start = current_time
    while current_time < landing_start + phase_durations['landing']:
        progress = (current_time - landing_start) / phase_durations['landing']
        altitude = TARGET_ALTITUDE * (1 - progress)
        yield {
            't': current_time,
            'pz': altitude,
            'led': LANDING_COLOR
        }
        current_time += SAMPLE_TIME
        idx += 1

def main():
    """Main function to generate and save CSV files"""
    # Create output directories if needed
    for path in OUTPUT_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)

    # Generate trajectory data
    trajectory = list(generate_trajectory())
    
    # Create CSV rows
    csv_rows = []
    for idx, point in enumerate(trajectory):
        csv_rows.append([
            idx,
            round(point['t'], 3),
            0.0,  # px
            0.0,  # py
            round(point['pz'], 3),
            0.0,  # vx
            0.0,  # vy
            0.0,  # vz
            0.0,  # ax
            0.0,  # ay
            0.0,  # az
            YAW,
            MODE,
            point['led'][0],  # Red
            point['led'][1],  # Green
            point['led'][2],  # Blue
        ])

    # Write to all output paths
    for path in OUTPUT_PATHS:
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'idx', 't', 'px', 'py', 'pz', 
                'vx', 'vy', 'vz', 'ax', 'ay', 'az',
                'yaw', 'mode', 'ledr', 'ledg', 'ledb'
            ])
            writer.writerows(csv_rows)
        
        print(f"Generated {path} with {len(csv_rows)} points")

if __name__ == "__main__":
    main()