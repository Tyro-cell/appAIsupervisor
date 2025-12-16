from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path
import json

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.utils import platform
from kivy.core.text import LabelBase
from kivy.logger import Logger
from ctypes import Structure, byref, c_long
import ctypes

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import OneLineListItem, TwoLineListItem, ThreeLineListItem
from kivymd.uix.button import MDFlatButton, MDFillRoundFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.boxlayout import MDBoxLayout
try:
    from kivymd.uix.snackbar import Snackbar
except Exception:  # pragma: no cover
    Snackbar = None

from app.ai import SUPERVISOR_SYSTEM, build_client, safe_json_extract, suspicion_score
from app.fonts import find_cjk_font
from app.scheduler import ReminderScheduler
from app.storage import Storage, TaskRow


class AiSupervisorApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.storage: Storage | None = None
        self.scheduler: ReminderScheduler | None = None
        self._dialogs: list[MDDialog] = []

    def build(self):
        Window.minimum_width, Window.minimum_height = 390, 780
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        if hasattr(self.theme_cls, "material_style"):
            self.theme_cls.material_style = "M3"
        self._configure_cjk_fonts()
        Window.bind(on_touch_down=self._normalize_touch_down)
        Window.bind(on_touch_up=self._normalize_touch_up)
        root = Builder.load_file("app/ui.kv")
        # Default tab.
        try:
            root.ids.sm.current = "today"
        except Exception:
            pass
        if platform == "android":
            try:
                from android.storage import app_storage_path  # type: ignore

                data_dir = Path(app_storage_path())
            except Exception:
                data_dir = Path(self.user_data_dir)
        else:
            data_dir = Path(self.user_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(db_path=data_dir / "ai_supervisor.sqlite3")
        self.scheduler = ReminderScheduler(self.storage)
        if platform == "android":
            self._maybe_start_android_service()
        Clock.schedule_once(lambda *_: self.refresh_all(), 0)
        self.scheduler.start()
        Clock.schedule_interval(lambda *_: self._tick_scheduler(), 30)
        return root

    def switch_tab(self, name: str):
        try:
            self.root.ids.sm.current = name
        except Exception:
            return
        title_map = {
            "today": "AI督学师",
            "plans": "计划",
            "checkin": "打卡",
            "history": "记录",
            "settings": "设置",
        }
        try:
            self.root.ids.topbar.title = title_map.get(name, "AI督学师")
        except Exception:
            pass

    def _normalize_touch_down(self, _window, touch):
        """
        Workaround for some Windows setups where SDL2 mouse positions are reported
        outside the window bounds (e.g. negative y), breaking widget hit-testing.
        If `touch.spos` looks sane, re-map `touch.pos` from normalized coords.
        """
        try:
            w, h = Window.size
            x, y = touch.pos
            btn = getattr(touch, "button", "")
            spos = getattr(touch, "spos", None)
            mouse_pos = getattr(Window, "mouse_pos", None)
            win_pos = self._win_client_mouse_pos()
            Logger.info(
                f"TOUCH: down pos={touch.pos} spos={spos} size={(w, h)} mouse_pos={mouse_pos} win_pos={win_pos} button={btn}"
            )

            # Windows workaround: use WinAPI cursor position in client coords.
            if win_pos is not None:
                mx, my = win_pos
                Logger.info(f"TOUCH: correcting via winapi {touch.pos} -> {(mx, my)}")
                touch.pos = (mx, my)
                try:
                    touch.spos = (mx / w, my / h)
                except Exception:
                    pass
                return False

            # Fallback: if SDL2 reports broken coordinates, try Window.mouse_pos.
            if w > 0 and h > 0:
                out_of_bounds = x < 0 or y < 0 or x > w or y > h
                spos_bad = False
                if isinstance(spos, (list, tuple)) and len(spos) == 2:
                    try:
                        sx, sy = float(spos[0]), float(spos[1])
                        spos_bad = sx < 0.0 or sy < 0.0 or sx > 1.0 or sy > 1.0
                    except Exception:
                        spos_bad = True
                else:
                    spos_bad = True

                if out_of_bounds or spos_bad:
                    mp = Window.mouse_pos
                    if isinstance(mp, (list, tuple)) and len(mp) == 2:
                        mx, my = float(mp[0]), float(mp[1])
                        if 0.0 <= mx <= w and 0.0 <= my <= h:
                            Logger.info(f"TOUCH: correcting via mouse_pos {touch.pos} -> {(mx, my)}")
                            touch.pos = (mx, my)
                            try:
                                touch.spos = (mx / w, my / h)
                            except Exception:
                                pass
        except Exception:
            pass
        return False

    def _normalize_touch_up(self, _window, touch):
        try:
            w, h = Window.size
            x, y = touch.pos
            spos = getattr(touch, "spos", None)
            if w > 0 and h > 0:
                win_pos = self._win_client_mouse_pos()
                if win_pos is not None:
                    mx, my = win_pos
                    touch.pos = (mx, my)
                    try:
                        touch.spos = (mx / w, my / h)
                    except Exception:
                        pass
                    return False

                out_of_bounds = x < 0 or y < 0 or x > w or y > h
                spos_bad = False
                if isinstance(spos, (list, tuple)) and len(spos) == 2:
                    try:
                        sx, sy = float(spos[0]), float(spos[1])
                        spos_bad = sx < 0.0 or sy < 0.0 or sx > 1.0 or sy > 1.0
                    except Exception:
                        spos_bad = True
                else:
                    spos_bad = True

                if out_of_bounds or spos_bad:
                    mp = Window.mouse_pos
                    if isinstance(mp, (list, tuple)) and len(mp) == 2:
                        mx, my = float(mp[0]), float(mp[1])
                        if 0.0 <= mx <= w and 0.0 <= my <= h:
                            touch.pos = (mx, my)
                            try:
                                touch.spos = (mx / w, my / h)
                            except Exception:
                                pass
        except Exception:
            pass
        return False

    def _win_client_mouse_pos(self):
        if platform not in ("win", "windows"):
            return None
        try:
            wi = Window.get_window_info()
            hwnd = int(getattr(wi, "window", 0) or 0)
            if not hwnd:
                return None

            class POINT(Structure):
                _fields_ = [("x", c_long), ("y", c_long)]

            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(byref(pt)) == 0:
                return None
            if ctypes.windll.user32.ScreenToClient(hwnd, byref(pt)) == 0:
                return None

            w, h = Window.size
            # WinAPI client coords origin: top-left. Kivy: bottom-left.
            x = float(pt.x)
            y = float(h - pt.y)
            if x < 0 or y < 0 or x > w or y > h:
                # Allow slight out-of-bounds for title bar; ignore.
                return None
            return (x, y)
        except Exception:
            return None

    def _configure_cjk_fonts(self) -> None:
        """
        Fix CJK garbled text by switching KivyMD's Roboto fonts to a CJK-capable font.
        On Windows this typically resolves to Microsoft YaHei.
        """
        plat = platform
        plat_key = "win" if plat in ("win", "windows") else plat
        font_path = find_cjk_font(plat_key)
        if not font_path:
            return
        # KivyMD 1.x uses these font names internally.
        for name in ("Roboto", "RobotoThin", "RobotoLight", "RobotoMedium", "RobotoBlack"):
            try:
                LabelBase.register(
                    name=name,
                    fn_regular=font_path,
                    fn_bold=font_path,
                    fn_italic=font_path,
                    fn_bolditalic=font_path,
                )
            except Exception:
                pass

    def _maybe_start_android_service(self):
        try:
            from android import AndroidService  # type: ignore

            service = AndroidService("AI督学师", "后台督学提醒运行中")
            service.start("reminders")
        except Exception:
            pass

    def _tick_scheduler(self):
        if self.scheduler:
            self.scheduler.tick()

    # ---- UI refresh ----
    def refresh_all(self):
        self.refresh_today()
        self.refresh_plans()
        self.refresh_checkin()
        self.refresh_history()
        self.load_settings_into_ui()

    def refresh_today(self):
        root = self.root
        tasks = self._s().list_tasks_for_day(date.today())
        lst = root.ids.today_task_list
        lst.clear_widgets()
        for t in tasks:
            lst.add_widget(self._task_item(t))
        if not tasks:
            lst.add_widget(self._empty_item("今天还没有任务", "去“计划/今日”添加一个最小任务块"))

    def refresh_checkin(self):
        root = self.root
        tasks = self._s().list_tasks_for_day(date.today())
        lst = root.ids.checkin_task_list
        lst.clear_widgets()
        for t in tasks:
            status = "✅已完成" if t.status == "done" else "⏳待打卡"
            item = TwoLineListItem(
                text=f"{t.start_time}-{t.end_time}  {t.title}",
                secondary_text=f"{status} · 点我打卡/补充汇报",
                on_release=lambda _w, task_id=t.id: self.open_checkin(task_id),
            )
            lst.add_widget(item)
        if not tasks:
            lst.add_widget(self._empty_item("没有可打卡任务", "先创建计划或添加今日任务"))

    def refresh_plans(self):
        root = self.root
        plans = self._s().list_plans()
        lst = root.ids.plan_list
        lst.clear_widgets()
        for p in plans:
            item = TwoLineListItem(
                text=str(p["title"]),
                secondary_text=f"{p['domain']} · {p['start_date']}→{p['end_date']}",
                on_release=lambda _w, pid=int(p["id"]): self.open_plan(pid),
            )
            lst.add_widget(item)
        if not plans:
            lst.add_widget(self._empty_item("还没有计划", "创建一个：Python全栈 · 12周冲刺"))

    def refresh_history(self):
        root = self.root
        rows = self._s().list_checkins_recent(limit=50)
        lst = root.ids.history_list
        lst.clear_widgets()
        for r in rows:
            text = f"{r['task_day']} · {r['task_title']}"
            sub = f"自评{r['self_score']}/10 · 质疑{r['suspicion_score']}/100"
            item = TwoLineListItem(
                text=text,
                secondary_text=sub,
                on_release=lambda _w, rid=int(r["id"]): self.open_checkin_record(rid),
            )
            lst.add_widget(item)
        if not rows:
            lst.add_widget(self._empty_item("还没有打卡记录", "从“打卡”开始，连续3天就会有变化"))

    def _task_item(self, t: TaskRow):
        status = "✅" if t.status == "done" else "•"
        return ThreeLineListItem(
            text=f"{status} {t.start_time}-{t.end_time}  {t.title}",
            secondary_text=t.description[:60],
            tertiary_text=f"状态：{t.status}",
            on_release=lambda _w, task_id=t.id: self.open_task(task_id),
        )

    def _empty_item(self, headline: str, supporting: str):
        return TwoLineListItem(text=headline, secondary_text=supporting)

    # ---- dialogs ----
    def open_add_task(self):
        Logger.info("[UI] open_add_task")
        plan_id = self._ensure_default_plan()
        content = MDBoxLayout(orientation="vertical", spacing=dp(12), padding=(0, dp(8), 0, 0))
        tf_title = MDTextField(mode="rectangle", hint_text="任务标题（最小可执行）")
        tf_desc = MDTextField(mode="rectangle", hint_text="任务说明/验收方式（例如：完成一个API并写测试）")
        tf_start = MDTextField(mode="rectangle", hint_text="开始时间（HH:MM）", text="20:00")
        tf_end = MDTextField(mode="rectangle", hint_text="结束时间（HH:MM）", text="21:00")
        content.add_widget(tf_title)
        content.add_widget(tf_desc)
        content.add_widget(tf_start)
        content.add_widget(tf_end)

        dialog = MDDialog(
            title="添加今日任务",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="取消", on_release=lambda *_: dialog.dismiss()),
                MDFillRoundFlatButton(
                    text="创建",
                    on_release=lambda *_: self._create_task_from_dialog(
                        dialog, plan_id, tf_title.text, tf_desc.text, tf_start.text, tf_end.text
                    ),
                ),
            ],
        )
        self._dialogs.append(dialog)
        dialog.open()

    def _ensure_default_plan(self) -> int:
        plans = self._s().list_plans()
        if plans:
            return int(plans[0]["id"])
        start = date.today()
        end = start + timedelta(days=84)
        return self._s().create_plan(
            title="默认计划：自驱力重建",
            domain="通用学习",
            long_goal="建立可持续学习节奏：每日最小学习单元 + 可验证产出",
            start=start,
            end=end,
        )

    def _create_task_from_dialog(self, dialog, plan_id: int, title: str, desc: str, start: str, end: str):
        title = (title or "").strip()
        if not title:
            self.toast("任务标题不能为空")
            return
        self._s().create_task(
            plan_id=plan_id,
            day=date.today(),
            start_time=(start or "20:00").strip(),
            end_time=(end or "21:00").strip(),
            title=title,
            description=(desc or "").strip() or "打卡时说明你做了什么，并给出可验证证据",
        )
        dialog.dismiss()
        self.refresh_all()
        self.toast("已添加任务")

    def open_create_plan(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12), padding=(0, dp(8), 0, 0))
        tf_title = MDTextField(mode="rectangle", hint_text="计划标题（如：Python全栈12周）")
        tf_domain = MDTextField(mode="rectangle", hint_text="领域（如：Python后端/全栈）", text="Python全栈")
        tf_goal = MDTextField(mode="rectangle", hint_text="长期目标（可量化）", multiline=True)
        tf_weeks = MDTextField(mode="rectangle", hint_text="周期（周，默认12）", input_filter="int", text="12")
        content.add_widget(tf_title)
        content.add_widget(tf_domain)
        content.add_widget(tf_goal)
        content.add_widget(tf_weeks)

        dialog = MDDialog(
            title="创建计划（可让AI拆解）",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="取消", on_release=lambda *_: dialog.dismiss()),
                MDFillRoundFlatButton(
                    text="创建并拆解7天",
                    on_release=lambda *_: self._create_plan_and_breakdown(
                        dialog, tf_title.text, tf_domain.text, tf_goal.text, tf_weeks.text
                    ),
                ),
            ],
        )
        self._dialogs.append(dialog)
        dialog.open()

    def _create_plan_and_breakdown(self, dialog, title: str, domain: str, goal: str, weeks: str):
        title = (title or "").strip() or "未命名计划"
        domain = (domain or "").strip() or "通用"
        goal = (goal or "").strip() or "提升该领域能力，形成作品/可证明产出"
        w = int((weeks or "12").strip() or "12")
        start = date.today()
        end = start + timedelta(days=7 * w)
        plan_id = self._s().create_plan(title=title, domain=domain, long_goal=goal, start=start, end=end)
        dialog.dismiss()
        self.refresh_plans()
        self.toast("计划已创建，正在让AI拆解…")
        threading.Thread(target=self._ai_breakdown_7days, args=(plan_id,), daemon=True).start()

    def _ai_breakdown_7days(self, plan_id: int):
        plan = self._s().get_plan(plan_id)
        if not plan:
            return
        base_url = self._s().get_setting("ai_base_url", "")
        api_key = self._s().get_setting("ai_api_key", "")
        model = self._s().get_setting("ai_model", "")
        client = build_client(base_url, api_key, model)

        prompt = f"""
学习者计划：
标题：{plan['title']}
领域：{plan['domain']}
长期目标：{plan['long_goal']}
先做“计划合理化建议”（如果目标过大/不现实，主动缩小范围、加入缓冲、给出可验证的阶段产出）。
再输出未来7天的“每日任务块”，每一天给2-3个任务块，每个任务块包含：
- start_time: "HH:MM"
- end_time: "HH:MM"
- title: 最小可执行
- description: 验收方式（必须可验证）
输出严格JSON：{{"advice":"...","days":[{{"day":"YYYY-MM-DD","blocks":[...]}},...]}}
"""
        if client is None:
            # Fallback: create a minimal 7-day cadence.
            for i in range(7):
                d = date.today() + timedelta(days=i)
                self._s().create_task(
                    plan_id=plan_id,
                    day=d,
                    start_time="20:00",
                    end_time="21:00",
                    title="Python全栈：最小学习单元",
                    description="验收：写下3条关键点 + 产出一段可运行代码（或提交commit）",
                )
            Clock.schedule_once(lambda *_: self._after_ai_breakdown(False), 0)
            return

        try:
            res = client.chat(system=SUPERVISOR_SYSTEM, user=prompt, timeout_s=60)
            data = safe_json_extract(res.text) or {}
            advice = str(data.get("advice", "") or "").strip()
            if advice:
                self._s().set_setting(f"plan_advice:{plan_id}", advice)
            for day_obj in data.get("days", []):
                d = date.fromisoformat(day_obj["day"])
                for b in day_obj.get("blocks", []):
                    self._s().create_task(
                        plan_id=plan_id,
                        day=d,
                        start_time=str(b.get("start_time", "20:00")),
                        end_time=str(b.get("end_time", "21:00")),
                        title=str(b.get("title", "")).strip() or "任务块",
                        description=str(b.get("description", "")).strip() or "验收：请提供可验证证据",
                    )
            Clock.schedule_once(lambda *_: self._after_ai_breakdown(True, advice), 0)
        except Exception:
            Clock.schedule_once(lambda *_: self._after_ai_breakdown(False, ""), 0)

    def _after_ai_breakdown(self, ok: bool, advice: str = ""):
        self.refresh_all()
        self.toast("AI拆解完成" if ok else "AI拆解失败：已用默认7天模板")
        if advice:
            dialog = MDDialog(
                title="督学师：计划合理化建议",
                text=advice,
                buttons=[MDFlatButton(text="知道了", on_release=lambda *_: dialog.dismiss())],
            )
            self._dialogs.append(dialog)
            dialog.open()

    def open_task(self, task_id: int):
        t = self._s().get_task(task_id)
        if not t:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(12), padding=(0, dp(8), 0, 0))
        content.add_widget(MDTextField(mode="rectangle", hint_text="标题", text=t.title))
        content.add_widget(MDTextField(mode="rectangle", hint_text="说明", text=t.description, multiline=True))

        dialog = MDDialog(
            title=f"{t.day} {t.start_time}-{t.end_time}",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="关闭", on_release=lambda *_: dialog.dismiss()),
                MDFillRoundFlatButton(text="去打卡", on_release=lambda *_: (dialog.dismiss(), self.open_checkin(task_id))),
            ],
        )
        self._dialogs.append(dialog)
        dialog.open()

    def open_plan(self, plan_id: int):
        plan = self._s().get_plan(plan_id)
        if not plan:
            return
        tasks = self._s().list_tasks_for_plan(plan_id)
        advice = self._s().get_setting(f"plan_advice:{plan_id}", "").strip()
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=(0, dp(8), 0, 0))
        content.add_widget(
            ThreeLineListItem(
                text=str(plan["title"]),
                secondary_text=str(plan["domain"]),
                tertiary_text=str(plan["long_goal"])[:120],
            )
        )
        if advice:
            content.add_widget(TwoLineListItem(text="督学建议", secondary_text=advice[:180]))
        # show only next 10
        for t in tasks[:10]:
            content.add_widget(
                TwoLineListItem(
                    text=f"{t.day} {t.start_time}-{t.end_time} {t.title}",
                    secondary_text=t.status,
                    on_release=lambda _w, tid=t.id: self.open_task(tid),
                )
            )
        dialog = MDDialog(title="计划概览（最近10条任务）", type="custom", content_cls=content, buttons=[MDFlatButton(text="关闭", on_release=lambda *_: dialog.dismiss())])
        self._dialogs.append(dialog)
        dialog.open()

    def open_checkin(self, task_id: int):
        t = self._s().get_task(task_id)
        if not t:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(12), padding=(0, dp(8), 0, 0))
        tf_report = MDTextField(mode="rectangle", hint_text="汇报：你做了什么？证据是什么？遇到什么阻碍？", multiline=True)
        tf_score = MDTextField(mode="rectangle", hint_text="自评（0-10）", input_filter="int", text="7")
        content.add_widget(tf_report)
        content.add_widget(tf_score)

        dialog = MDDialog(
            title=f"打卡：{t.title}",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="取消", on_release=lambda *_: dialog.dismiss()),
                MDFillRoundFlatButton(
                    text="提交",
                    on_release=lambda *_: self._submit_checkin(dialog, task_id, tf_report.text, tf_score.text),
                ),
            ],
        )
        self._dialogs.append(dialog)
        dialog.open()

    def _submit_checkin(self, dialog, task_id: int, report: str, score: str):
        report = (report or "").strip()
        if not report:
            self.toast("别糊弄：至少写清楚你做了什么+证据")
            return
        s = int((score or "0").strip() or "0")
        dialog.dismiss()
        self.toast("正在生成督学反馈…")
        threading.Thread(target=self._ai_feedback_and_save, args=(task_id, report, s), daemon=True).start()

    def _ai_feedback_and_save(self, task_id: int, report: str, self_score: int):
        t = self._s().get_task(task_id)
        if not t:
            return
        base_url = self._s().get_setting("ai_base_url", "")
        api_key = self._s().get_setting("ai_api_key", "")
        model = self._s().get_setting("ai_model", "")
        client = build_client(base_url, api_key, model)
        sus = suspicion_score(report)

        user = f"""
任务：{t.title}
任务说明/验收：{t.description}
学习者汇报：{report}
请输出：
1) 反馈与鼓励（真诚、具体）
2) 质疑与验收：要我补充1-3个证据/细节
3) 若进度不足：给出弥补方案（拆成最小动作）
字数控制在250字以内。
"""
        feedback = ""
        if client is None:
            feedback = "我看到了你在推进，但别用模糊词糊弄自己。请补充：1) 你产出的代码/笔记要点；2) 你卡住的点；3) 下一步最小动作是什么。今晚补救：再做20分钟，把“可运行最小例子”跑通。"
        else:
            try:
                feedback = client.chat(system=SUPERVISOR_SYSTEM, user=user, timeout_s=45).text
            except Exception:
                feedback = "AI反馈失败：请补充可验证证据（commit/截图/可复述要点），并把下一步拆成20分钟最小动作继续推进。"

        self._s().create_checkin(
            task_id=task_id,
            report_text=report,
            self_score=self_score,
            ai_feedback=feedback,
            suspicion_score=sus,
        )
        Clock.schedule_once(lambda *_: self._after_checkin_saved(feedback), 0)

    def _after_checkin_saved(self, feedback: str):
        self.refresh_all()
        self.toast("已记录打卡")
        dialog = MDDialog(
            title="督学反馈",
            text=feedback,
            buttons=[MDFlatButton(text="收下", on_release=lambda *_: dialog.dismiss())],
        )
        self._dialogs.append(dialog)
        dialog.open()

    def open_checkin_record(self, record_id: int):
        # Minimal: show from recent list only by re-querying.
        rows = self._s().list_checkins_recent(limit=50)
        row = next((r for r in rows if int(r["id"]) == int(record_id)), None)
        if not row:
            return
        dialog = MDDialog(
            title=f"记录：{row['task_day']} · {row['task_title']}",
            text=f"自评：{row['self_score']}/10\n质疑：{row['suspicion_score']}/100\n\n汇报：\n{row['report_text']}\n\n督学反馈：\n{row['ai_feedback']}",
            buttons=[MDFlatButton(text="关闭", on_release=lambda *_: dialog.dismiss())],
        )
        self._dialogs.append(dialog)
        dialog.open()

    # ---- settings ----
    def load_settings_into_ui(self):
        r = self.root.ids
        r.base_url.text = self._s().get_setting("ai_base_url", "")
        r.api_key.text = self._s().get_setting("ai_api_key", "")
        r.model.text = self._s().get_setting("ai_model", "gpt-4o-mini")
        r.reminder_grace_min.text = self._s().get_setting("reminder_grace_min", "5")
        r.reminder_resend_min.text = self._s().get_setting("reminder_resend_min", "15")
        r.reminder_max_sends.text = self._s().get_setting("reminder_max_sends", "3")

    def save_settings(self):
        r = self.root.ids
        self._s().set_setting("ai_base_url", r.base_url.text.strip())
        self._s().set_setting("ai_api_key", r.api_key.text.strip())
        self._s().set_setting("ai_model", r.model.text.strip() or "gpt-4o-mini")
        self._s().set_setting("reminder_grace_min", r.reminder_grace_min.text.strip() or "5")
        self._s().set_setting("reminder_resend_min", r.reminder_resend_min.text.strip() or "15")
        self._s().set_setting("reminder_max_sends", r.reminder_max_sends.text.strip() or "3")
        self.toast("已保存")

    def _s(self) -> Storage:
        if self.storage is None:
            raise RuntimeError("Storage not initialized yet")
        return self.storage

    def export_data(self):
        data = self._s().export_all()
        out_dir = Path(self.user_data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"ai_supervisor_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.toast(f"已导出：{path}")

    # ---- misc ----
    def toast(self, text: str):
        if Snackbar is None:
            print(text)
            return
        try:
            Snackbar(text=text).open()
        except Exception:
            print(text)


if __name__ == "__main__":
    AiSupervisorApp().run()
