#!/usr/bin/env bash
# Solo para un VPS IONOS NUEVO con Ubuntu 24.04 LTS / 22.04 LTS.
# Instala Docker desde el repositorio oficial y Git; NO cambia DNS ni firewall.
# No ejecutar en un servidor que aloje otros sitios sin revisar su configuración.
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "[ERROR] Ejecuta como root o mediante sudo."
  exit 1
fi
if [[ ! -f /etc/os-release ]]; then
  echo "[ERROR] No se reconoce el sistema operativo."
  exit 1
fi
. /etc/os-release
if [[ "$ID" != "ubuntu" || ( "$VERSION_ID" != "24.04" && "$VERSION_ID" != "22.04" ) ]]; then
  echo "[ERROR] Este instalador es para Ubuntu 22.04/24.04 LTS."
  echo "Usa la guia oficial para otro Linux: https://docs.docker.com/engine/install/"
  exit 1
fi
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "[OK] Docker y Docker Compose ya instalados; no se cambian."
  exit 0
fi
if dpkg-query -W -f='${Status}' docker.io 2>/dev/null | grep -q 'install ok installed'; then
  echo "[ERROR] Existe docker.io del repositorio Ubuntu."
  echo "Revisa cómo migrarlo a Docker CE SIN detener los servicios existentes."
  exit 1
fi

echo "[1/4] Dependencias basicas (Ubuntu)..."
apt-get update
apt-get install -y ca-certificates curl git
echo "[2/4] Clave oficial y repositorio apt Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
echo "[3/4] Instalando Docker Engine + Compose oficial..."
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
echo "[4/4] Activando Docker..."
systemctl enable --now docker
docker --version
docker compose version
echo
echo "[OK] VPS Ubuntu preparado para recibir ACMA."
echo "SIGUIENTE: crear dominio DNS A, copiar .env privado y ejecutar deploy/ionos/desplegar.sh."
echo "RECUERDA: abrir solo puertos 22 (SSH autorizado), 80 y 443 en el firewall IONOS."
