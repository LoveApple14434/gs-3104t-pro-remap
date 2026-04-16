# GS3104TPRO 键盘重映射

这是我为 GS3104TPRO 键盘配置的重映射规则。

之前发现这款键盘在 Linux 下 F1 到 F12 按键无法正常使用（无论是否按 FN），因此尝试通过 evsieve 做重映射。

## 使用前先确认键盘 input device

先执行下面命令，观察输出中对应键盘事件的设备路径（例如 /dev/input/event11）：

sudo timeout 10 evsieve --input /dev/input/event* grab --print

把识别到的设备路径填写到 remap-gs3104tpro.yaml 的 input_device 字段。

## 配置文件

- remap-gs3104tpro.yaml：重映射规则配置
- remap-gs3104tpro.sh：读取 YAML 配置并启动 evsieve

map_rules 中每一项格式为 源键:目标键，例如 brightnessdown:f1。

## 运行

sudo ./remap-gs3104tpro.sh

也可以指定配置文件路径：

sudo ./remap-gs3104tpro.sh /path/to/custom.yaml