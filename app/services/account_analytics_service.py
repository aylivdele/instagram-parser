from typing import List
from statistics import mean


class AccountAnalyticsService:

    def calculate_account_average_speed(
        self,
        posts_speeds: List[float]
    ) -> float:

        valid_speeds = [s for s in posts_speeds if s > 0]

        if not valid_speeds:
            return 0.0

        return mean(valid_speeds)
