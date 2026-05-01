#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from urllib.parse import urlparse


APP_TITLE = "Kbd Drive Remap Editor"
SERVICE_NAME = "gs3104tpro-remap.service"
DEFAULT_CONFIG_NAME = "remap-gs3104tpro.yaml"


@dataclass
class ConfigData:
    device_keyword: str = "GS3104T"
    grab_input: bool = True
    input_devices: list[str] = field(default_factory=list)
    map_rules: list[tuple[str, str]] = field(default_factory=list)


def strip_yaml_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def escape_yaml_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_config_text(text: str) -> ConfigData:
    config = ConfigData()
    section = ""

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if line.startswith("device_keyword:"):
            config.device_keyword = strip_yaml_value(line.split(":", 1)[1])
            section = ""
            continue

        if line.startswith("grab_input:"):
            config.grab_input = strip_yaml_value(line.split(":", 1)[1]).lower() == "true"
            section = ""
            continue

        if line.startswith("input_device:"):
            config.input_devices = [strip_yaml_value(line.split(":", 1)[1])]
            section = ""
            continue

        if line.startswith("input_devices:"):
            config.input_devices = []
            section = "input_devices"
            continue

        if line.startswith("map_rules:"):
            config.map_rules = []
            section = "map_rules"
            continue

        if section == "input_devices" and line.lstrip().startswith("-"):
            config.input_devices.append(strip_yaml_value(line.lstrip()[1:].strip()))
            continue

        if section == "map_rules" and line.lstrip().startswith("-"):
            rule = strip_yaml_value(line.lstrip()[1:].strip())
            if ":" in rule:
                src_key, dst_key = rule.split(":", 1)
                config.map_rules.append((src_key.strip(), dst_key.strip()))
            continue

        section = ""

    return config


def serialize_config(config: ConfigData) -> str:
    lines: list[str] = [f'device_keyword: "{escape_yaml_value(config.device_keyword)}"']
    lines.append(f"grab_input: {'true' if config.grab_input else 'false'}")

    if config.input_devices:
        lines.append("")
        lines.append("input_devices:")
        for device in config.input_devices:
            lines.append(f'  - "{escape_yaml_value(device)}"')

    lines.append("")
    lines.append("map_rules:")
    for src_key, dst_key in config.map_rules:
        lines.append(f'  - "{escape_yaml_value(src_key)}:{escape_yaml_value(dst_key)}"')

    return "\n".join(lines).rstrip() + "\n"


def validate_config(config: ConfigData) -> list[str]:
    errors: list[str] = []

    if not config.device_keyword.strip():
        errors.append("device_keyword 不能为空")

    if not config.map_rules:
        errors.append("map_rules 不能为空")

    seen_rules: set[tuple[str, str]] = set()
    for index, (src_key, dst_key) in enumerate(config.map_rules, start=1):
        if not src_key.strip() or not dst_key.strip():
            errors.append(f"第 {index} 条映射规则存在空值")
        if (src_key, dst_key) in seen_rules:
            errors.append(f"第 {index} 条映射规则重复")
        seen_rules.add((src_key, dst_key))

    if any(not device.strip() for device in config.input_devices):
        errors.append("input_devices 中存在空设备路径")

    return errors


def candidate_service_files() -> list[Path]:
    script_dir = Path(__file__).resolve().parent
    return [
        Path("/usr/lib/systemd/system") / SERVICE_NAME,
        script_dir / SERVICE_NAME,
    ]


def resolve_service_file_path() -> Path:
    for candidate in candidate_service_files():
        if candidate.exists():
            return candidate
    return candidate_service_files()[-1]


def resolve_config_path() -> Path:
    service_file = resolve_service_file_path()
    if service_file.exists():
        for line in service_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ExecStart="):
                try:
                    parts = shlex.split(line.split("=", 1)[1])
                except ValueError:
                    break
                for item in reversed(parts):
                    if item.endswith(".yaml") or item.endswith(".yml"):
                        return Path(item)

    script_dir = Path(__file__).resolve().parent
    fallback = script_dir / DEFAULT_CONFIG_NAME
    if fallback.exists():
        return fallback

    return Path("/etc/kbd-drive") / DEFAULT_CONFIG_NAME


def read_current_config() -> tuple[ConfigData, Path]:
    config_path = resolve_config_path()
    if config_path.exists():
        return parse_config_text(config_path.read_text(encoding="utf-8")), config_path

    fallback = Path(__file__).resolve().parent / DEFAULT_CONFIG_NAME
    if fallback.exists():
        return parse_config_text(fallback.read_text(encoding="utf-8")), config_path

    return ConfigData(), config_path


def run_command(command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, capture_output=True, text=True, check=False)


def run_privileged_command(command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if os.geteuid() == 0:
        return run_command(command, input_text=input_text)

    if shutil.which("pkexec"):
        return run_command(["pkexec", *command], input_text=input_text)

    if shutil.which("sudo"):
        return run_command(["sudo", "-n", *command], input_text=input_text)

    return subprocess.CompletedProcess(command, 1, "", "需要 root、pkexec 或 sudo 才能执行该操作")


def read_service_status() -> dict[str, str]:
    service_info = run_command([
        "systemctl",
        "show",
        SERVICE_NAME,
        "--no-pager",
        "--property=Description,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,ExecMainPID,ExecMainStatus",
    ])

    summary: dict[str, str] = {"ok": str(service_info.returncode == 0)}
    if service_info.returncode == 0:
        for line in service_info.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                summary[key] = value
    else:
        summary["error"] = service_info.stderr.strip() or service_info.stdout.strip() or "无法读取 systemd 状态"

    status_output = run_command(["systemctl", "status", SERVICE_NAME, "--no-pager", "--full", "--lines=12"])
    summary["status_text"] = status_output.stdout.strip() or status_output.stderr.strip()

    journal_output = run_command(["journalctl", "-u", SERVICE_NAME, "-n", "20", "--no-pager", "--output=short-iso"])
    summary["journal_text"] = journal_output.stdout.strip() or journal_output.stderr.strip()

    return summary


def save_config_to_fixed_path(config: ConfigData) -> None:
    config_path = resolve_config_path()
    rendered = serialize_config(config)

    if os.geteuid() == 0:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(rendered, encoding="utf-8")
        return

    temp_handle = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    try:
        temp_handle.write(rendered)
        temp_handle.flush()
        temp_handle.close()

        result = run_privileged_command(["install", "-D", "-m", "0644", temp_handle.name, str(config_path)])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "保存失败")
    finally:
        Path(temp_handle.name).unlink(missing_ok=True)


def run_service_action(action: str) -> None:
    result = run_privileged_command(["systemctl", action, SERVICE_NAME])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"systemctl {action} 失败")


def render_page() -> str:
    config_path = resolve_config_path()
    template = Template(r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #fef0f1;
      --panel: rgba(255, 255, 255, 0.82);
      --panel-strong: #ffffff;
      --text: #1c2430;
      --muted: #667181;
      --border: rgba(28, 36, 48, 0.14);
      --accent: #ec4899;
      --accent-2: #f472b6;
      --danger: #b91c1c;
      --shadow: 0 24px 60px rgba(28, 36, 48, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(236, 72, 153, 0.15), transparent 28%),
        radial-gradient(circle at right top, rgba(244, 114, 182, 0.12), transparent 24%),
        linear-gradient(180deg, #fff5f7 0%, var(--bg) 100%);
      min-height: 100vh;
    }
    .shell { max-width: 1520px; margin: 0 auto; padding: 28px; }
    .hero {
      display: flex; gap: 18px; justify-content: space-between; align-items: flex-start;
      padding: 24px 24px 20px; border: 1px solid var(--border); border-radius: 24px;
      background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(255,255,255,0.72));
      box-shadow: var(--shadow); backdrop-filter: blur(10px);
    }
    .hero h1 { margin: 0; font-size: clamp(28px, 4vw, 42px); letter-spacing: -0.03em; }
    .hero p { margin: 8px 0 0; color: var(--muted); line-height: 1.6; }
    .pill-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .pill {
      display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px;
      background: rgba(28, 36, 48, 0.04); border: 1px solid var(--border); color: var(--text);
      font-size: 13px;
    }
    .pill strong { font-weight: 700; }
    .layout {
      display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr); gap: 18px; margin-top: 18px;
    }
    .card {
      border: 1px solid var(--border); border-radius: 24px; background: var(--panel); box-shadow: var(--shadow);
      backdrop-filter: blur(10px); overflow: hidden;
    }
    .card-head {
      display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 18px 22px;
      border-bottom: 1px solid var(--border); background: rgba(255,255,255,0.55);
    }
    .card-head h2 { margin: 0; font-size: 18px; }
    .card-body { padding: 22px; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .field { display: flex; flex-direction: column; gap: 8px; }
    .field label { font-weight: 700; font-size: 13px; color: var(--muted); }
    input[type="text"], textarea {
      width: 100%; border: 1px solid var(--border); border-radius: 16px; background: var(--panel-strong);
      color: var(--text); padding: 12px 14px; font: inherit; outline: none; transition: border-color .15s ease, box-shadow .15s ease;
    }
    textarea { min-height: 138px; resize: vertical; line-height: 1.5; }
    input[type="text"]:focus, textarea:focus { border-color: rgba(204, 90, 45, 0.55); box-shadow: 0 0 0 4px rgba(204, 90, 45, 0.12); }
    .switch {
      display: inline-flex; align-items: center; gap: 10px; font-weight: 700; color: var(--text);
      padding: 12px 14px; border-radius: 16px; border: 1px solid var(--border); background: var(--panel-strong);
      width: fit-content;
    }
    .switch input { width: 18px; height: 18px; }
    .toolbar, .service-actions { display: flex; flex-wrap: wrap; gap: 10px; }
    button {
      border: 0; border-radius: 14px; padding: 10px 14px; font: inherit; font-weight: 700; cursor: pointer;
      transition: transform .12s ease, box-shadow .12s ease, opacity .12s ease; box-shadow: 0 10px 24px rgba(28, 36, 48, 0.08);
    }
    button:hover { transform: translateY(-1px); }
    .primary { background: linear-gradient(135deg, var(--accent), #e07a52); color: white; }
    .secondary { background: #f1efe9; color: var(--text); }
    .ghost { background: transparent; border: 1px solid var(--border); color: var(--text); box-shadow: none; }
    .danger { background: linear-gradient(135deg, #dc2626, #b91c1c); color: white; }
    .small { padding: 8px 12px; border-radius: 12px; font-size: 13px; }
    .muted { color: var(--muted); }
    .stack { display: grid; gap: 14px; }
    .preview {
      white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px;
      line-height: 1.6; background: #111827; color: #d1fae5; border-radius: 18px; padding: 16px; min-height: 320px;
      overflow: auto;
    }
    .status-box {
      background: #0f172a; color: #dbeafe; border-radius: 18px; padding: 16px; min-height: 160px; overflow: auto;
      white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px;
      will-change: contents;
    }
    .error-box {
      border-radius: 16px; padding: 12px 14px; background: rgba(185, 28, 28, 0.08); border: 1px solid rgba(185, 28, 28, 0.22);
      color: var(--danger); white-space: pre-wrap; line-height: 1.5;
    }
    .ok-box {
      border-radius: 16px; padding: 12px 14px; background: rgba(15, 118, 110, 0.08); border: 1px solid rgba(15, 118, 110, 0.22);
      color: #0f766e;
    }
    .footer-note { margin-top: 14px; color: var(--muted); font-size: 13px; line-height: 1.5; }
    .service-meta { display: grid; gap: 8px; font-size: 14px; color: var(--muted); }
    .service-meta strong { color: var(--text); }
    @media (max-width: 1080px) { .layout { grid-template-columns: 1fr; } .grid-2 { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1>$title</h1>
        <p>这是一个单页配置界面。修改会直接写回 systemd 服务所使用的 YAML 文件，不再弹出文件选择框。</p>
        <div class="pill-row">
          <div class="pill"><strong>配置文件</strong><span id="configPath">$config_path</span></div>
          <div class="pill"><strong>服务单元</strong><span>$service_name</span></div>
        </div>
      </div>
      <div class="toolbar">
        <button class="ghost" id="refreshAllBtn" type="button">刷新全部</button>
        <button class="primary" id="saveBtn" type="button">保存配置</button>
      </div>
    </div>

    <div class="layout">
      <div class="stack">
        <section class="card">
          <div class="card-head">
            <h2>配置编辑</h2>
            <div class="muted">在这一页内完成全部修改</div>
          </div>
          <div class="card-body stack">
            <div class="grid-2">
              <div class="field">
                <label for="deviceKeyword">device_keyword</label>
                <input id="deviceKeyword" type="text" autocomplete="off">
              </div>
              <div class="field">
                <label>grab_input</label>
                <label class="switch"><input id="grabInput" type="checkbox"><span>启用抓取输入</span></label>
              </div>
            </div>

            <div class="field">
              <label for="inputDevices">input_devices</label>
              <textarea id="inputDevices" placeholder="每行一个 /dev/input/event* 设备路径"></textarea>
            </div>

            <div class="field">
              <label for="mapRules">map_rules</label>
              <textarea id="mapRules" placeholder="每行一条 源键:目标键，例如 brightnessdown:f1"></textarea>
            </div>

            <div id="validationBox" class="ok-box">正在加载配置…</div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <h2>YAML 预览</h2>
            <div class="muted">保存前的最终结果</div>
          </div>
          <div class="card-body">
            <pre id="yamlPreview" class="preview"></pre>
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="card">
          <div class="card-head">
            <h2>systemd 状态</h2>
            <div class="service-actions">
              <button class="ghost small" data-action="reload-status" type="button">刷新状态</button>
              <button class="secondary small" data-action="start" type="button">启动</button>
              <button class="secondary small" data-action="stop" type="button">停止</button>
              <button class="secondary small" data-action="restart" type="button">重启</button>
              <button class="secondary small" data-action="enable" type="button">启用</button>
              <button class="secondary small" data-action="disable" type="button">禁用</button>
            </div>
          </div>
          <div class="card-body stack">
            <div class="service-meta" id="serviceMeta"></div>
            <pre id="serviceStatus" class="status-box"></pre>
            <div class="footer-note" id="serviceHint"></div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <h2>最近日志</h2>
            <div class="muted">journalctl -u $service_name</div>
          </div>
          <div class="card-body">
            <pre id="journalText" class="status-box"></pre>
          </div>
        </section>
      </div>
    </div>
  </div>

  <script>
    const state = {
      configPath: $config_path_json,
      serviceName: $service_name_json,
    };

    const deviceKeyword = document.getElementById('deviceKeyword');
    const grabInput = document.getElementById('grabInput');
    const inputDevices = document.getElementById('inputDevices');
    const mapRules = document.getElementById('mapRules');
    const yamlPreview = document.getElementById('yamlPreview');
    const validationBox = document.getElementById('validationBox');
    const serviceMeta = document.getElementById('serviceMeta');
    const serviceStatus = document.getElementById('serviceStatus');
    const journalText = document.getElementById('journalText');
    const serviceHint = document.getElementById('serviceHint');

    function yamlQuote(value) {
      return '"' + String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function buildYaml() {
      const deviceKeywordValue = deviceKeyword.value.trim();
      const inputDeviceLines = inputDevices.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      const ruleLines = mapRules.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      const rendered = [];
      rendered.push(`device_keyword: ${yamlQuote(deviceKeywordValue)}`);
      rendered.push(`grab_input: ${grabInput.checked ? 'true' : 'false'}`);
      if (inputDeviceLines.length) {
        rendered.push('');
        rendered.push('input_devices:');
        inputDeviceLines.forEach(line => rendered.push(`  - ${yamlQuote(line)}`));
      }
      rendered.push('');
      rendered.push('map_rules:');
      ruleLines.forEach(line => rendered.push(`  - ${yamlQuote(line)}`));
      return rendered.join('\n').replace(/\n+$$/,'') + '\n';
    }

    function validateClientState() {
      const errors = [];
      if (!deviceKeyword.value.trim()) errors.push('device_keyword 不能为空');
      const rules = mapRules.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      if (!rules.length) errors.push('map_rules 不能为空');
      rules.forEach((rule, index) => {
        if (!rule.includes(':')) errors.push(`第 ${index + 1} 条映射规则缺少冒号`);
        const parts = rule.split(':');
        const src = parts.shift().trim();
        const dst = parts.join(':').trim();
        if (!src || !dst) errors.push(`第 ${index + 1} 条映射规则存在空值`);
      });
      const devices = inputDevices.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      if (devices.some(item => !item)) errors.push('input_devices 中存在空设备路径');
      return errors;
    }

    function renderPreviewAndValidation() {
      yamlPreview.textContent = buildYaml();
      const errors = validateClientState();
      if (errors.length) {
        validationBox.className = 'error-box';
        validationBox.textContent = errors.join('\n');
      } else {
        validationBox.className = 'ok-box';
        validationBox.textContent = '配置有效，可以直接保存到服务使用的 YAML 文件。';
      }
    }

    function renderService(stateData) {
      const summary = [];
      summary.push(`<strong>ActiveState</strong>: ${stateData.ActiveState || 'unknown'}`);
      summary.push(`<strong>SubState</strong>: ${stateData.SubState || 'unknown'}`);
      summary.push(`<strong>UnitFileState</strong>: ${stateData.UnitFileState || 'unknown'}`);
      summary.push(`<strong>LoadState</strong>: ${stateData.LoadState || 'unknown'}`);
      summary.push(`<strong>FragmentPath</strong>: ${stateData.FragmentPath || 'unknown'}`);
      summary.push(`<strong>ExecMainPID</strong>: ${stateData.ExecMainPID || '0'}`);
      summary.push(`<strong>ExecMainStatus</strong>: ${stateData.ExecMainStatus || '0'}`);
      serviceMeta.innerHTML = summary.map(line => `<div>${line}</div>`).join('');

      serviceStatus.textContent = stateData.status_text || stateData.error || '没有可显示的 systemd 状态';
      journalText.textContent = stateData.journal_text || '没有日志';

      if (stateData.error) {
        serviceHint.innerHTML = `<span style="color: #b91c1c; font-weight: 700;">${escapeHtml(stateData.error)}</span>`;
      } else {
        serviceHint.textContent = `保存路径固定为 ${state.configPath}，服务状态通过 ${state.serviceName} 管理。`;
      }
    }

    async function apiGet(path) {
      const response = await fetch(path, { headers: { 'Accept': 'application/json' } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '请求失败');
      return payload;
    }

    async function apiPost(path, body) {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '请求失败');
      return payload;
    }

    async function loadState() {
      const payload = await apiGet('/api/state');
      state.configPath = payload.config_path;
      deviceKeyword.value = payload.config.device_keyword || '';
      grabInput.checked = Boolean(payload.config.grab_input);
      inputDevices.value = (payload.config.input_devices || []).join('\n');
      mapRules.value = (payload.config.map_rules || []).map(rule => `${rule[0]}:${rule[1]}`).join('\n');
      document.getElementById('configPath').textContent = payload.config_path;
      renderPreviewAndValidation();
      renderService(payload.service);
    }

    async function saveConfig() {
      renderPreviewAndValidation();
      const errors = validateClientState();
      if (errors.length) {
        alert('请先修正配置错误后再保存。\n\n' + errors.join('\n'));
        return;
      }
      const payload = {
        device_keyword: deviceKeyword.value.trim(),
        grab_input: grabInput.checked,
        input_devices: inputDevices.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean),
        map_rules: mapRules.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean),
      };
      await apiPost('/api/config', payload);
      await loadState();
    }

    async function runServiceAction(action) {
      await apiPost('/api/service', { action });
      await loadState();
    }

    async function quitEditor() {
      await apiPost('/api/quit', {});
    }

    document.getElementById('refreshAllBtn').addEventListener('click', loadState);
    document.getElementById('saveBtn').addEventListener('click', saveConfig);
    document.querySelectorAll('[data-action]').forEach(button => {
      button.addEventListener('click', async () => {
        const action = button.getAttribute('data-action');
        if (action === 'reload-status') {
          await loadState();
          return;
        }
        await runServiceAction(action);
      });
    });

    [deviceKeyword, grabInput, inputDevices, mapRules].forEach(element => {
      element.addEventListener('input', renderPreviewAndValidation);
      element.addEventListener('change', renderPreviewAndValidation);
    });

    loadState().catch(error => {
      validationBox.className = 'error-box';
      validationBox.textContent = error.message;
    });

    // 只定期刷新服务状态，不刷新表单数据以避免闪烁
    async function refreshServiceOnly() {
      try {
        const payload = await apiGet('/api/state');
        renderService(payload.service);
      } catch (error) {
        // 静默失败，不打断用户编辑
      }
    }

    setInterval(refreshServiceOnly, 5000);
  </script>
</body>
</html>
""".replace("${", "$${"))

    return template.substitute(
        title=html_escape(APP_TITLE),
        config_path=html_escape(str(config_path)),
        service_name=html_escape(SERVICE_NAME),
        config_path_json=json.dumps(str(config_path)),
        service_name_json=json.dumps(SERVICE_NAME),
    )


class EditorRequestHandler(BaseHTTPRequestHandler):
    server_version = "KbdDriveEditor/1.0"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _serve_state(self) -> None:
        config, config_path = read_current_config()
        self._send_json(
            {
                "config_path": str(config_path),
                "config": {
                    "device_keyword": config.device_keyword,
                    "grab_input": config.grab_input,
                    "input_devices": config.input_devices,
                    "map_rules": config.map_rules,
                },
                "service": read_service_status(),
            }
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            page = render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        if parsed.path == "/api/state":
            self._serve_state()
            return

        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                payload = self._read_json()
                config = ConfigData(
                    device_keyword=str(payload.get("device_keyword", "")).strip(),
                    grab_input=bool(payload.get("grab_input", True)),
                    input_devices=[str(item).strip() for item in payload.get("input_devices", []) if str(item).strip()],
                    map_rules=[],
                )
                for index, rule in enumerate(payload.get("map_rules", []), start=1):
                    if not isinstance(rule, str):
                        raise ValueError(f"第 {index} 条映射规则格式错误")
                    if ":" not in rule:
                        raise ValueError(f"第 {index} 条映射规则缺少冒号")
                    src_key, dst_key = rule.split(":", 1)
                    config.map_rules.append((src_key.strip(), dst_key.strip()))

                errors = validate_config(config)
                if errors:
                    self._send_json({"error": "\n".join(errors)}, 400)
                    return

                save_config_to_fixed_path(config)
                self._send_json({"ok": True, "message": f"已保存到 {resolve_config_path()}"})
                return

            if parsed.path == "/api/service":
                payload = self._read_json()
                action = str(payload.get("action", "")).strip()
                if action not in {"start", "stop", "restart", "enable", "disable", "reload", "reload-status"}:
                    self._send_json({"error": "不支持的 service 操作"}, 400)
                    return

                if action == "reload-status":
                    self._serve_state()
                    return

                run_service_action(action)
                self._send_json({"ok": True, "message": f"systemctl {action} {SERVICE_NAME} 已执行"})
                return

            if parsed.path == "/api/quit":
                self._send_json({"ok": True, "message": "编辑器已退出"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            self._send_json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def start_server(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer((host, port), EditorRequestHandler)
    return server, server.server_address[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    args = parser.parse_args()

    server, actual_port = start_server(args.host, args.port)
    url = f"http://{args.host}:{actual_port}/"
    print(f"{APP_TITLE}: {url}")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())