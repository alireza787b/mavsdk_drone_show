ALLOWED_EXTENSIONS = {'zip'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
           
# Function to clear show directories
def clear_show_directories():
    directories = [
        'shapes/swarm/skybrush',
        'shapes/swarm/processed',
        'shapes/swarm/plots'
    ]
    for directory in directories:
        print(f"Clearing directory: {directory}")  # Debugging line
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')  # Debugging line