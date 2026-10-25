#!/usr/bin/env bash
# Update the existing Compose installation without replacing its configuration.
set -Eeuo pipefail
umask 077

fail() { printf 'Update stopped: %s\n' "$*" >&2; exit 1; }
label() { docker inspect --format "{{index .Config.Labels \"$1\"}}" "$container"; }
healthy() {
    for ((attempt=0; attempt<30; attempt++)); do
        if docker exec "$container" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3)' >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

main() {
    repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
    cd -- "$repo"
    command -v git >/dev/null || fail 'Install Git first.'
    command -v docker >/dev/null || fail 'Install Docker first.'
    command -v flock >/dev/null || fail 'Install util-linux (flock) first.'
    docker compose version >/dev/null || fail 'Docker Compose v2 is required.'
    [[ "$(git branch --show-current)" == main ]] || fail 'Run this from the main branch.'
    git diff --quiet && git diff --cached --quiet || fail 'Tracked files have local edits. Preserve/reconcile them before updating.'
    case "$(git remote get-url origin)" in
        https://github.com/hahaw6517-creator/rongzhi-agent-native.git|https://github.com/hahaw6517-creator/rongzhi-agent-native|git@github.com:hahaw6517-creator/rongzhi-agent-native.git) ;;
        *) fail 'origin is not the FinBridge repository.' ;;
    esac
    if [[ "${1:-}" != --apply ]]; then
        git fetch origin main
        git merge --ff-only origin/main
        # Execute the newly fetched script rather than a partly read old file.
        exec bash "$repo/deploy/update.sh" --apply
    fi
    exec 9>"$(git rev-parse --git-path finbridge-update.lock)"
    flock -n 9 || fail 'Another update is running.'

    container=${FINBRIDGE_CONTAINER:-finbridge}
    [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]] || fail 'The existing container must be running.'
    project=$(label com.docker.compose.project)
    service=$(label com.docker.compose.service)
    directory=$(label com.docker.compose.project.working_dir)
    config_files=$(label com.docker.compose.project.config_files)
    [[ -n "$project" && "$project" != '<no value>' && "$service" == agent ]] || fail 'Expected an existing Compose agent service.'
    [[ -d "$directory" && -n "$config_files" && "$config_files" != '<no value>' ]] || fail 'Original Compose directory/files are unavailable.'
    [[ "$(docker inspect --format '{{.Config.Image}}' "$container")" == finbridge:latest ]] || fail 'Expected image finbridge:latest; custom installations need an explicit deployment update.'
    mount_before=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Type}}:{{.Name}}:{{.Source}}{{end}}{{end}}' "$container")
    [[ -n "$mount_before" ]] || fail '/app/storage must have persistent storage.'
    compose=(docker compose --project-directory "$directory" -p "$project")
    IFS=',' read -r -a files <<< "$config_files"
    for file in "${files[@]}"; do
        [[ -f "$file" ]] || fail "Missing Compose file: $file"
        compose+=(-f "$file")
    done
    "${compose[@]}" config --quiet
    old_image=$(docker inspect --format '{{.Image}}' "$container")
    revision=$(git rev-parse HEAD)
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup_dir="$repo/tmp/server-backups/$stamp"
    mkdir -p -- "$backup_dir"
    backup_path=$(docker exec -i "$container" python - "$stamp" <<'PY'
import os, sqlite3, sys
from pathlib import Path
source = Path(os.environ.get('FINBRIDGE_DB_PATH', '/app/storage/runtime.sqlite3')).resolve()
if not source.is_relative_to(Path('/app/storage')) or not source.is_file():
    raise SystemExit('Expected an existing SQLite database under /app/storage.')
target = source.parent / '.update-backups' / (sys.argv[1] + '.sqlite3')
target.parent.mkdir(exist_ok=True)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Database backup integrity check failed.')
print(target)
PY
    )
    docker cp "$container:$backup_path" "$backup_dir/runtime.sqlite3" >/dev/null
    printf 'Previous image: %s\nTarget commit: %s\n' "$old_image" "$revision" > "$backup_dir/version.txt"
    printf 'Database backed up to %s\nBuilding commit %s ...\n' "$backup_dir" "$revision"
    docker build --label "org.opencontainers.image.revision=$revision" -t finbridge:latest "$repo"
    new_image=$(docker image inspect --format '{{.Id}}' finbridge:latest)

    # From this point onward, recover the previous image if recreation or checks fail.
    trap 'rollback' ERR
    "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate "$service"
    healthy
    [[ "$(docker inspect --format '{{.Image}}' "$container")" == "$new_image" ]]
    [[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Type}}:{{.Name}}:{{.Source}}{{end}}{{end}}' "$container")" == "$mount_before" ]]
    trap - ERR
    printf 'Updated successfully: %s\nExisting Compose configuration and storage retained. Refresh the public website.\n' "$revision"
}

rollback() {
    trap - ERR
    printf 'Startup/check failed. Restoring the previous image...\n' >&2
    if docker image tag "$old_image" finbridge:latest && "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate "$service" && healthy; then
        printf 'Previous image restored. Database backup: %s\n' "$backup_dir" >&2
    else
        printf 'Automatic recovery failed. Inspect the Compose service; backup: %s\n' "$backup_dir" >&2
    fi
    exit 1
}

main "$@"
