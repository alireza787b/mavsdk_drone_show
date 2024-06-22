import csv
import os
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, 'config.csv')
SWARM_FILE_PATH = os.path.join(BASE_DIR, 'swarm.csv')

def load_config(file_path=CONFIG_FILE_PATH):
    config = []
    try:
        with open(file_path, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                config.append(row)
    except Exception as e:
        logging.error(f"Error loading config file: {e}")
    return config




def save_config(config, file_path=CONFIG_FILE_PATH):
    try:
        with open(file_path, mode='w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=config[0].keys())
            writer.writeheader()
            writer.writerows(config)
    except Exception as e:
        logging.error(f"Error saving config file: {e}")

def load_swarm(file_path=SWARM_FILE_PATH):
    swarm = []
    try:
        with open(file_path, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                swarm.append(row)
    except Exception as e:
        logging.error(f"Error loading swarm file: {e}")
    return swarm

def save_swarm(swarm, file_path=SWARM_FILE_PATH):
    try:
        with open(file_path, mode='w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=swarm[0].keys())
            writer.writeheader()
            writer.writerows(swarm)
    except Exception as e:
        logging.error(f"Error saving swarm file: {e}")
