"""定位模擬的連線狀態機：動作切換全部透過 pending_action 這個共享狀態。

用 qasync 讓 asyncio 事件迴圈直接跑在 Qt 事件迴圈的同一條 thread 上，
不需要背景 thread，也不需要跨執行緒 marshalling；協程直接用 Qt signal
把狀態送出，UI 層 connect 對應的 slot 即可，不需要自己判斷「目前是不是
在背景執行緒」。

維持一條長連線：開始移動/切換方向/停止都只是換動作，不會中斷連線；只有拿到
"disconnect" 動作（按下「恢復真實定位」）才會真正斷線，斷線當下裝置會
自動恢復真實 GPS。
"""

import asyncio
import logging

from PySide6.QtCore import QObject, Signal

from . import tunneld
from .geo import RouteSampler

logger = logging.getLogger(__name__)

STEP_INTERVAL_S = 1.0  # 每隔幾秒注入一次座標
MIN_ROUTE_POINTS = 2  # 路線至少要兩個點才能內插
# 兩個弧長位置相差不到這個值就當成同一個位置（浮點誤差的容許範圍）。
_SAME_POSITION_M = 0.01

# _walk_points() 的結果：被外部動作打斷／移動中改了速度／走到端點。
_INTERRUPTED, _SPEED_CHANGED, _ARRIVED = range(3)


class GPSSession(QObject):
    log = Signal(str)
    progress_value = Signal(float)   # 0~1
    progress_label = Signal(str)
    paused = Signal()                # 暫停/返回中斷後（對應原本 _on_paused）
    session_ended = Signal()         # 連線真正結束（對應原本 _on_session_ended）
    direction_changed = Signal()     # 循環模式在端點自動折返，方向被動改變
    position_changed = Signal(float, float)  # 每次實際注入座標（地圖即時位置/軌跡用）
    route_finished = Signal(str)     # 非循環模式抵達端點，UI 用來彈出不搶焦點的提示

    def __init__(self, route_provider, speed_provider, pin_provider, mode_provider, loop_provider,
                 loop_style_provider):
        """
        route_provider: () -> list[[lat, lon, name], ...]，目前的路線點
        speed_provider: () -> float，移動速度（公尺/秒）
        pin_provider:   () -> (lat, lon)，固定定位模式的座標
        mode_provider:  () -> "pin" | "route"
        loop_provider:  () -> bool，路線模式的循環開關
        loop_style_provider: () -> "bounce" | "circuit"，循環的走法（來回折返／迴圈瞬移回起點）
        """
        super().__init__()
        self._route_provider = route_provider
        self._speed_provider = speed_provider
        self._pin_provider = pin_provider
        self._mode_provider = mode_provider
        self._loop_provider = loop_provider
        self._loop_style_provider = loop_style_provider

        self.session_active = False
        # pending_action 一變就喚醒正在等待的迴圈（見 _wait_for_action_change()）。
        # Event 綁定建立時所在的事件迴圈，所以延到第一次等待時才在當下的迴圈建立。
        self._action_event = None
        self._action_event_loop = None
        self.pending_action = "pause"  # "forward" | "reverse" | "pause" | "disconnect"
        self.direction = "forward"  # "forward" | "reverse"，下次「開始移動」要走的方向
        # 進度記「已走到路線的第幾公尺」而不是「第幾個內插點」：內插點的數量
        # 由速度決定，停止時改速度（或編輯路線）會讓舊索引對到完全不同的位置，
        # 索引過大時還會被夾到最後一點，再按「開始移動」人就直接瞬移到終點。
        self.travelled_m = 0.0
        # 最後一次實際注入的座標；連線結束時歸零（UI 用來判斷座標有沒有變）。
        self.last_position = None
        self._task = None

    @property
    def pending_action(self):
        return self._pending_action

    @pending_action.setter
    def pending_action(self, action):
        # 不論是按鈕、循環折返還是測試改的，一律立刻喚醒等待中的迴圈：
        # 不這樣做的話「停止」要等到下一步的刻度（最多一秒）才生效，
        # 待機中按「開始移動」也要等下一輪輪詢。
        self._pending_action = action
        if self._action_event is not None:
            self._action_event.set()

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

    def reset_direction(self):
        """把下次「開始移動」的方向設回往終點走（載入路線最愛時用）。
        與 toggle_direction() 一樣不會啟動移動，呼叫端要確保目前不在移動中。"""
        self.direction = "forward"

    def restore_real_location(self):
        self.pending_action = "disconnect"

    def reset_progress(self):
        """整條路線被換掉時歸零進度——舊的已走距離對新路線沒有意義。"""
        self.travelled_m = 0.0

    def _ensure_task(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.ensure_future(self._session_main())

    # ── 核心狀態機 ────────────────────
    async def _session_main(self):
        # 這個 try/finally 包住「整個」函式主體（含所有提早 return 的分支），
        # 不能只包住 async with 那一段：搜尋裝置失敗／找不到裝置／匯入失敗這些
        # 提早 return 也必須確實重設 session_active 並 emit session_ended，
        # 否則 UI 會卡在按下「開始移動」當下的忙碌狀態（修過的 bug：卡住之後
        # 連「停止」都救不回來，因為那時 _session_main() 早已結束，沒有任何
        # task 在讀 pending_action，而 _stop() 本身也不會主動同步按鈕狀態）。
        try:
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
                self.log.emit("   " + tunneld.manual_start_hint())
                return

            if not rsds:
                self.log.emit("找不到裝置，請確認 USB 已連接")
                return

            rsd = rsds[0]
            self.log.emit("找到裝置：" + str(rsd.udid))

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
                        await self._wait_for_action_change(action)
                        continue
                    if self.pending_action == "pause":
                        self.paused.emit()

                await sim.clear()
                self.travelled_m = 0.0
                self.log.emit("已恢復真實定位")
                self.progress_value.emit(0.0)
                self.progress_label.emit("已恢復真實定位")
        except Exception as exc:
            # 移動中拔掉 USB、iPhone 鎖定、關掉開發者模式，或這裡的程式本身出錯，
            # 都會從 sim.set() 等處丟出例外。沒接住的話只會變成 asyncio 印在 stderr 的
            # 「Task exception was never retrieved」——pythonw／打包版根本沒有 stderr，
            # 使用者只看到按鈕突然恢復，不知道發生什麼事（修過的 bug）。
            # travelled_m 刻意不歸零：重新連線後按「開始移動」可以從原地接著走。
            logger.exception("模擬中斷")
            self.log.emit(f"模擬中斷：{type(exc).__name__}: {exc}")
            self.log.emit("   請確認 USB 連線、iPhone 已解鎖且開發者模式仍開啟，再按「開始移動」")
            self.progress_label.emit("模擬中斷")
        finally:
            # 連線已結束（正常斷線、提早 return 或中途出錯），動作一併歸零再通知：
            # 殘留的 "disconnect"/"forward" 會讓 UI 以為還在忙，按鈕全部卡在停用。
            # 狀態由這裡自己收尾，不交給收到 signal 的 UI 從外面改。
            self.session_active = False
            self.pending_action = "pause"
            self.last_position = None
            self.session_ended.emit()

    async def _walk_pin(self, sim):
        lat, lon = self._pin_provider()
        self.log.emit(f"固定位置：{lat:.6f}, {lon:.6f}")
        await sim.set(lat, lon)
        self.last_position = (lat, lon)
        self.position_changed.emit(lat, lon)
        self.progress_value.emit(1.0)
        self.progress_label.emit(f"固定中  {lat:.6f}, {lon:.6f}")
        self.log.emit("定位已固定！按「停止」可保持在目前座標")
        self.pending_action = "pause"

    async def _walk_route(self, sim, direction):
        """direction=1 往路線終點走，direction=-1 往路線起點走回去。
        走到一半若 pending_action 被改成別的值（暫停/切換方向/斷線），會立刻
        中斷並把已走距離留在 self.travelled_m，交回外層迴圈處理。不論這趟是往終點
        還是往起點走，每次走到端點時都會即時讀取循環開關與走法，決定要不要繼續
        走，直到 pending_action 被改成別的值——使用者可以在路上隨時勾選或切換，
        下次抵達端點就會生效。循環有兩種走法：
        「來回」（bounce）在端點折返、方向反轉；「迴圈」（circuit）方向不變，
        瞬移回路線另一端繼續走，模擬繞圈。

        移動中改速度會在下一步就生效：_walk_points() 發現速度變了就提早回來，
        這裡依 travelled_m 用新速度重新內插，從原地接著走。"""
        if direction == -1:
            self.log.emit("返回中，沿路線往回走...")

        skip_current = False
        while True:
            route = self._route_provider()
            if len(route) < MIN_ROUTE_POINTS:
                # 移動中路線表格已被鎖住，正常走不到這裡；仍要防：少於兩點無法內插，
                # 循環模式下一圈會直接丟 IndexError 把整個模擬弄掉（修過的 bug）。
                self.log.emit(f"路線少於 {MIN_ROUTE_POINTS} 個點，已停止移動")
                self.progress_label.emit("已停止")
                self.pending_action = "pause"
                return
            speed = self._speed_provider()
            # 每一輪都重建：速度或路線在停止期間被改過的話，步數與步長都會不同，
            # 必須用已走距離重新換算成這一輪的索引。RouteSampler 只處理原本的
            # 路線點、需要哪一步才算那一步，不會一次展開幾十萬個內插點。
            sampler = RouteSampler(route, speed * STEP_INTERVAL_S)
            start = self._resume_index(sampler, direction, skip_current)
            outcome, idx = await self._walk_points(sim, sampler, start, direction, speed)
            if outcome == _INTERRUPTED:
                return
            skip_current = outcome == _SPEED_CHANGED
            if skip_current:
                continue
            direction = self._on_route_end(direction, sampler, idx)
            if direction is None:
                return

    def _resume_index(self, sampler, direction, skip_current):
        """把 travelled_m 換算成這一輪要從哪個索引開始走。

        skip_current 在「移動中途改速度」時為真：travelled_m 對應的位置剛剛才注入
        過，要從行進方向上的下一個點開始，否則會在原地多停一秒。索引可能因此超出
        範圍（剛好停在端點），此時 _walk_points() 一步都不走，直接當作抵達端點。
        """
        idx = sampler.index_at(self.travelled_m)
        if not skip_current:
            return idx
        position = sampler.distance_at(idx)
        if direction == 1 and position <= self.travelled_m + _SAME_POSITION_M:
            return idx + 1
        if direction == -1 and position >= self.travelled_m - _SAME_POSITION_M:
            return idx - 1
        return idx

    async def _walk_points(self, sim, sampler, start, direction, speed):
        """從 start 開始每 STEP_INTERVAL_S 秒注入一點，回傳 (結果, 最後停留的索引)。

        每一步的時間點是從這一輪開始時算好的固定刻度，會扣掉 sim.set() 本身的耗時；
        單純在 set() 之後 sleep 一秒的話，實際間隔是「一秒 + 往返時間」，長路線跑
        下來會越來越落後設定的速度。某一步卡得比一個間隔還久時就從當下重新起算，
        不連續補送落後的那幾步（那等於在地圖上瞬間跳一段）。

        等下一個刻度的期間 pending_action 一被改掉就會提早醒來，「停止」立即生效。
        """
        action_name = _action_for(direction)
        suffix = "" if direction == 1 else "（返回中）"
        last = sampler.last_index
        total = last + 1
        idx = min(max(start, 0), last)
        indices = range(start, total) if direction == 1 else range(start, -1, -1)
        next_tick = self._now()
        for i in indices:
            if self.pending_action != action_name:
                return _INTERRUPTED, idx
            if self._speed_provider() != speed:
                return _SPEED_CHANGED, idx
            lat, lon = sampler.point(i)
            await sim.set(lat, lon)
            self.last_position = (lat, lon)
            self.position_changed.emit(lat, lon)
            idx = i
            self.travelled_m = sampler.distance_at(i)
            frac = (i + 1) / total if direction == 1 else i / total
            self.progress_value.emit(frac)
            self.progress_label.emit(f"{frac*100:.1f}%  {lat:.6f}, {lon:.6f}{suffix}")
            next_tick = max(next_tick + STEP_INTERVAL_S, self._now())
            await self._sleep_until_or_action_change(next_tick, action_name)
        return _ARRIVED, idx

    def _on_route_end(self, direction, sampler, idx):
        """抵達端點：回傳下一輪要走的方向，不再繼續走時回傳 None。

        走到端點才即時讀取循環開關/走法，而不是在一開始就快取，這樣使用者
        中途勾選/切換才會在下一次抵達端點時生效。
        """
        action_name = _action_for(direction)
        if self.pending_action != action_name or not self._loop_provider():
            if direction == 1:
                message = "已抵達終點，保持於目前座標"
            else:
                message = "已返回起點，保持於目前座標"
            self.log.emit(message)
            self.progress_label.emit("已完成")
            self.route_finished.emit(message)
            self.pending_action = "pause"
            return None

        last = sampler.last_index
        if self._loop_style_provider() == "circuit":
            # 迴圈模式：方向不變，瞬移回路線另一端繼續走。
            if direction == 1:
                self.log.emit("迴圈模式：已抵達終點，返回起點繼續前進")
                self.travelled_m = sampler.distance_at(0)
            else:
                self.log.emit("迴圈模式：已回到起點，返回終點繼續前進")
                self.travelled_m = sampler.distance_at(last)
            return direction

        if direction == 1:
            self.log.emit("循環模式：已抵達終點，沿路線折返")
        else:
            self.log.emit("循環模式：已回到起點，再次出發")
        direction = -direction
        # 折返後，方向被動改變，pending_action 與 direction 都要跟著更新，
        # 「往起點」/「往終點」按鈕文字才不會停留在舊方向。
        self.pending_action = _action_for(direction)
        self.direction = self.pending_action
        self.direction_changed.emit()
        self.travelled_m = sampler.distance_at(max(0, min(idx + direction, last)))
        return direction

    # ── 等待 pending_action 改變 ────────────────────
    def _current_action_event(self):
        loop = asyncio.get_running_loop()
        if self._action_event is None or self._action_event_loop is not loop:
            self._action_event = asyncio.Event()
            self._action_event_loop = loop
        return self._action_event

    async def _wait_for_action_change(self, action):
        """一直等到 pending_action 不再是 action（待機時不必輪詢）。"""
        event = self._current_action_event()
        # clear 與檢查之間沒有 await，不會漏掉這之間發生的變動。
        while self.pending_action == action:
            event.clear()
            await event.wait()

    async def _sleep_until_or_action_change(self, deadline, action):
        """等到 deadline；pending_action 在這之前不再是 action 就提早醒來。

        時間本身仍交給 _sleep_until()（測試會換成假的時鐘），這裡只是讓它跟
        「動作被改掉」賽跑，誰先完成就回來，另一個取消掉。
        """
        if self.pending_action != action:
            return
        sleeper = asyncio.ensure_future(self._sleep_until(deadline))
        waker = asyncio.ensure_future(self._wait_for_action_change(action))
        done, pending = await asyncio.wait(
            {sleeper, waker}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()  # 讓 _sleep_until() 裡的例外照常往外丟

    # ── 時間掛勾（測試會換成假的時鐘，不必真的一秒一秒等） ────────────────────
    def _now(self):
        return asyncio.get_running_loop().time()

    async def _sleep_until(self, deadline):
        await asyncio.sleep(max(0.0, deadline - self._now()))


def _action_for(direction):
    return "forward" if direction == 1 else "reverse"
