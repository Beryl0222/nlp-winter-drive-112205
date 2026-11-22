# 寒区试车叙述中

北沼联合试验组为合成车型构建本地文字试验台账。产品只核对文字与记录，不控制车辆。

## 资料格式

数据位于 `data/records.json`，以 UTF-8 保存。各表的记录以本表内的 `id` 或 `seq` 识别。原话保留提交时的文字。

温度为摄氏度，speed 为千米每小时，duration 为分钟。改进说法的模式、路段、阶段和对比容差由 claims 给出。一段运行可用来解释多个不同说法，同一说法的独立配对以 run 为口径。signoffs 存放已经对外引用的工程签认，签认原话可能窄于 claims 中拟核对的范围。

- `cars` 保存车队登记和版本。 字段为 `id`、`series`、`build`。
- `runs` 保存原始运行分段，阶段由驾驶日志确认。 字段为 `id`、`car`、`road`、`phase`、`mode`、`temp`、`speed`、`duration`、`started`。
- `notes` 保存试车员和乘员的手记。run_hint 为原登记范围，未必等于本句话描述。 字段为 `id`、`observer`、`run_hint`、`text`。
- `claims` 保存拟核定主张。required 指实际观察的独立证据下限。 字段为 `id`、`scope`、`type`、`required`、`evidence`。
- `signoffs` 保存在后续勘记以前作出的评审签认。 字段为 `id`、`claim`、`author`、`text`。
- `copy` 保存已上屏或备审的面向车主文字。 字段为 `id`、`state`、`refs`、`text`。

## 查看资料与自检

使用 Python 3.11.2 自带的标准库读取资料并验证字段和引用。

```sh
python3 -m json.tool data/records.json
python3 -m unittest discover -s tests -v
```
