"""Limiteur de débit de la connexion (BE-08) : horloge simulée, aucune attente réelle."""

import threading

import pytest

from app.core.ratelimit import (
    MAX_KEYS,
    LoginThrottle,
    RateLimited,
    SlidingWindow,
    account_key,
    client_key,
    forwarded_address,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


# --- Fenêtre glissante ------------------------------------------------------------------------


def test_up_to_the_limit_is_allowed_then_the_next_attempt_waits(clock):
    window = SlidingWindow(3, 60, clock=clock)
    assert [window.attempt("a") for _ in range(3)] == [0, 0, 0]
    assert window.attempt("a") == 60


def test_the_wait_is_until_the_oldest_event_leaves_the_window(clock):
    window = SlidingWindow(2, 60, clock=clock)
    window.attempt("a")
    clock.now += 25
    window.attempt("a")
    clock.now += 10  # 35 s depuis le premier : il sort de la fenêtre dans 25 s
    assert window.attempt("a") == 25
    assert window.retry_after("a") == 25


def test_the_wait_is_at_least_one_second_and_rounded_up(clock):
    window = SlidingWindow(1, 60, clock=clock)
    window.attempt("a")
    clock.now += 59.2
    assert window.attempt("a") == 1


def test_the_wait_is_rounded_up_never_down(clock):
    window = SlidingWindow(1, 60, clock=clock)
    window.attempt("a")
    clock.now += 10.5  # reste 49,5 s : attendre 49 s ne suffirait pas
    assert window.attempt("a") == 50
    clock.now += 49.0  # reste 0,5 s : 1 s, jamais 0
    assert window.attempt("a") == 1


def test_attempts_are_allowed_again_once_the_window_has_passed(clock):
    window = SlidingWindow(1, 60, clock=clock)
    window.attempt("a")
    assert window.attempt("a") > 0
    clock.now += 60
    assert window.attempt("a") == 0


def test_a_refused_attempt_is_not_counted_so_it_does_not_extend_the_wait(clock):
    window = SlidingWindow(1, 60, clock=clock)
    window.attempt("a")
    for _ in range(5):
        clock.now += 1
        assert window.attempt("a") > 0
    clock.now += 55  # 60 s depuis le seul essai compté
    assert window.attempt("a") == 0


def test_keys_do_not_share_their_budget(clock):
    window = SlidingWindow(1, 60, clock=clock)
    assert window.attempt("a") == 0
    assert window.attempt("b") == 0
    assert window.attempt("a") > 0


def test_retry_after_counts_nothing_and_record_and_reset_work(clock):
    window = SlidingWindow(2, 60, clock=clock)
    assert [window.retry_after("a") for _ in range(5)] == [0] * 5
    window.record("a")
    assert window.retry_after("a") == 0
    window.record("a")
    assert window.retry_after("a") == 60
    window.reset("a")
    assert window.retry_after("a") == 0
    window.reset("inconnue")  # sans effet, sans erreur


def test_memory_is_bounded_and_the_least_recently_seen_key_is_forgotten(clock):
    window = SlidingWindow(1, 60, clock=clock, max_keys=3)
    for key in ("a", "b", "c"):
        window.attempt(key)
    window.attempt("a")  # refusé, mais « a » redevient la plus récente
    window.attempt("d")  # dépasse la borne : « b », la plus ancienne, est oubliée
    assert len(window) == 3
    assert window.retry_after("b") == 0
    assert window.retry_after("a") > 0
    assert MAX_KEYS >= 1000, "la borne par défaut ne gêne pas un usage normal"


def test_expired_keys_are_dropped_when_seen_again(clock):
    window = SlidingWindow(1, 60, clock=clock)
    window.attempt("a")
    clock.now += 61
    assert window.retry_after("a") == 0
    assert len(window) == 0


def test_the_limit_holds_when_threads_attempt_at_the_same_time():
    window = SlidingWindow(50, 60)
    allowed: list[int] = []

    def worker() -> None:
        for _ in range(20):
            if window.attempt("a") == 0:
                allowed.append(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) == 50, "ni plus, ni moins que la limite, malgré 200 essais simultanés"


# --- Clés -------------------------------------------------------------------------------------


def test_an_account_key_ignores_case_and_surrounding_spaces_and_hides_the_name():
    assert account_key(" Operateur1 ") == account_key("operateur1")
    assert account_key("operateur1") != account_key("operateur2")
    assert "operateur1" not in account_key("operateur1")


def test_an_ipv4_address_is_its_own_key():
    assert client_key("192.0.2.10") == "192.0.2.10"


def test_an_ipv6_client_is_keyed_by_its_64_bit_network():
    assert client_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == client_key("2001:db8:1:2::1")
    assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")


@pytest.mark.parametrize("address", [None, "", "testclient", "pas une adresse", "999.1.1.1"])
def test_an_unreadable_address_shares_one_key_instead_of_failing(address):
    assert client_key(address) == "inconnue"


# --- Adresse derrière un relais de confiance --------------------------------------------------


def test_without_trusted_proxy_the_forwarded_header_is_ignored():
    assert forwarded_address("10.0.0.1", "203.0.113.9", 0) == "10.0.0.1"


def test_behind_one_proxy_the_last_entry_is_the_client():
    assert forwarded_address("10.0.0.1", "203.0.113.9", 1) == "203.0.113.9"


def test_a_client_cannot_choose_its_address_by_writing_the_header_itself():
    # Le client écrit « 198.51.100.1 » ; le relais ajoute l'adresse qu'il a vraiment vue.
    assert forwarded_address("10.0.0.1", "198.51.100.1, 203.0.113.9", 1) == "203.0.113.9"


def test_behind_two_proxies_the_second_from_the_right_is_the_client():
    assert forwarded_address("10.0.0.1", "203.0.113.9, 10.0.0.7", 2) == "203.0.113.9"


@pytest.mark.parametrize(
    "header",
    [None, "", "pas-une-adresse", "203.0.113.9"],
    ids=["absent", "vide", "illisible", "trop-court"],
)
def test_a_missing_or_unreadable_header_falls_back_to_the_connection(header):
    hops = 2 if header == "203.0.113.9" else 1
    assert forwarded_address("10.0.0.1", header, hops) == "10.0.0.1"


# --- Les deux limites de la connexion ---------------------------------------------------------


def throttle(clock, *, per_minute=5, failures=3, lockout=900) -> LoginThrottle:
    return LoginThrottle(
        attempts_per_minute=per_minute, max_failures=failures, lockout_s=lockout, clock=clock
    )


def test_failures_on_one_account_lock_it_even_for_the_right_password(clock):
    login = throttle(clock, per_minute=100)
    for _ in range(3):
        login.admit("192.0.2.1", "alice")
        login.failed("alice")
    with pytest.raises(RateLimited) as blocked:
        login.admit("192.0.2.2", "alice")  # une autre adresse : le blocage suit le compte
    assert blocked.value.retry_after_s == 900


def test_the_lock_ends_when_the_oldest_failure_leaves_the_window(clock):
    login = throttle(clock, per_minute=100)
    for _ in range(3):
        login.admit("192.0.2.1", "alice")
        login.failed("alice")
        clock.now += 1
    clock.now += 897  # 900 s depuis le premier échec
    login.admit("192.0.2.1", "alice")


def test_a_success_forgets_the_failures_of_the_account(clock):
    login = throttle(clock, per_minute=100)
    for _ in range(2):
        login.admit("192.0.2.1", "alice")
        login.failed("alice")
    login.succeeded("alice")
    for _ in range(2):  # de nouveau deux échecs permis, pas un seul
        login.admit("192.0.2.1", "alice")
        login.failed("alice")
    login.admit("192.0.2.1", "alice")


def test_an_unknown_account_is_limited_like_a_known_one(clock):
    login = throttle(clock, per_minute=100)
    for _ in range(3):
        login.admit("192.0.2.1", "personne-ne-s-appelle-ainsi")
        login.failed("personne-ne-s-appelle-ainsi")
    with pytest.raises(RateLimited):
        login.admit("192.0.2.1", "personne-ne-s-appelle-ainsi")


def test_a_lock_on_one_account_does_not_touch_another(clock):
    login = throttle(clock, per_minute=100)
    for _ in range(3):
        login.failed("alice")
    login.admit("192.0.2.1", "bob")


def test_one_client_is_limited_across_all_accounts(clock):
    login = throttle(clock, per_minute=3, failures=100)
    for name in ("a", "b", "c"):
        login.admit("192.0.2.1", name)
    with pytest.raises(RateLimited) as blocked:
        login.admit("192.0.2.1", "d")
    assert blocked.value.retry_after_s == 60
    login.admit("192.0.2.2", "d")  # un autre client n'est pas touché
    clock.now += 60
    login.admit("192.0.2.1", "d")


def test_a_locked_account_does_not_spend_the_budget_of_the_client(clock):
    login = throttle(clock, per_minute=2, failures=1)
    login.failed("alice")
    for _ in range(10):
        with pytest.raises(RateLimited):
            login.admit("192.0.2.1", "alice")
    login.admit("192.0.2.1", "bob")  # le budget de l'adresse est intact


def test_the_exception_says_how_long_to_wait():
    assert RateLimited(42).retry_after_s == 42
    assert "42" in str(RateLimited(42))
