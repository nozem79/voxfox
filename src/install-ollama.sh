#!/bin/sh
# Installs a local Ollama server for VoxFox: unpack the official release into
# /usr and register a systemd service. Meant to run as root, started by
# VoxFox through pkexec (see nl.voxfox.install-ollama.policy) -- not by hand,
# although it works from a root shell too.
#
# This is deliberately NOT `curl https://ollama.com/install.sh | sh`. That
# script goes further than "install Ollama": when it finds an NVIDIA card
# without the proprietary driver it adds NVIDIA's package repository and
# installs the cuda-drivers stack (DKMS, kernel headers, sometimes a reboot),
# and for an AMD card it downloads a separate ROCm bundle. Rewriting somebody's
# graphics drivers because they clicked "install translation" is not what that
# button promises. This does only what Ollama documents as its manual install
# (https://docs.ollama.com/linux): unpack the release, create the ollama user,
# add the systemd unit. Anyone who wants GPU acceleration can run Ollama's own
# installer afterwards, knowing what it does.
#
# Nothing on the system is touched until the download has finished.
#
# Output, as read by install_ollama() in voxfox_core/translate.py: lines that
# start with ">>>" are progress, curl's progress bar carries the download
# percentage, and a line starting with "ERROR:" is the reason for a failure.
# Exit status is 0 or 1 only, so pkexec's own 126/127 stay unambiguous.

fail() { echo "ERROR: $*" >&2; exit 1; }
status() { echo ">>> $*"; }

[ "$(id -u)" -eq 0 ] || fail "this installer must run as root"

case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) fail "unsupported architecture: $(uname -m)" ;;
esac

for tool in curl zstd tar; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required but not installed"
done

TMP=$(mktemp -d) || fail "could not create a temporary directory"
trap 'rm -rf "$TMP"' EXIT

URL="https://ollama.com/download/ollama-linux-$ARCH.tar.zst"
status "Downloading Ollama"
curl --fail --show-error --location --progress-bar -o "$TMP/ollama.tar.zst" "$URL" \
    || fail "download failed ($URL)"

status "Installing Ollama to /usr"
rm -rf /usr/lib/ollama
zstd -d -c "$TMP/ollama.tar.zst" | tar -xf - -C /usr \
    || fail "could not unpack the download"
[ -x /usr/bin/ollama ] || fail "/usr/bin/ollama is missing after unpacking"

if ! id ollama >/dev/null 2>&1; then
    status "Creating the ollama user"
    useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama \
        || fail "could not create the ollama user"
fi
# GPU access for the service; harmless when the groups don't exist.
getent group render >/dev/null 2>&1 && usermod -a -G render ollama
getent group video >/dev/null 2>&1 && usermod -a -G video ollama

if command -v systemctl >/dev/null 2>&1; then
    status "Creating the ollama systemd service"
    cat > /etc/systemd/system/ollama.service <<'EOF' || fail "could not write the service file"
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=default.target
EOF
    case "$(systemctl is-system-running 2>/dev/null)" in
        running|degraded)
            status "Enabling and starting the ollama service"
            systemctl daemon-reload && systemctl enable ollama && systemctl restart ollama \
                || fail "could not start the ollama service"
            ;;
        *)
            echo "WARNING: systemd is not running; start Ollama yourself with: ollama serve"
            ;;
    esac
else
    echo "WARNING: systemd was not found; start Ollama yourself with: ollama serve"
fi

status "Install complete. The Ollama API is now available at 127.0.0.1:11434."
