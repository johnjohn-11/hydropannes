#!/usr/bin/env python3
"""Génère les notes de release en couvrant à la fois les PR et les commits directs.

GitHub (`generate_release_notes`) ne liste que les pull requests : les commits
poussés directement sur la branche par défaut n'apparaissent jamais. Ce script
parcourt tous les commits depuis le tag précédent et produit une seule liste
chronologique : chaque entrée est soit la PR d'origine du commit (dédupliquée),
soit, à défaut, le commit direct (titre + lien + auteur cliquable).
"""
import json
import os
import subprocess

REPO = os.environ["GITHUB_REPOSITORY"]          # owner/repo
VERSION = os.environ["VERSION"]
TAG = f"v{VERSION}"
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def gh_api(path):
    out = run("gh", "api", "-H", "Accept: application/vnd.github+json", path)
    return json.loads(out) if out else None


def previous_tag():
    # Tag le plus proche accessible depuis le parent du nouveau tag.
    try:
        return run("git", "describe", "--tags", "--abbrev=0", f"{TAG}^")
    except subprocess.CalledProcessError:
        return None  # première release


def commit_shas(prev):
    rng = f"{prev}..{TAG}" if prev else TAG
    out = run("git", "rev-list", "--no-merges", rng)
    return out.splitlines() if out else []


def user_link(login, fallback):
    return f"@{login}" if login else (fallback or "inconnu")


def main():
    prev = previous_tag()
    lines = ["## Quoi de neuf", ""]
    seen_prs = set()

    for sha in commit_shas(prev):
        commit = gh_api(f"repos/{REPO}/commits/{sha}")
        title = commit["commit"]["message"].splitlines()[0]
        if title.startswith("chore: bump version to"):
            continue  # commit de bump automatique

        pulls = gh_api(f"repos/{REPO}/commits/{sha}/pulls") or []
        if pulls:
            for pr in pulls:
                if pr["number"] in seen_prs:
                    continue
                seen_prs.add(pr["number"])
                author = (pr.get("user") or {}).get("login")
                by = f" par {user_link(author, None)}" if author else ""
                lines.append(f"* {pr['title']}{by} dans #{pr['number']}")
        else:
            login = (commit.get("author") or {}).get("login")
            name = commit["commit"]["author"]["name"]
            lines.append(
                f"* {title} ([`{sha[:7]}`]({commit['html_url']})) par {user_link(login, name)}"
            )

    if len(lines) == 2:
        lines.append("_Aucun changement notable._")
    lines.append("")

    if prev:
        lines.append(f"**Changelog complet** : {SERVER}/{REPO}/compare/{prev}...{TAG}")
    else:
        lines.append(f"**Changelog complet** : {SERVER}/{REPO}/commits/{TAG}")

    with open("RELEASE_NOTES.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
