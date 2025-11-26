import json
import subprocess
import os
import shutil

# --- Configuration ---
GCP_BUCKET_PATH = "gs://soi_data/compressed/*.jpg"
COMBINED_FILES_JSON = "combined_files_50k.json"
DOWNLOAD_DIR = "data/jpgs"
BATCH_SIZE = 500
GITHUB_REPO = "50k-osm-jpg"

def run_command(command, exit_on_error=True):
    """Runs a shell command, prints output, and handles errors."""
    print(f"Executing: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False  # Don't raise exception on non-zero exit codes
        )
        if result.returncode != 0:
            print(f"--- ERROR ---")
            print(f"Command failed with exit code {result.returncode}: {' '.join(command)}")
            print(f"Stderr: {result.stderr.strip()}")
            print(f"Stdout: {result.stdout.strip()}")
            if exit_on_error:
                print("Exiting due to critical error.")
                exit(1)
        return result
    except FileNotFoundError:
        print(f"--- ERROR ---")
        print(f"Command not found: {command[0]}. Please ensure it is installed and in your PATH.")
        if exit_on_error:
            exit(1)
        return None

def get_existing_files(download_dir, github_repo):
    """
    Fetches a list of already existing files from the local directory and
    previously uploaded files from the GitHub release.
    """
    existing_files = set()

    # 1. Get local files from data/jpgs
    if os.path.exists(download_dir):
        for filename in os.listdir(download_dir):
            if filename.endswith('.jpg'):
                existing_files.add(filename)
    print(f"Found {len(existing_files)} existing local files in {download_dir}.")

    # 2. Get files from GitHub release listing
    print("Attempting to fetch 'listing_files.csv' from GitHub release...")
    listing_csv_path = "listing_files.csv"
    # Note: `gh` CLI might require `GITHUB_REPO` to be in `owner/repo` format.
    # If this step fails, please check the repository name.
    download_cmd = [
        "gh", "release", "download",
        github_repo,
        "--pattern", listing_csv_path,
        "--clobber"  # Overwrite if it exists locally
    ]
    result = run_command(download_cmd, exit_on_error=False)

    if result.returncode == 0 and os.path.exists(listing_csv_path):
        print(f"Successfully fetched '{listing_csv_path}'.")
        initial_count = len(existing_files)
        with open(listing_csv_path, 'r') as f:
            # Assuming the first column of the CSV is the filename, skipping header
            next(f, None)
            for line in f:
                parts = line.strip().split(',')
                if parts and parts[0].endswith('.jpg'):
                    existing_files.add(parts[0])
        
        new_files_from_listing = len(existing_files) - initial_count
        print(f"Added {new_files_from_listing} file names from release history.")
        print(f"Total unique files to skip (local + remote): {len(existing_files)}.")
        os.remove(listing_csv_path)  # Clean up the downloaded file
    else:
        print("Could not fetch 'listing_files.csv'. This is expected if no files have been uploaded yet.")
        if result and result.stderr:
            print(f"Stderr from gh command: {result.stderr.strip()}")

    return existing_files

def sort_key(sheet_id):
    """Sort key for sheet IDs like '40D_16'."""
    parts = sheet_id.split('_')
    try:
        # Assumes format 'STRING_NUMBER'
        return parts[0], int(parts[1])
    except (IndexError, ValueError):
        # Fallback for any sheet_id that doesn't match the expected format
        return sheet_id, 0

def upload_batch():
    """Uploads the current batch to GitHub Releases and clears the directory."""
    print(f"\nUploading batch of files from {DOWNLOAD_DIR}...")
    # NOTE: The user specified `uvx --from gh-release-tools...`. If `uvx` is not correct,
    # you may need to change it to `uv` or another command.
    upload_command = [
        "uvx", "--from", "gh-release-tools", "upload-to-release",
        "-r", GITHUB_REPO,
        "-d", DOWNLOAD_DIR,
        "-e", ".jpg",
        "-x"
    ]
    result = run_command(upload_command, exit_on_error=False)

    if result and result.returncode == 0:
        print("Upload successful. Updating release file list...")
        generate_lists_command = [
            "uvx", "--from", "gh-release-tools", "generate-lists",
            "-r", GITHUB_REPO,
            "-e", ".jpg"
        ]
        run_command(generate_lists_command)

        print(f"Cleaning up directory: {DOWNLOAD_DIR}")
        if os.path.exists(DOWNLOAD_DIR):
            shutil.rmtree(DOWNLOAD_DIR)
        os.makedirs(DOWNLOAD_DIR)
    else:
        print("\n--- UPLOAD FAILED ---")
        print(f"Upload from {DOWNLOAD_DIR} failed. The directory will not be cleaned.")
        print("Please check the errors above, resolve the issue, and consider re-running.")
        print("The downloaded files for the failed batch are still in the directory.")
        exit(1)

def main():
    """Main script execution."""
    print("--- Starting GCP to GitHub Release Script ---")

    # 1. Prepare environment
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        print(f"Created directory: {DOWNLOAD_DIR}")

    # Get set of files that already exist locally or in the release
    existing_files = get_existing_files(DOWNLOAD_DIR, GITHUB_REPO)

    # 2. Load and process combined files mapping
    print(f"\nLoading combined files mapping from {COMBINED_FILES_JSON}...")
    try:
        with open(COMBINED_FILES_JSON, 'r') as f:
            combined_groups = json.load(f)
    except FileNotFoundError:
        print(f"Error: {COMBINED_FILES_JSON} not found.")
        exit(1)

    id_to_combined_name = {}
    for group in combined_groups:
        group.sort(key=sort_key)  # Sort using custom key for proper numeric/alpha sorting
        combined_name = "-".join(group) + ".jpg"
        for sheet_id in group:
            id_to_combined_name[sheet_id] = combined_name
    print(f"Created mapping for {len(id_to_combined_name)} individual IDs.")

    # 3. Get file list from GCP
    print(f"\nFetching file list from {GCP_BUCKET_PATH}...")
    gsutil_ls_cmd = ["gsutil", "ls", GCP_BUCKET_PATH]
    result = run_command(gsutil_ls_cmd)
    gcp_files = result.stdout.strip().split('\n')
    if not gcp_files or not gcp_files[0]:
        print("No files found in GCP. Exiting.")
        return
    print(f"Found {len(gcp_files)} files in GCP to process.")

    # 4. Process files in batches
    batch_counter = 0
    processed_combined_files = set()

    for gcp_file_url in gcp_files:
        if not gcp_file_url:
            continue

        base_name = os.path.basename(gcp_file_url)
        sheet_id, _ = os.path.splitext(base_name)

        # Determine the correct destination filename
        if sheet_id in id_to_combined_name:
            dest_filename = id_to_combined_name[sheet_id]
            if dest_filename in processed_combined_files:
                print(f"Skipping {base_name} (part of already processed group {dest_filename})")
                continue
            processed_combined_files.add(dest_filename)
        else:
            dest_filename = base_name

        # Skip if file already exists
        if dest_filename in existing_files:
            print(f"Skipping {dest_filename}, already exists.")
            continue

        # Download the file
        download_path = os.path.join(DOWNLOAD_DIR, dest_filename)
        print(f"Downloading {gcp_file_url} -> {download_path}")
        cp_command = ["gsutil", "cp", gcp_file_url, download_path]
        cp_result = run_command(cp_command, exit_on_error=False)

        if cp_result and cp_result.returncode == 0:
            batch_counter += 1
        else:
            print(f"Warning: Failed to download {gcp_file_url}. Skipping this file.")

        # Check if batch is full
        if batch_counter >= BATCH_SIZE:
            upload_batch()
            batch_counter = 0
            # After upload, the download dir is cleared, so we should also clear local files list
            existing_files = get_existing_files(DOWNLOAD_DIR, GITHUB_REPO)
            #existing_files = set()


    # 5. Upload any remaining files in the last batch
    if batch_counter > 0:
        print("\nUploading the final batch...")
        upload_batch()

    print("\n--- Script finished successfully! ---")

if __name__ == "__main__":
    main()
