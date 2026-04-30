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

map_rules 中每一项格式为 源键:目标键，例如 brightnessdown:f1。

如果键盘型号或设备名关键字变化，只需要修改 `device_keyword`。

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