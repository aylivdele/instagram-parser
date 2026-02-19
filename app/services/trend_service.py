from dataclasses import dataclass
from datetime import datetime
from typing import List
from statistics import mean


@dataclass
class TrendConfig:
    growth_threshold_percent: float
    max_post_age_hours: int
    min_snapshots: int


@dataclass
class SnapshotData:
    views: int
    checked_at: datetime


@dataclass
class PostTrendResult:
    post_id: int
    current_views: int
    views_per_hour: float
    avg_views_per_hour: float
    growth_rate: float
    is_trending: bool


class TrendService:

    def __init__(self, config: TrendConfig):
        self.config = config

    # ────────────────────────────────
    # Публичный метод
    # ────────────────────────────────

    def analyze_post(
        self,
        post_id: int,
        published_at: datetime,
        snapshots: List[SnapshotData],
        account_avg_speed: float,
    ) -> PostTrendResult:

        if not snapshots:
            return self._empty_result(post_id)

        snapshots = sorted(snapshots, key=lambda s: s.checked_at)

        current_snapshot = snapshots[-1]
        current_views = current_snapshot.views

        post_age_hours = self._hours_between(
            published_at,
            current_snapshot.checked_at
        )

        views_per_hour = self._calculate_current_speed(
            snapshots,
            post_age_hours
        )

        avg_speed = account_avg_speed or 0

        growth_rate = self._calculate_growth(
            views_per_hour,
            avg_speed
        )

        is_trending = self._is_trending(
            growth_rate,
            post_age_hours,
            len(snapshots)
        )

        return PostTrendResult(
            post_id=post_id,
            current_views=current_views,
            views_per_hour=views_per_hour,
            avg_views_per_hour=avg_speed,
            growth_rate=growth_rate,
            is_trending=is_trending,
        )

    # ────────────────────────────────
    # Расчёт текущей скорости
    # ────────────────────────────────

    def _calculate_current_speed(
        self,
        snapshots: List[SnapshotData],
        post_age_hours: float
    ) -> float:

        if len(snapshots) >= 2:
            prev = snapshots[-2]
            curr = snapshots[-1]

            delta_views = curr.views - prev.views
            delta_hours = self._hours_between(prev.checked_at, curr.checked_at)

            if delta_hours > 0 and delta_views >= 0:
                return delta_views / delta_hours

        if post_age_hours > 0:
            return snapshots[-1].views / post_age_hours

        return 0.0

    # ────────────────────────────────
    # Рост относительно среднего
    # ────────────────────────────────

    def _calculate_growth(self, current: float, avg: float) -> float:
        if avg <= 0:
            return 0.0
        return ((current - avg) / avg) * 100

    # ────────────────────────────────
    # Условие тренда
    # ────────────────────────────────

    def _is_trending(
        self,
        growth_rate: float,
        post_age_hours: float,
        snapshots_count: int
    ) -> bool:

        return (
            growth_rate >= self.config.growth_threshold_percent
            and post_age_hours <= self.config.max_post_age_hours
            and snapshots_count >= self.config.min_snapshots
        )

    # ────────────────────────────────
    # Утилиты
    # ────────────────────────────────

    def _hours_between(self, dt1: datetime, dt2: datetime) -> float:
        return (dt2 - dt1).total_seconds() / 3600

    def _empty_result(self, post_id: int) -> PostTrendResult:
        return PostTrendResult(
            post_id=post_id,
            current_views=0,
            views_per_hour=0,
            avg_views_per_hour=0,
            growth_rate=0,
            is_trending=False,
        )
