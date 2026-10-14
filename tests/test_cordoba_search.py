import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import update_idealista


class CordobaSearchTests(unittest.TestCase):
    def test_cordoba_search_is_sale_only_and_limited_to_two_days(self):
        cordoba = update_idealista.LOCATIONS["cordoba"]

        self.assertEqual(cordoba["operations"], ("sale",))
        self.assertEqual(cordoba["since"], "Y")
        self.assertEqual(cordoba["max_pages"], 5)

    def test_process_location_makes_only_one_bounded_sale_query(self):
        sale_results = pd.DataFrame(
            [{"propertyCode": "sale-1", "operation": "sale", "updateDate": "2026-10-14"}]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            location = {
                **update_idealista.LOCATIONS["cordoba"],
                "csv_path": str(Path(temp_dir) / "cordoba.csv"),
            }
            with (
                patch.object(update_idealista, "get_all_results", return_value=sale_results) as search,
                patch.object(update_idealista, "send_telegram_message"),
            ):
                update_idealista.process_location(location, "test-token")

        search.assert_called_once_with(
            "sale",
            "test-token",
            location["center"],
            location["distance"],
            session=None,
            max_pages=5,
            since="Y",
        )

    def test_pagination_stops_at_configured_max_pages(self):
        response = {
            "elementList": [{"propertyCode": "sale-1"}],
            "totalPages": 10,
            "actualPage": 1,
        }

        with (
            patch.object(update_idealista, "search_api", return_value=response) as search,
            patch.object(update_idealista.time, "sleep"),
        ):
            update_idealista.get_all_results(
                "sale",
                "test-token",
                "37.892375,-4.780324",
                "5000",
                max_pages=5,
                since="Y",
            )

        self.assertEqual(search.call_count, 5)
        self.assertIn("&since=Y", search.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
