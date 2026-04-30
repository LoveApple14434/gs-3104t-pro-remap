#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-$SCRIPT_DIR/remap-gs3104tpro.yaml}"

strip_yaml_value() {
    local value="$1"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    echo "$value"
}

discover_input_devices() {
    local device_keyword="$1"

    if ! command -v libinput >/dev/null 2>&1; then
        echo "配置错误: 找不到 libinput 命令，请先安装 libinput" >&2
        exit 1
    fi

    libinput list-devices | awk -v keyword="$device_keyword" '
        BEGIN { include = 0 }
        /^[[:space:]]*Device:[[:space:]]+/ {
            include = ($0 ~ keyword)
            next
        }
        include && /^[[:space:]]*Kernel:[[:space:]]+/ {
            kernel = $0
            sub(/^[[:space:]]*Kernel:[[:space:]]+/, "", kernel)
            print kernel
        }
    ' | awk '!seen[$0]++'
}

parse_yaml_config() {
    local yaml_file="$1"
    local line
    local section=""

    DEVICE_KEYWORD="GS3104T"
    INPUT_DEVICES=()
    GRAB_INPUT="true"
    MAP_RULES=()

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"

        if [[ -z "${line//[[:space:]]/}" ]]; then
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*input_device:[[:space:]]*(.+)[[:space:]]*$ ]]; then
            # Backward compatible with the old single-device key.
            INPUT_DEVICES=("$(strip_yaml_value "${BASH_REMATCH[1]}")")
            section=""
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*device_keyword:[[:space:]]*(.+)[[:space:]]*$ ]]; then
            DEVICE_KEYWORD="$(strip_yaml_value "${BASH_REMATCH[1]}")"
            section=""
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*input_devices:[[:space:]]*$ ]]; then
            INPUT_DEVICES=()
            section="input_devices"
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*grab_input:[[:space:]]*(.+)[[:space:]]*$ ]]; then
            GRAB_INPUT="$(strip_yaml_value "${BASH_REMATCH[1]}")"
            section=""
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*map_rules:[[:space:]]*$ ]]; then
            section="map_rules"
            continue
        fi

        if [[ "$section" == "input_devices" && "$line" =~ ^[[:space:]]*-[[:space:]]*(.+)[[:space:]]*$ ]]; then
            INPUT_DEVICES+=("$(strip_yaml_value "${BASH_REMATCH[1]}")")
            continue
        fi

        if [[ "$section" == "map_rules" && "$line" =~ ^[[:space:]]*-[[:space:]]*(.+)[[:space:]]*$ ]]; then
            MAP_RULES+=("$(strip_yaml_value "${BASH_REMATCH[1]}")")
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*[a-zA-Z_][a-zA-Z0-9_]*:[[:space:]]* ]]; then
            section=""
        fi
    done < "$yaml_file"
}

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "配置文件不存在: $CONFIG_FILE" >&2
    echo "用法: $0 [配置文件路径]" >&2
    exit 1
fi

parse_yaml_config "$CONFIG_FILE"

if [[ ${#INPUT_DEVICES[@]} -eq 0 ]]; then
    mapfile -t INPUT_DEVICES < <(discover_input_devices "$DEVICE_KEYWORD")
fi

if [[ ${#MAP_RULES[@]} -eq 0 ]]; then
    echo "配置错误: MAP_RULES 不能为空" >&2
    exit 1
fi

if [[ ${#INPUT_DEVICES[@]} -eq 0 ]]; then
    echo "配置错误: 未找到名称包含 ${DEVICE_KEYWORD} 的输入设备" >&2
    exit 1
fi

echo "检测到的输入设备:" >&2
printf '  %s\n' "${INPUT_DEVICES[@]}" >&2

args=()

for input_device in "${INPUT_DEVICES[@]}"; do
    args+=(--input "$input_device")

    if [[ "${GRAB_INPUT:-true}" == "true" ]]; then
        args+=(grab)
    fi
done

for rule in "${MAP_RULES[@]}"; do
    IFS=':' read -r src_key dst_key <<< "$rule"

    if [[ -z "$src_key" || -z "$dst_key" ]]; then
        echo "配置错误: 非法映射规则 '$rule'，格式应为 源键:目标键" >&2
        exit 1
    fi

    args+=(--map "key:${src_key}" "key:${dst_key}")
done

args+=(--output)

exec evsieve "${args[@]}"