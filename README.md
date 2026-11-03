# Spider 课程运营工作台

本机使用的小红书与闲鱼工作台。课程 PDF 可分别生成两份草稿，两边各自保存文案、选页与版本。闲鱼独立服务提供本地商品草稿和人工发布预览。生成或导入草稿不会触发发布。

| 目录 | 内容 |
| --- | --- |
| `xhs/xhs-all-in-one-local` | 工作台启动脚本、FastAPI 后端、React 前端及测试 |
| `xianyu/xianyu-auto-reply-local` | 闲鱼独立服务、桥接接口、发布预览及测试 |
| `xianyu/xianyu-auto-reply-local/source` | 闲鱼上游 Git 子模块 |

仓库保存源码和应用资源。题库原件、课程样张（含模板中的真实课件预览）、草稿数据、账号会话和运行配置保存在各自的本地目录。新安装会创建空数据库，需要另行指定题库目录和登录账号。

## 本机补齐的文件

小红书 SDK 的 `xhs_creator/js/reference_profile.json` 和 `xhs_pc/js/reference_profile.json` 是本机参考配置。两套 SDK 分别位于 `XHS_ALL_IN_ONE/xhs_utils/` 和 `XHS_ALL_IN_ONE/vendor/spider_xhs_23dab803/xhs_utils/`。从现有安装迁移时，把各自的文件按原相对路径补齐，然后在新安装中重新登录账号。

上游说明里的部分截图和图片可在下方的上游项目中查看。工作台导航使用的 `XHS_ALL_IN_ONE/frontend/public/logo.jpg` 可从现有安装补齐，再构建前端。

## 本机启动工作台

使用 macOS、Python 3.12、Node.js 22 及 npm。在仓库根目录执行：

```sh
cd xhs/xhs-all-in-one-local
python3.12 -m venv .venv
.venv/bin/python -m pip install -r XHS_ALL_IN_ONE/requirements.txt
npm --prefix XHS_ALL_IN_ONE ci
npm --prefix XHS_ALL_IN_ONE/frontend ci
npm --prefix XHS_ALL_IN_ONE/frontend run build
mkdir -p data
.venv/bin/python manage.py configure
.venv/bin/python manage.py start
```

打开 [工作台](http://127.0.0.1:8000)。启动器为本机生成随机密钥，默认绑定 `127.0.0.1` 并关闭后台调度。首次使用先在本机注册工作台用户。需要启用题库时，可在新生成的 `config.local.yaml` 中设置 `course_center.enabled`、`course_library.enabled`、`course_library.root` 和 `course_library.owner_id`，然后重启工作台。

## 接入闲鱼独立服务

1. 在仓库根目录执行 `git submodule update --init`。
2. 进入 `xianyu/xianyu-auto-reply-local`，创建 Python 3.12 的 `.venv`，安装 `requirements-local.txt`。
3. 按 `manage.py` 中的路径准备本机 MySQL 8.4.11 和 Redis 7.2.17，再运行 `.venv/bin/python manage.py configure`。配置生成在本机 `private/config.json`。
4. 在工作台的 `runtime/xianyu-connector.json` 中设置 `base_url` 为 `http://127.0.0.1:18089`。将两边的 `owner_user_id` 设为实际工作台用户 ID，将独立服务生成的 `bridge_token` 配到工作台桥接文件。
5. 在闲鱼独立服务目录运行 `.venv/bin/python manage.py start`，在工作台闲鱼页绑定账号。新配置默认以草稿模式启动。

## 上游来源

- [cv-cat/XHS_ALL_IN_ONE](https://github.com/cv-cat/XHS_ALL_IN_ONE/tree/e86f82bbf07e36b30c74a00f2b6745d63cb6cadc) 为工作台基线。上游 README 和声明随源码保留。
- [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS/tree/23dab803a0465e35e01cf87137353a900b47e93d) 的 SDK 版本与文件校验记录见 `vendor/spider_xhs_23dab803/SDK_SOURCE.json`。
- [zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply/tree/888fe4164c0a9779065cabf2092c825b47200153) 由子模块锁定。上游 AGPL-3.0 许可证见 `LICENSE.upstream`。
