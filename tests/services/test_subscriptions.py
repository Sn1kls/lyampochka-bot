import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.diff import data_hash
from poweron.core.domain.models import (
    Building,
    City,
    MessageKind,
    OutboxMessage,
    ScheduleVersion,
    Street,
    Subscription,
)
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")


@pytest.fixture
def subscriptions(repository: SqlRepository) -> Subscriptions:
    return Subscriptions(repository)


async def test_of_user_and_get_are_scoped_to_the_user(subscriptions: Subscriptions) -> None:
    alice = await subscriptions.register("telegram", "1", "telegram", "1")
    bob = await subscriptions.register("telegram", "2", "telegram", "2")
    home = await subscriptions.add(
        alice, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )
    await subscriptions.add(
        bob, "Робота", TERNOPIL, SADOVA, Building(2, "2", "1.2"), ["1.2"], ["1.2"], NOW
    )

    assert await subscriptions.of_user(alice) == [home]
    assert await subscriptions.get(alice, home.id) == home
    assert await subscriptions.get(bob, home.id) is None
    assert await subscriptions.get(alice, home.id + 100) is None


async def test_forget_removes_everything_of_the_user_only(
    repository: SqlRepository, subscriptions: Subscriptions
) -> None:
    alice = await subscriptions.register("telegram", "1", "telegram", "1")
    bob = await subscriptions.register("telegram", "2", "telegram", "2")
    await subscriptions.add(
        alice, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )
    bobs = await subscriptions.add(
        bob, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )
    slots = {"00:00": "0"}
    version = ScheduleVersion("4.1", NOW.date(), NOW, data_hash(slots), slots, NOW)
    await repository.save_version(
        version,
        [
            OutboxMessage(alice, MessageKind.SCHEDULE_UPDATED, {}, "alice"),
            OutboxMessage(bob, MessageKind.SCHEDULE_UPDATED, {}, "bob"),
        ],
    )

    await subscriptions.forget(alice)

    assert await subscriptions.of_user(alice) == []
    assert await repository.delivery_targets(alice) == []
    assert [item.message.dedupe_key for item in await repository.due_messages(NOW, 10, 5)] == [
        "bob"
    ]
    assert await subscriptions.of_user(bob) == [bobs]
    assert len(await repository.delivery_targets(bob)) == 1


async def test_register_does_not_rebind_a_target_of_another_user(
    repository: SqlRepository, subscriptions: Subscriptions
) -> None:
    alice = await subscriptions.register("telegram", "1", "telegram", "chat-1")
    mallory = await subscriptions.register("telegram", "2", "telegram", "chat-1")

    assert mallory != alice
    assert [target.address for target in await repository.delivery_targets(alice)] == ["chat-1"]
    assert await repository.delivery_targets(mallory) == []


async def test_register_reactivates_the_own_target(
    repository: SqlRepository, subscriptions: Subscriptions
) -> None:
    alice = await subscriptions.register("telegram", "1", "telegram", "chat-1")
    (target,) = await repository.delivery_targets(alice)
    await repository.deactivate_target(target.id)

    assert await subscriptions.register("telegram", "1", "telegram", "chat-1") == alice
    assert len(await repository.delivery_targets(alice)) == 1


async def test_find_user_is_read_only_and_does_not_register(subscriptions: Subscriptions) -> None:
    assert await subscriptions.find_user("telegram", "1") is None
    alice = await subscriptions.register("telegram", "1", "telegram", "1")
    assert await subscriptions.find_user("telegram", "1") == alice
    assert await subscriptions.find_user("telegram", "2") is None


async def test_subscription_keeps_all_queues_with_the_tracked_ones_first(
    subscriptions: Subscriptions,
) -> None:
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    building = Building(1, "96", "4.1")

    added = await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, building, ["2.2", "4.1"], ["4.1"], NOW
    )

    assert added.subqueues == ("4.1", "2.2")
    assert added.tracked_subqueues == ("4.1",)
    assert await subscriptions.get(user_id, added.id) == added


async def test_tracked_queues_must_be_a_non_empty_subset(subscriptions: Subscriptions) -> None:
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    building = Building(1, "96", "4.1")

    for tracked in ([], ["9.9"]):
        with pytest.raises(ValueError):
            await subscriptions.add(
                user_id, "Дім", TERNOPIL, SADOVA, building, ["4.1"], tracked, NOW
            )


def settings_of(subscription: Subscription) -> tuple[bool, int, int]:
    return (
        subscription.notify_on_update,
        subscription.remind_before_off_min,
        subscription.remind_before_on_min,
    )


async def test_update_settings_changes_only_the_given_fields(subscriptions: Subscriptions) -> None:
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    home = await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )
    assert settings_of(home) == (True, 30, 0)

    updated = await subscriptions.update_settings(user_id, home.id, remind_before_on_min=15)
    assert updated is not None
    assert settings_of(updated) == (True, 30, 15)

    muted = await subscriptions.update_settings(user_id, home.id, notify_on_update=False)
    assert muted is not None
    assert settings_of(muted) == (False, 30, 15)


async def test_update_settings_cannot_touch_another_users_subscription(
    subscriptions: Subscriptions,
) -> None:
    alice = await subscriptions.register("telegram", "1", "telegram", "1")
    bob = await subscriptions.register("telegram", "2", "telegram", "2")
    home = await subscriptions.add(
        alice, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )

    assert await subscriptions.update_settings(bob, home.id, remind_before_off_min=60) is None
    assert await subscriptions.get(alice, home.id) == home


async def test_update_settings_rejects_unsupported_minutes(subscriptions: Subscriptions) -> None:
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    home = await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )

    with pytest.raises(ValueError):
        await subscriptions.update_settings(
            user_id, home.id, notify_on_update=False, remind_before_off_min=45
        )
    with pytest.raises(ValueError):
        await subscriptions.update_settings(user_id, home.id, remind_before_on_min=-15)
    assert await subscriptions.get(user_id, home.id) == home
