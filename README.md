# GitSync

A CLI tool that automatically generates AI-powered commit messages and syncs your changes to GitHub.

## Features

- **AI-generated commit messages** using OpenRouter API (Gemini 2.5 Flash Lite)
- **Visual diff summary** showing changed files with additions/deletions
- **Auto-push** to remote repository
- **GitHub repo creation** via `gh` CLI if no remote exists
- **Beautiful terminal UI** powered by Rich

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/gitsync.git
cd gitsync

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

## Requirements

- Python 3.13+
- [OpenRouter API key](https://openrouter.ai/)
- [GitHub CLI](https://cli.github.com/) (optional, for creating new repos)

## Setup

Set your OpenRouter API key as an environment variable:

```bash
export OPENROUTER_API_KEY="your-api-key-here"
```

## Usage

Run from any git repository:

```bash
gitsync
```

The tool will:

1. Detect all staged, unstaged, and untracked changes
2. Display a summary of modified files
3. Generate a conventional commit message using AI
4. Commit all changes
5. Push to the remote (if configured)

If no remote is configured, GitSync will offer to create a GitHub repository for you.

## Dependencies

- [GitPython](https://gitpython.readthedocs.io/) - Git repository interaction
- [OpenAI SDK](https://github.com/openai/openai-python) - OpenRouter API client
- [Rich](https://rich.readthedocs.io/) - Terminal formatting

## License

MIT