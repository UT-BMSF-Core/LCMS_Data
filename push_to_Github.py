# Code generated with CLaude and edited by Sean Meehan. Code using Pygithub to push local files from PC to Github Repo


import argparse
import hashlib
import os
import sys
from fnmatch import fnmatch
from pathlib import Path

from github import Auth, Github, GithubException

# Things we never want to upload
IGNORE_DIRS = {".git", "venv", ".venv", "env", "__pycache__",
               ".ipynb_checkpoints", ".vscode", ".idea"}
IGNORE_FILES = ["*.pyc", ".env", ".DS_Store"]
MAX_BYTES = 50 * 1024 * 1024  # skip files over 50 MB (API limit is 100 MB)


def git_blob_sha(data: bytes) -> str:
    """Compute the SHA-1 that Git itself would give this file's contents."""
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data).hexdigest()


def iter_files(folder: Path):
    """Yield every uploadable file under `folder`, skipping ignored ones."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]  # prune in place
        for name in files:
            if any(fnmatch(name, pattern) for pattern in IGNORE_FILES):
                continue
            yield Path(root) / name


def main():
    parser = argparse.ArgumentParser(
        description="Update files that ALREADY exist in a GitHub repo. Never adds new files.")
    parser.add_argument("folder", help="Local folder holding the updated files")
    parser.add_argument("repo", help="Target repo as 'owner/name'")
    parser.add_argument("-m", "--message", default="Update from script")
    parser.add_argument("--branch", help="Branch to write to (default: repo's default)")
    parser.add_argument("--prefix", default="", help="Subfolder inside the repo to compare against")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be updated without changing anything")
    args = parser.parse_args()

    
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"ERROR: {folder} is not a folder.")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("ERROR: set the GITHUB_TOKEN environment variable first.")

    gh = Github(auth=Auth.Token(token))
    try:
        repo = gh.get_repo(args.repo)
    except GithubException as e:
        sys.exit(f"ERROR: cannot open repo '{args.repo}' (HTTP {e.status}).")
    branch = args.branch or repo.default_branch

    updated = unchanged = not_in_repo = 0
    for local in iter_files(folder):
        remote_path = local.relative_to(folder).as_posix()
        if args.prefix:
            remote_path = f"{args.prefix.strip('/')}/{remote_path}"

        data = local.read_bytes()
        if len(data) > MAX_BYTES:
            print(f"SKIP (too large): {remote_path}")
            continue

        # Look the file up on GitHub
        try:
            existing = repo.get_contents(remote_path, ref=branch)
        except GithubException as e:
            if e.status != 404:
                raise
            print(f"not in repo, skipped: {remote_path}")
            not_in_repo += 1
            continue

        # Path exists but is a folder in the repo (get_contents returns a list)
        if isinstance(existing, list):
            print(f"is a folder in the repo, skipped: {remote_path}")
            continue

        if existing.sha == git_blob_sha(data):
            print(f"unchanged: {remote_path}")
            unchanged += 1
            continue

        if args.dry_run:
            print(f"WOULD UPDATE: {remote_path}")
        else:
            repo.update_file(remote_path, f"{args.message}: update {remote_path}",
                             data, existing.sha, branch=branch)
            print(f"UPDATED: {remote_path}")
        updated += 1

    print(f"\nDone. updated={updated} unchanged={unchanged} not_in_repo={not_in_repo}")


if __name__ == "__main__":
    main()
