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
