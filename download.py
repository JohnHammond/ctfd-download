#!/usr/bin/python3

import requests
import json
import logging
import os
import re
import argparse
import sys
from urllib.parse import urljoin, urlparse
import textwrap
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.logging import RichHandler

CHALLENGES_FOLDER = "📂 Challenges"

# Initialize the Rich console for colored and formatted output
console = Console()

# Configure the logger with RichHandler for styled logging
logging.basicConfig(
    level="WARNING",
    format="%(message)s",
    handlers=[RichHandler(console=console, show_time=True, show_path=True)]
)
logger = logging.getLogger("CTFd Downloader")

# Argument parser for CLI usage
def parse_arguments():
    parser = argparse.ArgumentParser(
        prog='CTFd Download Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''
            This tool downloads CTFd instances for generating writeups.
            Usage: python download.py -u <URL> -n <Name> -o <Output> -t <Token>
        '''))
    parser.add_argument("-u", "--url", required=True, help="CTF Base URL (e.g., http://myctf.ctfd.io/)")
    parser.add_argument("-n", "--name", required=True, help="CTF Name (e.g., MyCTF)")
    parser.add_argument("-t", "-c", "-s", "--session", required=True, help="API Token or Session Cookie")
    parser.add_argument("-o", "--output", required=True, help="Output Directory")
    parser.add_argument("--update", action="store_true", help="Download only new challenges")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity level")
    return parser.parse_args()

# Basic utilities for text and file handling
def slugify(text):
    return "🔲 " + re.sub(r"[^a-z0-9-]", "", re.sub(r"[\s]+", "-", text.lower())).strip("-")

def create_directory_structure(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, CHALLENGES_FOLDER), exist_ok=True)

def configure_logging(verbosity_level):
    levels = {1: "INFO", 2: "DEBUG"}
    log_level = levels.get(verbosity_level, "WARNING")
    logger.setLevel(log_level)

# Core CTFd downloading functions
def fetch_challenges(api_url, headers):
    response = requests.get(f"{api_url}/challenges", headers=headers)
    try:
        return json.loads(response.text).get("data", [])
    except (json.JSONDecodeError, KeyError):
        logger.error("Failed to retrieve challenges")
        sys.exit(1)

def fetch_challenge_details(api_url, challenge_id, headers):
    """Fetch detailed data for a single challenge, including description and files."""
    response = requests.get(f"{api_url}/challenges/{challenge_id}", headers=headers)
    try:
        return json.loads(response.text)["data"]
    except (json.JSONDecodeError, KeyError):
        logger.error("Failed to retrieve details for challenge ID %s", challenge_id)
        return None

def download_challenge_assets(session, url, destination, progress, file_task_id):
    response = session.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                file.write(chunk)
                progress.update(file_task_id, advance=len(chunk))
    progress.console.log(f"Downloaded {urlparse(url).path.split('/')[-1]} to {destination}")

def save_challenge_metadata(challenge, output_path):
    challenge_name = challenge.get('name', 'Unnamed Challenge')
    challenge_description = challenge.get('description', 'No description provided.')

    # Save each challenge as an individual .md file
    file_path = os.path.join(output_path, f"{slugify(challenge_name)}.md")
    with open(file_path, "w") as challenge_file:
        challenge_file.write(f"# {challenge_name}\n\n> {challenge_description}\n\n-------------------\n\n")
    
    return file_path

def organize_challenges(challenges, output_dir, session, headers, api_url, update_existing, ctf_name):
    links_to_review = []

    with Progress(
        TextColumn("{task.description}", justify="left"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "•",
        TimeRemainingColumn(),
        console=console
    ) as progress:

        for challenge in challenges:
            challenge_name = challenge.get("name", "Unnamed Challenge")
            task_id = progress.add_task(f"Processing Challenge: {challenge_name}", total=100)
            progress.update(task_id, advance=10)

            # Fetch full challenge data to ensure we have a description and files
            challenge_data = fetch_challenge_details(api_url, challenge["id"], headers) or challenge

            # Define the path for the .md file instead of creating a folder
            category = challenge_data.get("category", "Uncategorized")
            challenge_file_path = os.path.join(output_dir, CHALLENGES_FOLDER, f"{category}_{slugify(challenge_name)}.md")

            # Save metadata to .md file
            saved_file_path = save_challenge_metadata(challenge_data, os.path.join(output_dir, CHALLENGES_FOLDER))
            progress.console.log(f"Saved challenge file: {saved_file_path}")
            progress.update(task_id, advance=40)

            # Download challenge files if available
            for file_url in challenge_data.get("files", []):
                file_name = urlparse(file_url).path.split("/")[-1]
                download_path = os.path.join(output_dir, CHALLENGES_FOLDER, f"{slugify(challenge_name)}_{file_name}")
                
                # Add download task to the existing Progress instance
                file_task_id = progress.add_task(f"Downloading File: {file_name}", total=0)  # Initialize with 0 and update in function
                download_challenge_assets(session, urljoin(api_url, file_url), download_path, progress, file_task_id)

            links_to_review.extend(re.findall(r'(https?://[^\s]+)', challenge_data.get("description", "")))
            progress.update(task_id, advance=50)

        # Save README listing all challenges
        with open(os.path.join(output_dir, "README.md"), "w") as readme_file:
            readme_file.write(f"# {ctf_name}\n\n## Challenges\n\n")
            for challenge in challenges:
                challenge_name = challenge.get("name", "Unnamed Challenge")
                category = challenge.get("category", "Uncategorized")
                readme_file.write(f"* [{challenge_name}](<{CHALLENGES_FOLDER}/{category}_{slugify(challenge_name)}.md>)\n")
                
        if links_to_review:
            console.print("[bold yellow]External links found in descriptions; check for manual download needs.")

def main():
    args = parse_arguments()
    configure_logging(args.verbose)
    create_directory_structure(args.output)
    
    headers = {"Content-Type": "application/json"}
    if args.session.startswith("session="):
        headers["Cookie"] = args.session
    else:
        headers["Authorization"] = args.session
    
    api_url = urljoin(args.url, "/api/v1")
    challenges = fetch_challenges(api_url, headers)
    session = requests.Session()
    organize_challenges(challenges, args.output, session, headers, api_url, args.update, args.name)
    console.print("[bold green]Download completed![/bold green]")

if __name__ == "__main__":
    main()
