#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@37.27.6.17}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/opt/protracklite}"
SSH_KEY="${SSH_KEY:-/home/shantanu/mykey.key}"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no)
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
ARCHIVE_NAME="protracklite-${TIMESTAMP}.tar.gz"
REMOTE_TMP="/tmp/${ARCHIVE_NAME}"

require_clean_worktree() {
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Refusing to deploy with unstaged or uncommitted changes."
    echo "Commit or stash your changes first."
    exit 1
  fi
}

push_code() {
  if [[ "${SKIP_PUSH:-0}" == "1" ]]; then
    echo "Skipping git push because SKIP_PUSH=1."
    return
  fi
  echo "Pushing main to origin..."
  git push origin main
}

build_archive() {
  echo "Building release archive..."
  git archive --format=tar.gz -o "$ARCHIVE_NAME" HEAD
}

upload_archive() {
  echo "Uploading archive to ${REMOTE_HOST}..."
  scp "${SSH_OPTS[@]}" "$ARCHIVE_NAME" "${REMOTE_HOST}:${REMOTE_TMP}"
}

deploy_remote() {
  echo "Deploying on ${REMOTE_HOST}..."
  ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
    "set -euo pipefail
    mkdir -p '${REMOTE_APP_DIR}'
    tar -xzf '${REMOTE_TMP}' -C '${REMOTE_APP_DIR}'
    rm -f '${REMOTE_TMP}'
    cd '${REMOTE_APP_DIR}'
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    install -m 644 deploy/protracklite.service /etc/systemd/system/protracklite.service
    systemctl daemon-reload
    systemctl restart protracklite
    systemctl --no-pager --full status protracklite
    "
}

cleanup() {
  rm -f "$ARCHIVE_NAME"
}

main() {
  require_clean_worktree
  trap cleanup EXIT
  push_code
  build_archive
  upload_archive
  deploy_remote
  echo "Deployment complete."
}

main "$@"
