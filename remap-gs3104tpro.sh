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

parse_yaml_config() {
    local yaml_file="$1"
    local line
    local in_map_rules="false"

    INPUT_DEVICE=""
    GRAB_INPUT="true"
    MAP_RULES=()

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"

        if [[ -z "${line//[[:space:]]/}" ]]; then
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*input_device:[[:space:]]*(.+)[[:space:]]*$ ]]; then
            INPUT_DEVICE="$(strip_yaml_value "${BASH_REMATCH[1]}")"
            in_map_rules="false"
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*grab_input:[[:space:]]*(.+)[[:space:]]*$ ]]; then
            GRAB_INPUT="$(strip_yaml_value "${BASH_REMATCH[1]}")"
            in_map_rules="false"
            continue
        fi

        if [[ "$line" =~ ^[[:space:]]*map_rules:[[:space:]]*$ ]]; then
            in_map_rules="true"
            continue
        fi

        if [[ "$in_map_rules" == "true" && "$line" =~ ^[[:space:]]*-[[:space:]]*(.+)[[:space:]]*$ ]]; then
            MAP_RULES+=("$(strip_yaml_value "${BASH_REMATCH[1]}")")
            continue
        fi

        if [[ "$line" =~ ^[^[:space:]] ]]; then
            in_map_rules="false"
        fi
    done < "$yaml_file"
}

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "配置文件不存在: $CONFIG_FILE" >&2
    echo "用法: $0 [配置文件路径]" >&2
    exit 1
fi

parse_yaml_config "$CONFIG_FILE"

if [[ -z "${INPUT_DEVICE:-}" ]]; then
    echo "配置错误: INPUT_DEVICE 不能为空" >&2
    exit 1
fi

if [[ ${#MAP_RULES[@]} -eq 0 ]]; then
    echo "配置错误: MAP_RULES 不能为空" >&2
    exit 1
fi

args=(--input "$INPUT_DEVICE")

if [[ "${GRAB_INPUT:-true}" == "true" ]]; then
    args+=(grab)
fi

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