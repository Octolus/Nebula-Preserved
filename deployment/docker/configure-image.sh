#!/usr/bin/env bash
# Resolve a published image pair and its build pins; never start an application.
set -euo pipefail

die() { printf '%s\n' "configure-image: $*" >&2; exit 1; }
[[ $# -ge 2 && $# -le 3 ]] || die 'usage: ./configure-image.sh ghcr.io/owner/repo tag [new-runtime.env]'
prefix=$1
tag=$2
output=${3:-runtime.env}
[[ $prefix =~ ^ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$ ]] || die 'use a lowercase ghcr.io/owner/repo image prefix'
[[ $tag =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die 'invalid image tag'
[[ $output =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.env$ ]] || die 'output must be a new .env filename in this directory'
[[ ! -e $output && ! -L $output ]] || die 'output already exists; preserve it and choose a new filename for an upgrade'
command -v docker >/dev/null 2>&1 || die 'Docker CLI is required'

server_repository=${prefix}-server
panel_repository=${prefix}-panel
docker pull --quiet "${server_repository}:${tag}" >/dev/null || die 'server image pull failed'
docker pull --quiet "${panel_repository}:${tag}" >/dev/null || die 'panel image pull failed'

resolve_image() {
    local reference=$1 repository=$2 id platform raw candidate selected=''
    id=$(docker image inspect --format '{{.Id}}' "$reference") || die 'pulled image inspection failed'
    [[ $id =~ ^sha256:[0-9a-f]{64}$ ]] || die 'immutable local image ID missing'
    platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$id") || die 'image platform inspection failed'
    [[ $platform == linux/amd64 ]] || die 'images must target Linux amd64'
    raw=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$id") || die 'image digest inspection failed'
    while IFS= read -r candidate; do
        [[ -z $candidate ]] && continue
        if [[ $candidate == "${repository}@"* ]]; then
            [[ ${candidate#*@} =~ ^sha256:[0-9a-f]{64}$ ]] || die 'malformed repository digest'
            [[ -z $selected || $selected == "$candidate" ]] || die 'ambiguous repository digests'
            selected=$candidate
        fi
    done <<< "$raw"
    [[ -n $selected ]] || die 'pulled image has no digest for the selected publisher'
    RESOLVED_ID=$id
    RESOLVED_REFERENCE=$selected
}

resolve_image "${server_repository}:${tag}" "$server_repository"
server_id=$RESOLVED_ID
server_reference=$RESOLVED_REFERENCE
resolve_image "${panel_repository}:${tag}" "$panel_repository"
panel_id=$RESOLVED_ID
panel_reference=$RESOLVED_REFERENCE

label() {
    docker image inspect --format "{{index .Config.Labels \"$2\"}}" "$1" || die 'image metadata inspection failed'
}
report=$(label "$server_id" 'io.github.nebula-preserved.build-report-sha256')
server=$(label "$server_id" 'io.github.nebula-preserved.server-sha256')
managed=$(label "$server_id" 'io.github.nebula-preserved.managed-sha256')
for pin in "$report" "$server" "$managed"; do
    [[ $pin =~ ^[0-9a-f]{64}$ ]] || die 'server image lacks a valid build-report, ELF or managed-assembly hash label'
done
server_revision=$(label "$server_id" 'org.opencontainers.image.revision')
panel_revision=$(label "$panel_id" 'org.opencontainers.image.revision')
[[ $server_revision =~ ^[0-9a-f]{40}$ && $panel_revision == "$server_revision" ]] || die 'server and panel revisions differ; wait for a complete publication and rerun'

umask 077
temporary=$(mktemp './.nebula-runtime-env.XXXXXXXXXX') || die 'cannot create private metadata staging file'
trap 'rm -f -- "$temporary"' EXIT
{
    printf 'NEBULA_BUILD_REPORT_SHA256=%s\n' "$report"
    printf 'NEBULA_SERVER_SHA256=%s\n' "$server"
    printf 'NEBULA_MANAGED_SHA256=%s\n' "$managed"
    printf 'NEBULA_IMAGE_PREFIX=%s\n' "$prefix"
    printf 'NEBULA_IMAGE_TAG=%s\n' "$tag"
    printf 'NEBULA_SERVER_IMAGE=%s\n' "$server_reference"
    printf 'NEBULA_PANEL_IMAGE=%s\n' "$panel_reference"
    printf 'NEBULA_SOURCE_REVISION=%s\n' "$server_revision"
} > "$temporary"
# GNU ln -T creates the destination exclusively, including against symlinks,
# FIFOs and directories. No existing runtime metadata can be overwritten.
ln -T -- "$temporary" "$output" || die 'output creation failed; no existing runtime metadata was changed'
printf 'Created %s for revision %s. No application or state was started or changed.\n' "$output" "$server_revision"
