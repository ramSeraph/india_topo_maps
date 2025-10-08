
import os
import hashlib
import json
from collections import defaultdict

def get_file_hash(filepath):
    """Calculates the SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(65536)  # Read in 64k chunks
            if not data:
                break
            h.update(data)
    return h.hexdigest()

def sort_key(filename):
    """Sort key for filenames like '40D_16'."""
    parts = os.path.splitext(filename)[0].split('_')
    return parts[0], int(parts[1])

def find_and_process_duplicates(directory, json_path):
    """Finds, renames, and records duplicate files."""
    hashes = defaultdict(list)
    for filename in os.listdir(directory):
        if filename.endswith('.pdf'):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                file_hash = get_file_hash(filepath)
                hashes[file_hash].append(filepath)

    duplicates_found = []
    for file_hash, filepaths in hashes.items():
        if len(filepaths) > 1:
            # Sort files based on the custom key
            filepaths.sort(key=lambda p: sort_key(os.path.basename(p)))

            basenames = [os.path.splitext(os.path.basename(p))[0] for p in filepaths]
            
            # Create the new combined filename
            new_basename = '-'.join(basenames)
            new_filename = f"{new_basename}.pdf"
            new_filepath = os.path.join(directory, new_filename)

            # Rename the first file
            os.rename(filepaths[0], new_filepath)
            print(f"Renamed '{filepaths[0]}' to '{new_filepath}'")

            # Remove the other duplicate files
            for i in range(1, len(filepaths)):
                os.remove(filepaths[i])
                print(f"Removed duplicate file '{filepaths[i]}'")

            duplicates_found.append(basenames)

    if duplicates_found:
        # Update the JSON file
        with open(json_path, 'r') as f:
            data = json.load(f)

        for item in duplicates_found:
            if item not in data:
                data.append(item)

        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Updated '{json_path}' with new combined files.")
    else:
        print("No new duplicate files found.")

if __name__ == '__main__':
    data_raw_dir = 'data/raw'
    json_file = 'data/combined_files_50k.json'
    find_and_process_duplicates(data_raw_dir, json_file)
