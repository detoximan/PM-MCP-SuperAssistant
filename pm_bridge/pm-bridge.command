#!/bin/bash
# PM Bridge — КНОПКА ЗАПУСКА (macOS).
# Определяем папку проекта относительно места, где лежит .command файл.
PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
bash "$PROJ_DIR/bridge-up.sh"
