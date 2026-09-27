"""GPSSession._walk_route() 的行為測試：續走、改速度、循環走法、時間間隔。

用假的時鐘與假的 sim 取代真正的等待與 iPhone 連線：GPSSession 只用到 QtCore 的
signal，不需要 Qt 事件迴圈；時間透過 _now()／_sleep_until() 這兩個掛勾注入，
一秒一步的路線不必真的跑好幾秒。
"""

import asyncio

import pytest

from gps_qt.geo import haversine
from gps_qt.session import GPSSession

# 約 100 公尺的南北向直線，10 公尺/秒時切成 10 步（11 個點）
START = (24.0, 120.0)
END = (24.0009, 120.0)
ROUTE = [[START[0], START[1], "起點"], [END[0], END[1], "終點"]]
SPEED_MS = 10.0


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    async def sleep_until(self, deadline):
        self.t = max(self.t, deadline)
        await asyncio.sleep(0)


class FakeSim:
    """記錄每次 set() 的時間與座標；latency 模擬 RemoteXPC 往返的耗時。"""

    def __init__(self, clock, latency=0.0, on_set=None):
        self.clock = clock
        self.latency = latency
        self.on_set = on_set
        self.calls = []

    async def set(self, lat, lon):
        self.calls.append((self.clock.t, lat, lon))
        self.clock.t += self.latency
        if self.on_set:
            self.on_set(len(self.calls))

    @property
    def positions(self):
        return [(lat, lon) for _t, lat, lon in self.calls]


class Harness:
    def __init__(self, route=ROUTE, speed_ms=SPEED_MS, loop=False, style="bounce"):
        self.state = {"speed": speed_ms, "loop": loop, "style": style}
        self.clock = FakeClock()
        self.session = GPSSession(
            route_provider=lambda: route,
            speed_provider=lambda: self.state["speed"],
            pin_provider=lambda: (0.0, 0.0),
            mode_provider=lambda: "route",
            loop_provider=lambda: self.state["loop"],
            loop_style_provider=lambda: self.state["style"],
        )
        self.session._now = self.clock.now
        self.session._sleep_until = self.clock.sleep_until
        self.finished = []
        self.direction_changes = []
        self.session.route_finished.connect(self.finished.append)
        self.session.direction_changed.connect(lambda: self.direction_changes.append(1))

    def walk(self, direction, sim):
        self.session.pending_action = "forward" if direction == 1 else "reverse"
        asyncio.run(self.session._walk_route(sim, direction))


def _step_lengths(positions):
    return [haversine(a[0], a[1], b[0], b[1]) for a, b in zip(positions, positions[1:])]


def _stop_after(harness, count):
    def on_set(n):
        if n >= count:
            harness.session.pending_action = "pause"
    return on_set


def test_forward_walk_goes_from_start_to_end_and_holds():
    # Arrange
    harness = Harness()
    sim = FakeSim(harness.clock)

    # Act
    harness.walk(1, sim)

    # Assert
    assert sim.positions[0] == pytest.approx(START)
    assert sim.positions[-1] == pytest.approx(END)
    assert len(sim.positions) == 11
    assert harness.session.pending_action == "pause"
    assert harness.finished == ["已抵達終點，保持於目前座標"]


def test_steps_stay_one_second_apart_despite_set_latency():
    """每步間隔要扣掉 sim.set() 的耗時，否則長路線跑下來會越來越慢。"""
    # Arrange：每次注入要花 0.3 秒
    harness = Harness()
    sim = FakeSim(harness.clock, latency=0.3)

    # Act
    harness.walk(1, sim)

    # Assert：注入時間仍是 0、1、2、…秒
    times = [t for t, _lat, _lon in sim.calls]
    assert times == pytest.approx([float(i) for i in range(len(times))])


def test_a_stalled_set_does_not_cause_a_burst_of_catch_up_steps():
    # Arrange：第 3 次注入卡了 5 秒
    harness = Harness()
    sim = FakeSim(harness.clock)

    def on_set(n):
        if n == 3:
            harness.clock.t += 5.0
    sim.on_set = on_set

    # Act
    harness.walk(1, sim)

    # Assert：卡住之後照常一秒一步，不會連續補送好幾步
    times = [t for t, _lat, _lon in sim.calls]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= 0.0
    assert all(gap == pytest.approx(1.0) for gap in gaps[3:])


def test_stop_then_start_resumes_where_it_stopped():
    # Arrange
    harness = Harness()
    first = FakeSim(harness.clock, on_set=_stop_after(harness, 4))
    harness.walk(1, first)
    stopped_at = first.positions[-1]

    # Act
    second = FakeSim(harness.clock)
    harness.walk(1, second)

    # Assert：從停下來的位置繼續，而不是回到起點或瞬移到終點
    assert harness.session.travelled_m > 0
    assert second.positions[0] == pytest.approx(stopped_at)
    assert second.positions[-1] == pytest.approx(END)


def test_speed_change_while_moving_takes_effect_on_the_next_step():
    # Arrange：走完第 3 步時改成 20 公尺/秒
    harness = Harness()

    def on_set(n):
        if n == 3:
            harness.state["speed"] = 20.0
    sim = FakeSim(harness.clock, on_set=on_set)

    # Act
    harness.walk(1, sim)

    # Assert：前兩步約 10 公尺；改速度後不會在原地重送同一點，之後每步接近 20 公尺
    steps = _step_lengths(sim.positions)
    assert steps[:2] == pytest.approx([10.0, 10.0], rel=0.05)
    assert min(steps) > 1.0
    assert all(step == pytest.approx(20.0, rel=0.05) for step in steps[3:-1])
    assert sim.positions[-1] == pytest.approx(END)


def test_speed_change_while_walking_back_keeps_heading_to_the_start():
    # Arrange：先走到終點，再往回走；往回走第 3 步時改成 5 公尺/秒
    harness = Harness()
    harness.walk(1, FakeSim(harness.clock))

    def on_set(n):
        if n == 3:
            harness.state["speed"] = 5.0
    sim = FakeSim(harness.clock, on_set=on_set)

    # Act
    harness.walk(-1, sim)

    # Assert：一路往南、不重送同一點，改速度後每步接近 5 公尺
    steps = _step_lengths(sim.positions)
    assert all(b[0] < a[0] for a, b in zip(sim.positions, sim.positions[1:]))
    assert all(step == pytest.approx(5.0, rel=0.05) for step in steps[3:-1])
    assert sim.positions[-1] == pytest.approx(START)


def test_bounce_loop_turns_around_at_the_end():
    # Arrange：來回模式，折返後再走 3 步就停
    harness = Harness(loop=True, style="bounce")

    def on_set(n):
        if n >= 14:
            harness.session.pending_action = "pause"
    sim = FakeSim(harness.clock, on_set=on_set)

    # Act
    harness.walk(1, sim)

    # Assert：抵達終點後改為往起點走，終點不會重送兩次
    assert sim.positions[10] == pytest.approx(END)
    assert sim.positions[11] != pytest.approx(END)
    assert sim.positions[11][0] < sim.positions[10][0]
    assert harness.session.direction == "reverse"
    assert harness.direction_changes == [1]
    assert harness.finished == []


def test_circuit_loop_jumps_back_to_the_start_without_changing_direction():
    # Arrange：迴圈模式，回到起點後再走 1 步就停
    harness = Harness(loop=True, style="circuit")
    sim = FakeSim(harness.clock, on_set=_stop_after(harness, 13))

    # Act
    harness.walk(1, sim)

    # Assert
    assert sim.positions[10] == pytest.approx(END)
    assert sim.positions[11] == pytest.approx(START)
    assert sim.positions[12][0] > START[0]
    assert harness.session.direction == "forward"
    assert harness.direction_changes == []


def test_reverse_walk_returns_to_the_start():
    # Arrange：先往前走到一半再停
    harness = Harness()
    harness.walk(1, FakeSim(harness.clock, on_set=_stop_after(harness, 6)))

    # Act
    sim = FakeSim(harness.clock)
    harness.walk(-1, sim)

    # Assert
    assert sim.positions[-1] == pytest.approx(START)
    assert all(b[0] <= a[0] for a, b in zip(sim.positions, sim.positions[1:]))
    assert harness.finished[-1] == "已返回起點，保持於目前座標"


def test_session_end_resets_pending_action_even_on_early_return(monkeypatch):
    """找不到裝置這類提早 return 也要把 pending_action 歸零，UI 按鈕才不會卡在停用。"""
    import pymobiledevice3.tunneld.api as tunneld_api

    async def no_devices():
        return []
    monkeypatch.setattr(tunneld_api, "get_tunneld_devices", no_devices)
    harness = Harness()
    ended = []
    harness.session.session_ended.connect(
        lambda: ended.append((harness.session.pending_action, harness.session.session_active))
    )
    harness.session.pending_action = "forward"

    # Act
    asyncio.run(harness.session._session_main())

    # Assert：session_ended 發出的當下狀態就已經歸零
    assert ended == [("pause", False)]


class _FakeContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


def _patch_device(monkeypatch, sim):
    """讓 _session_main() 連到假的裝置：找得到一台，DVT 連線直接給 sim。"""
    import pymobiledevice3.services.dvt.instruments.dvt_provider as dvt_module
    import pymobiledevice3.services.dvt.instruments.location_simulation as loc_module
    import pymobiledevice3.tunneld.api as tunneld_api

    class FakeRsd:
        udid = "00008110-TEST"

    async def one_device():
        return [FakeRsd()]
    monkeypatch.setattr(tunneld_api, "get_tunneld_devices", one_device)
    monkeypatch.setattr(dvt_module, "DvtProvider", lambda rsd: _FakeContext("dvt"))
    monkeypatch.setattr(loc_module, "LocationSimulation", lambda dvt: _FakeContext(sim))


def test_session_reports_an_error_raised_while_walking(monkeypatch):
    """移動中拔掉 USB 這類例外要寫進執行日誌，不能只丟進沒人看的 stderr。"""
    # Arrange：第 3 次注入時連線中斷
    harness = Harness()

    def on_set(n):
        if n == 3:
            raise ConnectionResetError("裝置已中斷連線")
    sim = FakeSim(harness.clock, on_set=on_set)
    _patch_device(monkeypatch, sim)
    logs, ended = [], []
    harness.session.log.connect(logs.append)
    harness.session.session_ended.connect(lambda: ended.append(harness.session.pending_action))
    harness.session.pending_action = "forward"

    # Act：例外不能從 _session_main() 漏出去
    asyncio.run(harness.session._session_main())

    # Assert
    assert any("模擬中斷" in line and "裝置已中斷連線" in line for line in logs)
    assert ended == ["pause"]
    assert harness.session.session_active is False
    assert harness.session.travelled_m > 0  # 已走的距離保留，重新連線後可以接著走


def test_route_emptied_while_looping_stops_with_a_message():
    """移動中路線被清空時要停下來並說明，不能在下一圈丟 IndexError。"""
    # Arrange：來回模式，走到第 3 步時路線被清空
    route = [list(row) for row in ROUTE]
    harness = Harness(route=route, loop=True, style="bounce")
    logs = []
    harness.session.log.connect(logs.append)

    def on_set(n):
        if n == 3:
            route.clear()
    sim = FakeSim(harness.clock, on_set=on_set)

    # Act
    harness.walk(1, sim)

    # Assert
    assert harness.session.pending_action == "pause"
    assert any("少於 2 個點" in line for line in logs)
