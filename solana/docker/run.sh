#!/usr/bin/env bash
# Host-side entrypoint: runs a command in the pinned Anchor container.
#
#   solana/docker/run.sh build          -> compile the program
#   solana/docker/run.sh test           -> anchor test against a local validator
#   solana/docker/run.sh sh             -> interactive shell
#
# MSYS_NO_PATHCONV is required on Git Bash for Windows, which otherwise rewrites
# container paths like /work into C:/Program Files/Git/work.
set -euo pipefail
IMAGE="solanafoundation/anchor:v0.31.1"
REPO_SOLANA="$(cd "$(dirname "$0")/.." && pwd)"
CMD="${1:-sh}"

case "$CMD" in
  build) INNER="sh /work/docker/build.sh" ;;
  test)  INNER="sh /work/docker/test.sh"  ;;
  sh)    INNER="sh" ;;
  *)     INNER="$*" ;;
esac

MSYS_NO_PATHCONV=1 docker run --rm -it \
  -v "${REPO_SOLANA}:/work" -w /work \
  --entrypoint sh "$IMAGE" -c "
    if [ ! -x /root/.local/share/solana/install/active_release/bin/solana ]; then
      sh -c \"\$(curl -sSfL https://release.anza.xyz/stable/install)\" >/dev/null 2>&1
    fi
    ${INNER}"
