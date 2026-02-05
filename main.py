import os
import sys

from git import Repo
from git.exc import InvalidGitRepositoryError
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


def get_repo() -> Repo | None:
    """Get the git repository for current directory."""
    try:
        return Repo(".", search_parent_directories=True)
    except InvalidGitRepositoryError:
        return None


def get_changed_files(repo: Repo) -> list[dict]:
    """Get list of changed files with their status and diff stats."""
    files = []

    # Get unstaged changes (working tree vs index)
    for diff in repo.index.diff(None):
        stats = (
            diff.a_blob.data_stream.read().decode().count("\n") if diff.a_blob else 0
        )
        b_stats = (
            diff.b_blob.data_stream.read().decode().count("\n") if diff.b_blob else 0
        )
        files.append(
            {
                "filename": diff.a_path or diff.b_path,
                "status": "Modified" if diff.change_type == "M" else diff.change_type,
                "additions": 0,
                "deletions": 0,
                "change_type": "unstaged",
            }
        )

    # Get staged changes (index vs HEAD)
    try:
        staged_diffs = repo.index.diff("HEAD")
    except Exception:
        staged_diffs = repo.index.diff(repo.head.commit) if repo.head.is_valid() else []

    for diff in staged_diffs:
        existing = next(
            (f for f in files if f["filename"] == (diff.a_path or diff.b_path)), None
        )
        if existing:
            existing["change_type"] = "both"
        else:
            status_map = {"M": "Modified", "A": "Added", "D": "Deleted", "R": "Renamed"}
            files.append(
                {
                    "filename": diff.a_path or diff.b_path,
                    "status": status_map.get(diff.change_type, diff.change_type),
                    "additions": 0,
                    "deletions": 0,
                    "change_type": "staged",
                }
            )

    # Get untracked files
    for filepath in repo.untracked_files:
        files.append(
            {
                "filename": filepath,
                "status": "Untracked",
                "additions": 0,
                "deletions": 0,
                "change_type": "untracked",
            }
        )

    # Calculate diff stats using git diff
    for f in files:
        if f["status"] == "Untracked":
            continue
        try:
            diff_output = repo.git.diff("--numstat", "--", f["filename"])
            if diff_output:
                parts = diff_output.strip().split("\t")
                if len(parts) >= 2:
                    f["additions"] = int(parts[0]) if parts[0] != "-" else 0
                    f["deletions"] = int(parts[1]) if parts[1] != "-" else 0

            staged_output = repo.git.diff("--cached", "--numstat", "--", f["filename"])
            if staged_output:
                parts = staged_output.strip().split("\t")
                if len(parts) >= 2:
                    f["additions"] += int(parts[0]) if parts[0] != "-" else 0
                    f["deletions"] += int(parts[1]) if parts[1] != "-" else 0
        except Exception:
            pass

    return files


def display_changes(files: list[dict]) -> None:
    """Display changed files in a rich table."""
    table = Table(title="Changed Files")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("+", style="green", justify="right")
    table.add_column("-", style="red", justify="right")

    for f in files:
        table.add_row(
            f["filename"],
            f["status"],
            f"+{f['additions']}" if f["additions"] else "",
            f"-{f['deletions']}" if f["deletions"] else "",
        )

    console.print(table)


def get_full_diff(repo: Repo) -> str:
    """Get the full diff for commit message generation."""
    diff_content = ""

    # Staged diff
    staged = repo.git.diff("--cached")
    if staged:
        diff_content += f"Staged changes:\n{staged}\n"

    # Unstaged diff
    unstaged = repo.git.diff()
    if unstaged:
        diff_content += f"Unstaged changes:\n{unstaged}\n"

    # Untracked files
    untracked = repo.untracked_files
    if untracked:
        diff_content += f"New untracked files:\n{chr(10).join(untracked)}\n"

    return diff_content[:8000]


def generate_commit_message(diff: str) -> str:
    """Generate commit message using OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        console.print(
            "[red]Error: OPENROUTER_API_KEY environment variable not set[/red]"
        )
        sys.exit(1)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    prompt = f"""Generate a concise git commit message for the following changes.
Follow conventional commit format (e.g., feat:, fix:, docs:, refactor:, etc.).
Keep the first line under 72 characters. Add a brief body if needed.
Only output the commit message, nothing else.

Changes:
{diff}"""

    response = client.chat.completions.create(
        model="google/gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )

    return response.choices[0].message.content.strip()


def commit_changes(repo: Repo, message: str) -> bool:
    """Stage all changes and commit."""
    try:
        repo.git.add("-A")
        repo.index.commit(message)
        return True
    except Exception as e:
        console.print(f"[red]Error committing: {e}[/red]")
        return False


def main():
    console.print(
        Panel.fit(
            "[bold blue]GitSync[/bold blue] - Auto Git Commit", border_style="blue"
        )
    )

    # Check if git repo
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking git repository...", total=None)
        repo = get_repo()

        if not repo:
            progress.stop()
            console.print("[red]Error: Not a git repository[/red]")
            sys.exit(1)

        progress.update(task, description="[green]Git repository found[/green]")

    # Get changed files
    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking for changes...", total=None)
        files = get_changed_files(repo)
        progress.update(
            task, description=f"[green]Found {len(files)} changed file(s)[/green]"
        )

    if not files:
        console.print("[yellow]No changes to commit[/yellow]")
        sys.exit(0)

    console.print()
    display_changes(files)
    console.print()

    # Generate commit message
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating commit message...", total=None)
        diff = get_full_diff(repo)
        message = generate_commit_message(diff)
        progress.update(task, description="[green]Commit message generated[/green]")

    console.print()
    console.print(
        Panel(message, title="Generated Commit Message", border_style="green")
    )
    console.print()

    # Commit changes
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Committing changes...", total=None)
        success = commit_changes(repo, message)

        if success:
            progress.update(
                task, description="[green]Changes committed successfully![/green]"
            )
        else:
            progress.update(task, description="[red]Commit failed[/red]")
            sys.exit(1)

    console.print()
    console.print("[bold blue]Done![/bold blue]")


if __name__ == "__main__":
    main()
