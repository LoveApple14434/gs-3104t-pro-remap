# GS3104TPRO 键盘重映射

这是我为 GS3104TPRO 键盘配置的重映射规则。

之前发现这款键盘在 Linux 下 `F1` 到 `F12` 按键无法正常使用（无论是否按 `FN`），因此尝试通过 `evsieve` 做重映射。

## 设备发现方式

脚本会先执行 `libinput list-devices`，查找设备名包含配置项 `device_keyword` 的条目，然后读取对应的 `Kernel:` 路径（例如 `/dev/input/event11`），再把这些内核设备交给 `evsieve`。

如果你想手动指定设备，也可以在 `remap-gs3104tpro.yaml` 里保留 `input_devices` 列表；否则脚本会自动发现。

## 如何确定重映射规则

如果你不确定某个实体按键在系统里叫什么名字，可以先让系统把它识别出来，再把识别结果写进 `map_rules`。

1. 先按一下目标按键，观察系统输出的键名。常见方式是临时用 `libinput debug-events` 或 `evtest` 看这一键被识别成什么名字。
2. 记下这个名字作为 `map_rules` 里的左侧源键。
3. 再决定你希望它最终变成什么键名，把那个名字写到右侧目标键。

例如，如果按某个键时系统识别成 `brightnessdown`，而你希望它表现为 `f1`，就写成：

```yaml
map_rules:
  - "brightnessdown:f1"
```

如果要确认一组功能键，也可以依次按 `F1` 到 `F12`，把系统识别到的名字逐个记下来，再补到 YAML 里。

## 配置文件

- `remap-gs3104tpro.yaml`：重映射规则配置，包含 `device_keyword`、`grab_input` 和 `map_rules`
- `remap-gs3104tpro.sh`：读取 YAML 配置并启动 evsieve
- `kbd-drive-config-ui.py`：单页 Web 配置编辑器，支持读入、编辑、预览和保存 YAML

map_rules 中每一项格式为 源键:目标键，例如 brightnessdown:f1。

如果键盘型号或设备名关键字变化，只需要修改 `device_keyword`。

## 单页编辑器

项目内新增了一个本地单页网页应用，用于直接修改配置项并预览最终写出的 YAML。

它会自动打开浏览器页面，所有配置都在同一页内完成，不再使用文件选择框或分步弹窗。

它目前支持：

- 编辑 `device_keyword`
- 切换 `grab_input`
- 编辑 `input_devices`
- 编辑 `map_rules`
- 直接保存到 systemd 服务正在使用的 YAML 路径
- 查看 `gs3104tpro-remap.service` 的状态和最近日志
- 执行启动、停止、重启、启用、禁用等 service 操作

应用菜单默认启动的是桌面应用窗口（WebView），不会再单独弹出系统浏览器。

保存会直接写入 systemd 服务使用的 YAML 路径，不再让你选择位置；如果保存和服务操作需要权限，页面会尝试使用 `pkexec` 或 `sudo -n`。

如果安装了打包后的桌面入口，可以从应用菜单启动；开发状态下也可以直接运行 `kbd-drive-config-ui.py`。

### 编辑器排障

如果页面能打开但一直停在“正在加载配置…”，通常是本地运行的旧版本脚本仍在占用端口。可先结束旧进程后重启：

```bash
pkill -f kbd-drive-config-ui.py || true
python ./kbd-drive-config-ui.py
```

开发时请保持脚本内嵌 HTML/JS 模板为 raw string 形式（`Template(r"""...""")`），否则 Python 会吞掉 JavaScript 反斜杠，导致前端脚本在加载阶段报 `SyntaxError`，状态接口不会渲染到页面。

### 桌面应用启动

开发环境可直接运行：

```bash
python ./kbd-drive-desktop-app.py
```

该启动器会自动拉起本地后端并在窗口中加载配置页面，关闭窗口时会自动退出后端。

## 运行

```bash
sudo ./remap-gs3104tpro.sh
```

也可以指定配置文件路径：

```bash
sudo ./remap-gs3104tpro.sh /path/to/custom.yaml
```

## 配置开机自启动（systemd）

项目内提供了服务文件 `gs3104tpro-remap.service`，默认按 `/opt/kbd-drive` 这个位置来启动；如果你把仓库克隆到别的目录，需要同步修改其中的 `WorkingDirectory` 和 `ExecStart`。

可按以下方式安装并启用：

```bash
sudo install -m 0644 ./gs3104tpro-remap.service /etc/systemd/system/gs3104tpro-remap.service
sudo systemctl daemon-reload
sudo systemctl enable --now gs3104tpro-remap.service
```

查看运行状态：

```bash
sudo systemctl status gs3104tpro-remap.service --no-pager
```

## AUR 打包与发布

仓库已包含 AUR 需要的文件：

- `PKGBUILD`
- `.SRCINFO`
- `kbd-drive-remap-git.install`

本项目当前采用 `-git` 包名：`kbd-drive-remap-git`。

### 本地检查

```bash
makepkg --printsrcinfo > .SRCINFO
makepkg -si
```

### 发布到 AUR

```bash
# 1) 克隆你的 AUR 仓库（首次）
git clone ssh://aur@aur.archlinux.org/kbd-drive-remap-git.git aur-kbd-drive-remap-git

# 2) 复制打包文件
cp PKGBUILD .SRCINFO kbd-drive-remap-git.install aur-kbd-drive-remap-git/

# 3) 提交并推送
cd aur-kbd-drive-remap-git
git add PKGBUILD .SRCINFO kbd-drive-remap-git.install
git commit -m "Initial release"
git push
```

推送后可在 AUR 页面查看构建元数据是否更新。