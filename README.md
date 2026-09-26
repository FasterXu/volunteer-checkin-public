# 志愿者活动签到系统

一个可直接运行的 Flask + SQLite 签到系统。视觉参考经典 Bootstrap 管理页：深色/绿色导航、白底内容区、双语标题、紧凑表格，以及绿色成功、红色异常状态。

## 已实现功能

- 创建活动，设置地点、说明、开始和结束时间
- 活动状态：准备中、进行中、已结束
- 导入 CSV / XLSX 名单，必填“姓名”“学号/工号”，可选“手机号”“岗位”
- 重复导入时按学号/工号更新资料，并保留已有签到状态
- 每场活动自动生成唯一签到码和二维码
- 参与者移动端扫码，填写姓名和学号/工号完成核验签到
- 已登记手机号时，可用手机号进行辅助核验
- 数据库条件更新防止同一人员重复签到
- 管理后台每 5 秒自动刷新，无需手动重载页面
- 每场活动自动生成高强度随机观察员链接，可免登录只读查看、筛选和导出签到结果
- 总人数、已签到、未签到、签到率统计卡片
- 全部 / 已签到 / 未签到一键筛选，姓名、编号、手机号、岗位搜索
- CSV 导出完整签到结果或仅导出未签到名单
- 管理员手工补签和取消签到，可填写备注
- 管理员可修改活动名称、地点、时间和说明
- 签到记录中可修改姓名、学号/工号、手机号、岗位和备注，或删除名单人员
- 记录签到时间、签到来源和备注
- 导出内容自动防护表格公式注入，另提供 `/healthz` 部署健康检查
- 响应式布局，适配手机与电脑

## 目录结构

```text
sign-in-system/
├─ app.py                 # Flask 应用与数据库逻辑
├─ requirements.txt       # Python 依赖
├─ sample_roster.csv      # 示例名单
├─ templates/             # 管理端与移动端模板
├─ static/                # 样式和管理端实时刷新脚本
└─ data/                  # 首次运行自动创建 SQLite 数据库
```

## 本地启动

需要 Python 3.10 或更高版本。

### Windows PowerShell

```powershell
cd sign-in-system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

### macOS / Linux

```bash
cd sign-in-system
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

浏览器打开 `http://127.0.0.1:5000/admin`。

推荐体验顺序：

1. 创建活动。
2. 上传 `sample_roster.csv`，也可以按相同表头制作 XLSX 文件。
3. 点击“开始活动”。
4. 显示二维码，或直接点击“打开手机签到页”。
5. 使用示例姓名与学号完成签到，观察后台实时变化。

## 让手机扫码访问

电脑与手机需处于同一局域网。先查看电脑局域网 IP，例如 `192.168.1.20`，再启动服务：

```powershell
$env:PUBLIC_BASE_URL="http://192.168.1.20:5000"
python app.py
```

确认系统防火墙允许 5000 端口后，系统生成的二维码就会指向这个地址。

## 生产部署

Linux 可使用 Gunicorn：

```bash
export SECRET_KEY='请替换为足够长的随机字符串'
export PUBLIC_BASE_URL='https://checkin.example.com'
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Windows 可使用 Waitress：

```powershell
$env:SECRET_KEY="请替换为足够长的随机字符串"
$env:PUBLIC_BASE_URL="https://checkin.example.com"
waitress-serve --listen=0.0.0.0:8000 app:app
```

环境变量：

| 名称 | 用途 | 默认值 |
|---|---|---|
| `SECRET_KEY` | Flask 会话签名；生产环境必须设置 | 自动生成的开发值 |
| `ADMIN_PASSWORD` | 管理后台登录密码；公网部署必须设置 | 未设置时仅适合本地开发 |
| `PUBLIC_BASE_URL` | 二维码使用的公开访问根地址 | 当前请求地址 |
| `SIGNIN_DATABASE` | SQLite 文件路径 | `data/signin.db` |
| `PORT` | `python app.py` 的监听端口 | `5000` |

生产环境建议置于 HTTPS 反向代理之后，并务必设置 `ADMIN_PASSWORD`。管理页面、活动管理接口、名单导入导出及补签操作都会受到登录保护；参与者签到页、观察员页面和健康检查保持公开。观察员链接包含不可猜测的随机令牌，但持有链接者可以查看和导出完整名单，应按敏感链接管理并谨慎分享。

项目包含 `render.yaml`，可通过 Render Blueprint 部署。当前配置使用新加坡区域的免费单实例，适合上线试用；创建 Blueprint 时必须填写 `ADMIN_PASSWORD`，Render 会自动生成 `SECRET_KEY`。免费实例没有持久化磁盘，SQLite 数据可能在重新部署、重启或平台回收实例后丢失，正式使用前应升级付费实例并挂载磁盘，或迁移至托管数据库。

## 名单格式

CSV 和 XLSX 的首行是表头。系统也兼容 `名字`、`编号`、`联系电话`、`职位`、`职务`、`name`、`identifier`、`phone`、`position` 等常见别名。

```csv
姓名,学号/工号,手机号,岗位
示例用户甲,DEMO-001,,签到引导
示例用户乙,DEMO-002,,秩序维护
示例用户丙,DEMO-003,,物资管理
```

CSV 推荐使用 UTF-8 编码；系统也会尝试读取常见的 GB18030 编码。单次上传限制为 8 MB。

## 数据备份

所有业务数据保存在 `data/signin.db`。停止应用后复制该文件即可完成备份。恢复时把备份文件放回相同位置。
