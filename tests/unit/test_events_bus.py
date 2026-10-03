# tests/unit/test_events_bus.py
from core.events.bus import EventBus
from core.events.events import EventType


def test_subscribe_and_publish_order():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append("a"))
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append("b"))
    bus.publish(EventType.USER_MESSAGE, payload={"text": "hi"})
    assert seen == ["a", "b"]


def test_unrelated_events_do_not_fire():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append("msg"))
    bus.publish(EventType.AI_RESPONSE_STARTED)
    assert seen == []


def test_handler_exception_does_not_stop_others():
    bus = EventBus()
    seen: list[str] = []

    def boom(_e):
        raise RuntimeError("nope")

    bus.subscribe(EventType.USER_MESSAGE, boom)
    bus.subscribe(EventType.USER_MESSAGE, lambda e: seen.append("ok"))
    bus.publish(EventType.USER_MESSAGE)
    assert seen == ["ok"]


def test_unsubscribe():
    bus = EventBus()
    seen: list[int] = []

    def handler(_e):
        seen.append(1)

    bus.subscribe(EventType.USER_MESSAGE, handler)
    bus.publish(EventType.USER_MESSAGE)
    bus.unsubscribe(EventType.USER_MESSAGE, handler)
    bus.publish(EventType.USER_MESSAGE)
    assert seen == [1]


def test_publishing_inside_handler_is_allowed():
    bus = EventBus()
    seen: list[str] = []

    def outer(_e):
        bus.publish(EventType.AI_RESPONSE_STARTED, payload={"x": 1})

    def inner(_e):
        seen.append("inner")

    bus.subscribe(EventType.USER_MESSAGE, outer)
    bus.subscribe(EventType.AI_RESPONSE_STARTED, inner)
    bus.publish(EventType.USER_MESSAGE)
    assert seen == ["inner"]