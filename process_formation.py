
from functions.plot_drone_paths import plot_drone_paths

from functions.process_drone_files import process_drone_files

from functions.update_config_file import update_config_file

# Process the drone files and output the processed data to another directory
print("starting process_formation.py")
skybrush_dir = 'shapes/swarm/skybrush'

processed_dir = 'shapes/swarm/processed'

method = 'cubic'

dt = 0.05

SHOW_PLOTS = False

process_drone_files(skybrush_dir, processed_dir, method, dt)

# Update the 'x' and 'y' columns of the config file with the initial position of each drone

config_file = 'config.csv'

update_config_file(skybrush_dir, config_file)

plot_drone_paths(skybrush_dir, processed_dir,SHOW_PLOTS)

print("Processing complete!")
exit(0)  # Success
