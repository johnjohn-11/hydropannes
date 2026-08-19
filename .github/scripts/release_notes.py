#!/usr/bin/env python3
"""Génère les notes de release en couvrant à la fois les PR et les commits directs.

GitHub (`generate_release_notes`) ne liste que les pull requests : les commits
poussés directement sur la branche par défaut n'apparaissent jamais. Ce script
parcourt tous les commits depuis le tag de version précédent et produit une
seule liste chronologique : chaque entrée est soit la PR d'origine du commit
(dédupliquée), soit, à défaut, le commit direct (titre + lien + auteur
cliquable).

Changements incompatibles : toute ligne d'un message de commit commençant par
« Breaking change: » (insensible à la casse) est reprise — jusqu'à la fin du
paragraphe — dans une section « Changements incompatibles » en tête des notes.
"""

import json
import os
import subprocess

REPO = os.environ["GITHUB_REPOSITORY"]  # owner/repo
VERSION = os.environ["VERSION"]
TAG = f"v{VERSION}"
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

BREAKING_PREFIX = "breaking change:"


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def gh_api(path):
    out = run("gh", "api", "-H", "Accept: application/vnd.github+json", path)
    return json.loads(out) if out else None


def is_ancestor(ref):
    """True si ``ref`` est un ancêtre du nouveau tag."""
    return subprocess.run(["git", "merge-base", "--is-ancestor", ref, TAG]).returncode == 0


def previous_tag():
    """Tag de version le plus récent (tri sémantique) qui est un ancêtre du tag.

    Plus robuste que « git describe » : celui-ci échoue lorsque les seuls tags
    existants sont sur une autre ligne d'historique (ce qui listait alors tout
    l'historique). On retient le plus haut tag réellement présent dans
    l'historique du nouveau tag, ou None pour une première release.
    """
    for tag in run("git", "tag", "--sort=-v:refname").splitlines():
        if tag != TAG and is_ancestor(tag):
            return tag
    return None


def commit_shas(prev):
    rng = f"{prev}..{TAG}" if prev else TAG
    out = run("git", "rev-list", "--no-merges", rng)
    return out.splitlines() if out else []


def user_link(login, fallback):
    return f"@{login}" if login else (fallback or "inconnu")


def extract_breaking(message):
    """Reprend le paragraphe d'une note « Breaking change: », ou None."""
    msg_lines = message.splitlines()
    for i, line in enumerate(msg_lines):
        if line.strip().lower().startswith(BREAKING_PREFIX):
            parts = [line.strip()[len(BREAKING_PREFIX) :].strip()]
            for cont in msg_lines[i + 1 :]:
                if not cont.strip():
                    break
                parts.append(cont.strip())
            return " ".join(p for p in parts if p).strip()
    return None


def main():
    prev = previous_tag()
    changes = []
    breaking = []
    seen_prs = set()

    for sha in commit_shas(prev):
        commit = gh_api(f"repos/{REPO}/commits/{sha}")
        message = commit["commit"]["message"]
        title = message.splitlines()[0]
        if title.startswith("chore: bump version to"):
            continue  # commit de bump automatique

        note = extract_breaking(message)
        if note and note not in breaking:
            breaking.append(note)

        pulls = gh_api(f"repos/{REPO}/commits/{sha}/pulls") or []
        if pulls:
            for pr in pulls:
                if pr["number"] in seen_prs:
                    continue
                seen_prs.add(pr["number"])
                author = (pr.get("user") or {}).get("login")
                by = f" par {user_link(author, None)}" if author else ""
                changes.append(f"* {pr['title']}{by} dans #{pr['number']}")
        else:
            login = (commit.get("author") or {}).get("login")
            name = commit["commit"]["author"]["name"]
            changes.append(
                f"* {title} ([`{sha[:7]}`]({commit['html_url']})) par {user_link(login, name)}"
            )

    lines = []
    if breaking:
        lines += ["## ⚠️ Changements incompatibles", ""]
        lines += [f"- {note}" for note in breaking]
        lines.append("")

    lines += ["## Quoi de neuf", ""]
    lines += changes or ["_Aucun changement notable._"]
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
