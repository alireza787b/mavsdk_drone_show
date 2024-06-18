#gcs-server/config.py
import csv
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, 'config.csv')
SWARM_FILE_PATH = os.path.join(BASE_DIR, 'swarm.csv')

def load_config(file_path=CONFIG_FILE_PATH):
    config = []
    with open(file_path, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            config.append(row)
    return config

def save_config(config, file_path=CONFIG_FILE_PATH):
    with open(file_path, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=config[0].keys())
        writer.writeheader()
        writer.writerows(config)

def load_swarm(file_path=SWARM_FILE_PATH):
    swarm = []
    with open(file_path, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            swarm.append(row)
    return swarm

def save_swarm(swarm, file_path=SWARM_FILE_PATH):
    with open(file_path, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=swarm[0].keys())
        writer.writeheader()
        writer.writerows(swarm)
