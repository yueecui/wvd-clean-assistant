# -*- coding: utf-8 -*-
"""任务结束时发送 Windows 桌面推送。

用系统自带 PowerShell 调 WinRT ToastNotificationManager，不引入第三方依赖，
绿色版也能用。异步发送、失败静默，绝不影响扫描 / 改造主流程。
WVD_NO_TOAST=1 可关闭（自动化测试时避免弹窗）。
"""
from __future__ import annotations

import base64
import os
import subprocess

_PS = r'''
$ErrorActionPreference = 'SilentlyContinue'
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  $t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
  $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t)
  $n = $x.GetElementsByTagName('text')
  $n.Item(0).AppendChild($x.CreateTextNode($env:WVD_TOAST_TITLE)) | Out-Null
  $n.Item(1).AppendChild($x.CreateTextNode($env:WVD_TOAST_BODY)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($x)
  $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
} catch {}
'''

_ENCODED = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")

_PHASE_LABEL = {"done": "已完成", "stopped": "已停止", "error": "出错"}


def notify(title: str, body: str) -> None:
    """发一条 toast；后台进程执行，任何异常都忽略。"""
    if os.name != "nt" or os.environ.get("WVD_NO_TOAST"):
        return
    try:
        env = os.environ.copy()
        env["WVD_TOAST_TITLE"] = title
        env["WVD_TOAST_BODY"] = body
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", _ENCODED],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def task_finished(task: str, phase: str, msg: str, total: str) -> None:
    """统一的结束通知：标题带任务名与结果，正文带摘要与总用时。"""
    notify(f"WVD 装备梳理 · {task}{_PHASE_LABEL.get(phase, '结束')}",
           f"{msg} · 总用时 {total}")
