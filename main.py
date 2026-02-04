import os
import subprocess
import sys

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn


console = Console()


def run_git(args: list[str]) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    code, _, _ = run_git(["rev-parse", "--git-dir"])
    return code == 0


def get_changed_files() -> list[dict]:
    """Get list of changed files with their status and diff stats."""
    files = []

    # Get status of all files
    _, output, _ = run_git(["status", "--porcelain"])
    if not output.strip():
        return files

    for line in output.strip().split("\n"):
        if not line:
            continue
        status = line[:2].strip()
        filename = line[3:]

        # Get diff stats for this file
        additions, deletions = 0, 0
        if status not in ["??", "A"]:
            _, diff_stat, _ = run_git(["diff", "--numstat", "--", filename])
            if diff_stat.strip():
                parts = diff_stat.strip().split("\t")
                if len(parts) >= 2:
                    additions = int(parts[0]) if parts[0] != "-" else 0
                    deletions = int(parts[1]) if parts[1] != "-" else 0

        # Also check staged changes
        _, staged_stat, _ = run_git(["diff", "--cached", "--numstat", "--", filename])
        if staged_stat.strip():
            parts = staged_stat.strip().split("\t")
            if len(parts) >= 2:
                additions += int(parts[0]) if parts[0] != "-" else 0
                deletions += int(parts[1]) if parts[1] != "-" else 0

        status_map = {
            "M": "Modified",
            "A": "Added",
            "D": "Deleted",
            "R": "Renamed",
            "C": "Copied",
            "??": "Untracked",
            "MM": "Modified",
            "AM": "Added/Modified",
        }

        files.append({
            "filename": filename,
            "status": status_map.get(status, status),
            "additions": additions,
            "deletions": deletions,
        })

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


def get_full_diff() -> str:
    """Get the full diff for commit message generation."""
    # Get staged diff
    _, staged, _ = run_git(["diff", "--cached"])
    # Get unstaged diff
    _, unstaged, _ = run_git(["diff"])
    # Get list of untracked files
    _, untracked, _ = run_git(["ls-files", "--others", "--exclude-standard"])

    diff_content = ""
    if staged:
        diff_content += f"Staged changes:\n{staged}\n"
    if unstaged:
        diff_content += f"Unstaged changes:\n{unstaged}\n"
    if untracked:
        diff_content += f"New untracked files:\n{untracked}\n"

    return diff_content[:8000]  # Limit to avoid token issues


def generate_commit_message(diff: str) -> str:
    """Generate commit message using OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        console.print("[red]Error: OPENROUTER_API_KEY environment variable not set[/red]")
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


def commit_changes(message: str) -> bool:
    """Stage all changes and commit."""
    # Stage all changes
    code, _, err = run_git(["add", "-A"])
    if code != 0:
        console.print(f"[red]Error staging changes: {err}[/red]")
        return False

    # Commit
    code, _, err = run_git(["commit", "-m", message])
    if code != 0:
        console.print(f"[red]Error committing: {err}[/red]")
        return False

    return True


def main():
    console.print(Panel.fit("[bold blue]GitSync[/bold blue] - Auto Git Commit", border_style="blue"))

    # Check if git repo
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking git repository...", total=None)

        if not is_git_repo():
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
        files = get_changed_files()
        progress.update(task, description=f"[green]Found {len(files)} changed file(s)[/green]")

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
        diff = get_full_diff()
        message = generate_commit_message(diff)
        progress.update(task, description="[green]Commit message generated[/green]")

    console.print()
    console.print(Panel(message, title="Generated Commit Message", border_style="green"))
    console.print()

    # Commit changes
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Committing changes...", total=None)
        success = commit_changes(message)

        if success:
            progress.update(task, description="[green]Changes committed successfully![/green]")
        else:
            progress.update(task, description="[red]Commit failed[/red]")
            sys.exit(1)

    console.print()
    console.print("[bold green]Done![/bold green]")


if __name__ == "__main__":
    main()
