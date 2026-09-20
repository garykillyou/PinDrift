"""定位模擬的連線狀態機：動作切換全部透過 pending_action 這個共享狀態。

用 qasync 讓 asyncio 事件迴圈直接跑在 Qt 事件迴圈的同一條 thread 上，
不需要背景 thread，也不需要跨執行緒 marshalling；協程直接用 Qt signal
把狀態送出，UI 層 connect 對應的 slot 即可，不需要自己判斷「目前是不是
在背景執行緒」。

維持一條長連線：開始/返回/停止都只是換動作，不會中斷連線；只有拿到
"disconnect" 動作（按下「恢復真實定位」）才會真正斷線，斷線當下裝置會
自動恢復真實 GPS。
"""

import asyncio

from PySide6.QtCore import QObject, Signal

from .geo import interpolate_points


class GPSSession(QObject):
    log = Signal(str)
    progress_value = Signal(float)   # 0~1
    progress_label = Signal(str)
    paused = Signal()                # 暫停/返回中斷後（對應原本 _on_paused）
    session_ended = Signal()         # 連線真正結束（對應原本 _on_session_ended）
    direction_changed = Signal()     # 循環模式在端點自動折返，方向被動改變
    position_changed = Signal(float, float)  # 每次實際注入座標（地圖即時位置/軌跡用）
    route_finished = Signal(str)     # 非循環模式抵達端點，UI 用來彈出不搶焦點的提示

    def __init__(self, route_provider, speed_provider, pin_provider, mode_provider, loop_provider):
        """
        route_provider: () -> list[[lat, lon, name], ...]，目前的路線點
        speed_provider: () -> float，移動速度（公尺/秒）
        pin_provider:   () -> (lat, lon)，固定定位模式的座標
        mode_provider:  () -> "pin" | "route"
        loop_provider:  () -> bool，路線模式的循環（來回往復）開關
        """
        super().__init__()
        self._route_provider = route_provider
        self._speed_provider = speed_provider
        self._pin_provider = pin_provider
        self._mode_provider = mode_provider
        self._loop_provider = loop_provider

        self.session_active = False
        self.pending_action = "pause"  # "forward" | "reverse" | "pause" | "disconnect"
        self.direction = "forward"  # "forward" | "reverse"，下次「開始移動」要走的方向
        self.point_idx = 0
        self._task = None

    # ── 外部呼叫的動作：對應原本四顆按鈕 ────────────────────
    def start_forward(self):
        self.pending_action = "forward"
        self._ensure_task()

    def start(self):
        """路線模式的「開始移動」：依目前 self.direction 開始移動。"""
        self.pending_action = self.direction
        self._ensure_task()

    def stop(self):
        self.pending_action = "pause"

    def toggle_direction(self):
        """單純切換下次「開始移動」要走的方向，不會啟動移動——呼叫端要自行
        確保目前不在移動中（UI 在移動中會停用切換方向按鈕）。"""
        self.direction = "forward" if self.direction == "reverse" else "reverse"

    def restore_real_location(self):
        self.pending_action = "disconnect"

    def _ensure_task(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.ensure_future(self._session_main())

    # ── 核心狀態機 ────────────────────
    async def _session_main(self):
        try:
            from pymobiledevice3.tunneld.api import get_tunneld_devices
            from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
            from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        except ImportError as e:
            self.log.emit("匯入失敗：" + str(e))
            return

        self.log.emit("搜尋裝置中...")
        try:
            rsds = await get_tunneld_devices()
        except Exception as e:
            self.log.emit("tunneld 連線失敗：" + str(e))
            self.log.emit("   請先以系統管理員執行：python -m pymobiledevice3 remote tunneld")
            return

        if not rsds:
            self.log.emit("找不到裝置，請確認 USB 已連接")
            return

        rsd = rsds[0]
        self.log.emit("找到裝置：" + str(rsd.udid))

        try:
            async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim:
                self.session_active = True
                while True:
                    action = self.pending_action
                    if action == "disconnect":
                        break
                    elif action == "forward" and self._mode_provider() == "pin":
                        await self._walk_pin(sim)
                    elif action == "forward":
                        await self._walk_route(sim, 1)
                    elif action == "reverse":
                        await self._walk_route(sim, -1)
                    else:
                        await asyncio.sleep(0.2)
                        continue
                    if self.pending_action == "pause":
                        self.paused.emit()

                await sim.clear()
                self.point_idx = 0
                self.log.emit("已恢復真實定位")
                self.progress_value.emit(0.0)
                self.progress_label.emit("已恢復真實定位")
        finally:
            self.session_active = False
            self.session_ended.emit()

    async def _walk_pin(self, sim):
        lat, lon = self._pin_provider()
        self.log.emit(f"固定位置：{lat:.6f}, {lon:.6f}")
        await sim.set(lat, lon)
        self.position_changed.emit(lat, lon)
        self.progress_value.emit(1.0)
        self.progress_label.emit(f"固定中  {lat:.6f}, {lon:.6f}")
        self.log.emit("定位已固定！按「停止」可保持在目前座標")
        self.pending_action = "pause"

    async def _walk_route(self, sim, direction):
        """direction=1 往路線終點走，direction=-1 往路線起點走回去。
        走到一半若 pending_action 被改成別的值（暫停/切換方向/斷線），會立刻
        中斷並把目前位置留在 self.point_idx，交回外層迴圈處理。不論這趟是由
        「開始」還是「返回」觸發，每次走到終點/起點時都會即時讀取循環開關，
        決定要不要折返繼續走，如此來回往復，直到 pending_action 被改成別的
        值——因此使用者可以在路上隨時勾選/取消勾選，下次抵達端點就會生效。"""
        action_name = "forward" if direction == 1 else "reverse"
        if direction == -1:
            self.log.emit("返回中，沿路線往回走...")

        idx = self.point_idx
        while True:
            suffix = "" if direction == 1 else "（返回中）"
            speed = self._speed_provider()
            route = self._route_provider()
            points = interpolate_points([(r[0], r[1], "") for r in route], speed, 1.0)
            total = len(points)
            idx = max(0, min(idx, total - 1))
            idx_range = range(idx, total) if direction == 1 else range(idx, -1, -1)

            interrupted = False
            for i in idx_range:
                if self.pending_action != action_name:
                    interrupted = True
                    break
                lat, lon = points[i]
                await sim.set(lat, lon)
                self.position_changed.emit(lat, lon)
                idx = i
                self.point_idx = i
                frac = (i + 1) / total if direction == 1 else i / total
                self.progress_value.emit(frac)
                self.progress_label.emit(f"{frac*100:.1f}%  {lat:.6f}, {lon:.6f}{suffix}")
                await asyncio.sleep(1.0)

            if interrupted:
                return

            # 走到端點才即時讀取循環開關，而不是在函式一開始就快取，這樣
            # 使用者中途勾選/取消勾選才會在下一次抵達端點時生效。
            if self.pending_action == action_name and self._loop_provider():
                if direction == 1:
                    self.log.emit("循環模式：已抵達終點，沿路線折返")
                else:
                    self.log.emit("循環模式：已回到起點，再次出發")
                direction = -direction
                # 折返後，方向被動改變，pending_action/action_name/direction
                # 都要跟著更新，「往起點」/「往終點」按鈕文字才不會停留在舊方向。
                action_name = "forward" if direction == 1 else "reverse"
                self.pending_action = action_name
                self.direction = action_name
                self.direction_changed.emit()
                idx = max(0, min(idx + direction, total - 1))
                self.point_idx = idx
                continue

            if direction == 1:
                message = "已抵達終點，保持於目前座標"
            else:
                message = "已返回起點，保持於目前座標"
            self.log.emit(message)
            self.progress_label.emit("已完成")
            self.route_finished.emit(message)
            self.pending_action = "pause"
            return
